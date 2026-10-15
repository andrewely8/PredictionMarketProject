import { useEffect, useRef, useState } from 'react';
import { Panel } from 'react-resizable-panels';
import { useGlobal } from '../contexts/GlobalContext';
import {
  ENGINE_WS,
  formatClock,
  formatDollars,
  formatDuration,
  postJSON,
} from '../api/engine';
import { improveStrategyPrompt } from '../api/prompts';
import EquityChart from './EquityChart';
import ReportView, { pnlClass } from './ReportView';
import '../App.css';

const SPEEDS = [1, 2, 5, 10, 50, 100, 500, null]; // null = Max
const SESSION = 'replayer';
const RUNNING = ['starting', 'waiting', 'running'];

/** Live state of the Replayer's simulator session, pushed by the engine ~5x/second. */
function useReplayState(enabled) {
  const [state, setState] = useState(null);
  useEffect(() => {
    if (!enabled) return undefined;
    let ws;
    let retry;
    let closed = false;
    function connect() {
      ws = new WebSocket(`${ENGINE_WS}/replay/${SESSION}/stream`);
      ws.onmessage = (e) => setState(JSON.parse(e.data));
      ws.onclose = () => {
        if (!closed) retry = setTimeout(connect, 1500);
      };
    }
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      ws?.close();
    };
  }, [enabled]);
  return state;
}

function speedLabel(speed) {
  return speed === null ? 'Max' : `${speed}`;
}

