import { formatDollars } from '../api/engine';

/** Minimal SVG equity curve: [[ts_ms, equity], ...] with a dashed starting-balance line. */
export default function EquityChart({ curve, start, height = 70 }) {
  if (!curve || curve.length < 2) {
    return <div className="muted">No equity data yet.</div>;
  }
  const width = 600;
  const values = curve.map((p) => p[1]);
  const base = start ?? values[0];
  const lo = Math.min(...values, base);
  const hi = Math.max(...values, base);
  const span = hi - lo || 1;
  const t0 = curve[0][0];
  const t1 = curve[curve.length - 1][0] || t0 + 1;
  const x = (t) => ((t - t0) / Math.max(t1 - t0, 1)) * width;
  const y = (v) => height - 4 - ((v - lo) / span) * (height - 8);
  const points = curve
    .map(([t, v]) => `${x(t).toFixed(1)},${y(v).toFixed(1)}`)
    .join(' ');
  const last = values[values.length - 1];
  const color = last >= base ? '#8fe39b' : '#ff9a8f';
  return (
    <div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        style={{
          width: '100%',
          height,
          background: 'rgba(0,0,0,0.2)',
          borderRadius: 6,
        }}
        role="img"
        aria-label="Equity curve"
      >
        <line
          x1="0"
          x2={width}
          y1={y(base)}
          y2={y(base)}
          stroke="rgba(255,255,255,0.3)"
          strokeDasharray="4 4"
        />
        <polyline
          fill="none"
          stroke={color}
          strokeWidth="1.5"
          points={points}
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div className="muted">
        equity {formatDollars(last)} (low {formatDollars(lo)}, high{' '}
        {formatDollars(hi)}, start {formatDollars(base)})
      </div>
    </div>
  );
}
