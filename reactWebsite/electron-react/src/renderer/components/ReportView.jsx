import { useEffect, useState } from 'react';
import { formatDollars, getJSON } from '../api/engine';
import Modal from './Modal';
import EquityChart from './EquityChart';

export function pnlClass(v) {
  if (v === null || v === undefined) return '';
  if (v > 0) return 'ok';
  if (v < 0) return 'bad';
  return '';
}

export default function ReportView({ reportFile, onClose, onAskAI }) {
  const [report, setReport] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    getJSON(`/strategy/reports/${encodeURIComponent(reportFile)}`)
      .then(setReport)
      .catch((e) => setError(e.message));
  }, [reportFile]);

  const a = report?.account;
  return (
    <Modal title={`Run report: ${reportFile}`} onClose={onClose} wide>
      {error && <div className="bad">{error}</div>}
      {report && (
        <>
          <div>
            <b>{report.strategy}</b> on <b>{report.data_file}</b> |{' '}
            {report.status}
            {report.error ? ` (${report.error})` : ''} | speed {report.speed} |{' '}
            {report.started} | {report.wall_seconds}s |{' '}
            {Math.round((report.replay?.coverage ?? 0) * 100)}% of the recording
          </div>
          <div className="row">
            <span>
              P&amp;L <b className={pnlClass(a.pnl)}>{formatDollars(a.pnl)}</b>
            </span>
            <span>realized {formatDollars(a.realized_pnl)}</span>
            <span>fees {formatDollars(a.fees)}</span>
            <span>max drawdown {formatDollars(report.max_drawdown)}</span>
            <span>
              {a.fills} fills / {a.orders} orders
            </span>
            <span>{a.contracts_traded} contracts</span>
            {report.orders_rejected > 0 && (
              <span className="warn">{report.orders_rejected} rejected</span>
            )}
          </div>
          <EquityChart
            curve={report.equity_curve}
            start={report.starting_balance}
            height={110}
          />
          <div className="sectionTitle">Per market</div>
          <table className="dataTable">
            <thead>
              <tr>
                <th>Market</th>
                <th>Position</th>
                <th>Realized P&amp;L</th>
                <th>Fees</th>
                <th>Fills</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(report.per_market || {}).map(([t, m]) => (
                <tr key={t}>
                  <td className="mono">{t}</td>
                  <td>{m.position}</td>
                  <td className={pnlClass(m.realized_pnl)}>
                    {formatDollars(m.realized_pnl, 4)}
                  </td>
                  <td>{formatDollars(m.fees)}</td>
                  <td>{m.fills}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="sectionTitle">Strategy console (last lines)</div>
          <pre className="console">
            {(report.console_tail || []).join('\n')}
          </pre>
          <div className="sectionTitle">Simulator assumptions</div>
          <ul className="muted" style={{ margin: 0 }}>
            {(report.assumptions || []).map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
          {onAskAI && (
            <div className="row">
              <button type="button" onClick={() => onAskAI(report)}>
                Ask AI to improve this strategy
              </button>
            </div>
          )}
        </>
      )}
    </Modal>
  );
}
