"""Generate a small synthetic recording in the exact format written by collectMarketData.py.

Used by the tests and for local smoke testing (no real Kalshi data is committed to the repo).
The synthetic market has a deliberately planted relation between top-of-book imbalance and the
next price move, so the analysis tools have something to find.

    python tests/sample_data.py out.jsonl --minutes 30
"""

import argparse
import json
import random


def _fmt_price(cents: int) -> str:
    return f"{cents / 100:.4f}"


def _desired(fair: int, rng: random.Random, depth: int = 8) -> tuple[dict, dict]:
    yes = {fair - 1 - k: rng.randint(50, 2000) for k in range(depth) if fair - 1 - k >= 1}
    no = {(100 - fair - 1) - k: rng.randint(50, 2000) for k in range(depth) if (100 - fair - 1) - k >= 1}
    return yes, no


def generate(path: str, minutes: int = 30, seed: int = 7,
             tickers=("KXSYNTH-26OCT15-AAA", "KXSYNTH-26OCT15-BBB")) -> str:
    rng = random.Random(seed)
    t0 = 1_791_000_000_000
    lines = [{"type": "subscribed", "id": 1, "msg": {"channel": "orderbook_delta", "sid": 1}}]
    state = {}
    seq = 0
    for i, tk in enumerate(tickers):
        fair = 45 + 10 * i
        yes, no = _desired(fair, rng)
        state[tk] = {"fair": fair, "yes": dict(yes), "no": dict(no)}
        seq += 1
        lines.append({"type": "orderbook_snapshot", "sid": 1, "seq": seq, "msg": {
            "market_ticker": tk, "market_id": f"id-{i}",
            "yes_dollars_fp": [[_fmt_price(p), f"{q:.2f}"] for p, q in sorted(yes.items())],
            "no_dollars_fp": [[_fmt_price(p), f"{q:.2f}"] for p, q in sorted(no.items())]}})

    def emit(tk, side, price, delta, ts):
        nonlocal seq
        seq += 1
        lines.append({"type": "orderbook_delta", "sid": 1, "seq": seq, "msg": {
            "market_ticker": tk, "market_id": "x", "price_dollars": _fmt_price(price),
            "delta_fp": f"{delta:.2f}", "side": side, "ts": "", "ts_ms": ts}})

    ts = t0
    end = t0 + minutes * 60_000
    while ts < end:
        ts += rng.randint(50, 400)
        tk = rng.choice(tickers)
        st = state[tk]
        best_yes, best_no = max(st["yes"]), max(st["no"])
        bq, aq = st["yes"][best_yes], st["no"][best_no]
        imb = (bq - aq) / (bq + aq)
        if rng.random() < 0.03:  # price move, biased toward the heavy side (planted signal)
            step = 1 if rng.random() < 0.5 + 0.35 * imb else -1
            st["fair"] = min(90, max(10, st["fair"] + step))
            yes, no = _desired(st["fair"], rng)
            for side, cur, want in (("yes", st["yes"], yes), ("no", st["no"], no)):
                for p in list(cur):
                    if p not in want:
                        emit(tk, side, p, -cur.pop(p), ts)
                for p, q in want.items():
                    if p not in cur:
                        cur[p] = q
                        emit(tk, side, p, q, ts)
        else:  # size noise on an existing level
            side = rng.choice(("yes", "no"))
            book = st[side]
            p = max(book) if rng.random() < 0.6 else rng.choice(list(book))
            delta = rng.randint(-int(book[p]) + 1, 600)
            book[p] += delta
            emit(tk, side, p, delta, ts)

    with open(path, "w", encoding="utf-8") as fh:
        for obj in lines:
            fh.write(json.dumps(obj) + "\n")
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--minutes", type=int, default=30)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    print(generate(a.out, a.minutes, a.seed))