function TopOfBook({ books }) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'row',
        flexWrap: 'wrap',
        gap: 14,
      }}
    >
      {Object.entries(books || {}).map(([ticker, book]) => (
        <div key={ticker} style={{ marginTop: '6px' }}>
          <span className="mono">{ticker}</span>
          <div>
            <span style={{ margin: '5px' }}>
              best_yes_bid_dollars: {book.best_yes_bid_dollars ?? '-'}
            </span>
            <span style={{ margin: '5px' }}>
              best_yes_bid_volume: {book.best_yes_bid_volume ?? '-'}
            </span>
          </div>
          <div>
            <span style={{ margin: '5px' }}>
              best_yes_ask_dollars: {book.best_yes_ask_dollars ?? '-'}
            </span>
            <span style={{ margin: '5px' }}>
              best_yes_ask_volume: {book.best_yes_ask_volume ?? '-'}
            </span>
          </div>
          <div>
            <span style={{ margin: '5px' }}>
              best_no_bid_dollars: {book.best_no_bid_dollars ?? '-'}
            </span>
            <span style={{ margin: '5px' }}>
              best_no_bid_volume: {book.best_no_bid_volume ?? '-'}
            </span>
          </div>
          <div>
            <span style={{ margin: '5px' }}>
              best_no_ask_dollars: {book.best_no_ask_dollars ?? '-'}
            </span>
            <span style={{ margin: '5px' }}>
              best_no_ask_volume: {book.best_no_ask_volume ?? '-'}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

function StrategyView({ state }) {
  const consoleRef = useRef(null);
  const acct = state.account;
  useEffect(() => {
    consoleRef.current?.scrollTo(0, consoleRef.current.scrollHeight);
  }, [state.console]);
  if (!acct) return null;
  const positions = Object.entries(acct.positions || {});
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'row',
        gap: 12,
        flexWrap: 'wrap',
      }}
    >
      <div style={{ flex: '1 1 320px', minWidth: 280 }}>
        <div className="sectionTitle">Simulated account</div>
        <div className="row">
          <span>
            P&amp;L{' '}
            <b className={pnlClass(acct.pnl)}>{formatDollars(acct.pnl)}</b>
          </span>
          <span>equity {formatDollars(acct.equity)}</span>
          <span>cash {formatDollars(acct.cash)}</span>
          <span>fees {formatDollars(acct.fees)}</span>
          <span>
            {acct.fills} fills / {acct.orders} orders
          </span>
          {acct.open_orders > 0 && <span>{acct.open_orders} resting</span>}
        </div>
        <div className="muted">
          positions:{' '}
          {positions.length
            ? positions
                .map(
                  ([t, q]) =>
                    `${t.split('-').pop()} ${q > 0 ? `+${q} YES` : `${-q} NO`}`,
                )
                .join(' | ')
            : 'flat'}
        </div>
        <EquityChart
          curve={state.equity_curve}
          start={acct.equity - acct.pnl}
        />
        <div className="sectionTitle">Recent fills</div>
        <table className="dataTable">
          <tbody>
            {(state.recent_fills || []).slice(0, 8).map((f) => (
              <tr key={f.trade_id}>
                <td>{formatClock(f.ts_ms)}</td>
                <td className="mono">{f.market_ticker.split('-').pop()}</td>
                <td>{f.action === 'buy' ? 'buy YES' : 'sell YES'}</td>
                <td>{f.count_fp}</td>
                <td>@ {f.yes_price_dollars}</td>
                <td className="muted">{f.is_taker ? 'taker' : 'maker'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ flex: '1 1 320px', minWidth: 280 }}>
        <div className="sectionTitle">Strategy console</div>
        <pre className="console" ref={consoleRef} style={{ maxHeight: 260 }}>
          {(state.console || []).join('\n') || 'Strategy output appears here.'}
        </pre>
      </div>
    </div>
  );
}

export default function Replayer() {
  const {
    engineOnline,
    currentReplayFile,
    currentTestFile,
    askAI,
    refreshWorkspace,
  } = useGlobal();
  const state = useReplayState(engineOnline);
  const [speedIndex, setSpeedIndex] = useState(3);
  const [error, setError] = useState('');
  const [viewReport, setViewReport] = useState(null);
  const [seekValue, setSeekValue] = useState(null);
  const lastRunStatus = useRef(null);

  const speed = SPEEDS[speedIndex];
  const run = state?.run;
  const strategyRunning = run && RUNNING.includes(run.status);
  const loaded = state && state.file && state.state !== 'loading';
  const playing = state?.state === 'playing';

  // Load the recording chosen in the Workspace.
  useEffect(() => {
    if (!engineOnline || !currentReplayFile) return;
    postJSON(`/replay/${SESSION}/load`, { file: currentReplayFile })
      .then(() => setError(''))
      .catch((e) => setError(e.message));
  }, [engineOnline, currentReplayFile]);

  // Refresh the workspace (new report) when a run finishes.
  useEffect(() => {
    if (
      run &&
      lastRunStatus.current &&
      RUNNING.includes(lastRunStatus.current) &&
      !RUNNING.includes(run.status)
    ) {
      void refreshWorkspace();
    }
    lastRunStatus.current = run?.status ?? null;
  }, [run, refreshWorkspace]);

  async function call(path, body) {
    setError('');
    try {
      await postJSON(path, body);
    } catch (e) {
      setError(e.message);
    }
  }

  function changeSpeed() {
    const next = (speedIndex + 1) % SPEEDS.length;
    setSpeedIndex(next);
    if (playing) void call(`/replay/${SESSION}/play`, { speed: SPEEDS[next] });
  }

  function runStrategy() {
    if (strategyRunning) {
      void call(`/strategy/runs/${run.id}/stop`);
    } else {
      void call('/strategy/runs', {
        strategy: currentTestFile,
        data_file: currentReplayFile,
        speed,
        mode: 'replayer',
      });
    }
  }

  const elapsed = loaded ? state.clock_ts - state.start_ts : 0;
  const total = loaded ? state.end_ts - state.start_ts : 0;
  const finishedRun =
    run && !RUNNING.includes(run.status) && run.report_file ? run : null;

  return (
    <Panel className="panel" collapsible minSize={200} defaultSize="45%">
      <div className="panelTitleContainer">
        <div className="panelTitle">Replayer</div>
        <div className="MarketTrackerInteriorContainer">
          <div className="panelBody">
            <div className="row">
              <span>
                Data File:{' '}
                {currentReplayFile ?? (
                  <span className="muted">
                    choose &quot;replay&quot; on a data file
                  </span>
                )}
              </span>
              {state?.state === 'loading' && (
                <span className="warn">
                  loading {Math.round((state.load_progress || 0) * 100)}%...
                </span>
              )}
            </div>
            <div className="row">
              <span>
                Strategy File:{' '}
                {currentTestFile ?? (
                  <span className="muted">
                    choose &quot;test&quot; on a strategy file
                  </span>
                )}
              </span>
              <button
                type="button"
                onClick={runStrategy}
                disabled={
                  !strategyRunning &&
                  (!currentTestFile || !currentReplayFile || !loaded)
                }
              >
                {strategyRunning ? 'Stop Strategy' : 'Run Strategy TEST'}
              </button>
              {run && (
                <span className={run.status === 'failed' ? 'bad' : 'muted'}>
                  {run.strategy}: {run.status}
                  {run.error ? ` - ${run.error}` : ''}
                </span>
              )}
            </div>

            <div className="row">
              <span style={{ marginRight: '10px' }}>Current Time:</span>
              <span className="mono">
                {loaded ? formatClock(state.clock_ts) : '--:--:--'}
              </span>
              <span className="muted">
                {formatDuration(elapsed)} / {formatDuration(total)}
                {loaded
                  ? ` | ${state.index.toLocaleString()} / ${state.events.toLocaleString()} updates`
                  : ''}
              </span>
            </div>
            <input
              className="seekBar"
              type="range"
              min="0"
              max="1000"
              aria-label="Replay position"
              value={seekValue ?? Math.round((state?.progress || 0) * 1000)}
              disabled={!loaded || strategyRunning}
              onChange={(e) => setSeekValue(Number(e.target.value))}
              onMouseUp={() => {
                if (seekValue !== null)
                  void call(`/replay/${SESSION}/seek`, {
                    fraction: seekValue / 1000,
                  });
                setSeekValue(null);
              }}
              onKeyUp={() => {
                if (seekValue !== null)
                  void call(`/replay/${SESSION}/seek`, {
                    fraction: seekValue / 1000,
                  });
                setSeekValue(null);
              }}
            />
            <div className="row">
              <button
                type="button"
                disabled={!loaded || strategyRunning || state.state === 'ended'}
                onClick={() =>
                  call(`/replay/${SESSION}/${playing ? 'pause' : 'play'}`, {
                    speed,
                  })
                }
              >
                {playing ? 'pause' : 'play'}
              </button>
              <span style={{ marginLeft: '10px' }}>Playback speed:</span>
              <button type="button" disabled={!loaded} onClick={changeSpeed}>
                {speedLabel(speed)}
              </button>
              <button
                type="button"
                disabled={!loaded || strategyRunning}
                onClick={() => call(`/replay/${SESSION}/reset`)}
              >
                reset
              </button>
              {state?.state === 'ended' && (
                <span className="muted">end of recording</span>
              )}
            </div>
            {error && <div className="bad">{error}</div>}

            {finishedRun && (
              <div className="card row">
                <span>
                  Run {finishedRun.status}: P&amp;L{' '}
                  <b className={pnlClass(state.account?.pnl)}>
                    {formatDollars(state.account?.pnl)}
                  </b>
                  , report saved.
                </span>
                <button
                  type="button"
                  onClick={() => setViewReport(finishedRun.report_file)}
                >
                  View report
                </button>
                <button
                  type="button"
                  onClick={() =>
                    askAI(
                      improveStrategyPrompt({
                        strategy: finishedRun.strategy,
                        dataFile: finishedRun.data_file,
                        reportFile: finishedRun.report_file,
                        pnl: state.account?.pnl,
                      }),
                      [finishedRun.data_file],
                    )
                  }
                >
                  Ask AI to improve
                </button>
              </div>
            )}

            {loaded && <TopOfBook books={state.books} />}
            {loaded && (state.connected_strategies > 0 || run) && (
              <StrategyView state={state} />
            )}
          </div>
        </div>
      </div>
      {viewReport && (
        <ReportView
          reportFile={viewReport}
          onClose={() => setViewReport(null)}
        />
      )}
    </Panel>
  );
}
