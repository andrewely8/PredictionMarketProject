import { Panel } from 'react-resizable-panels';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useGlobal } from '../contexts/GlobalContext';
import { deleteJSON, formatBytes, getJSON, postJSON } from '../api/engine';
import '../App.css';

/** "7:30" + "pm" -> the next such local time (today or tomorrow), as an ISO string. */
function nextScheduledTime(text, ampm) {
  const m = /^\s*(\d{1,2})(?::(\d{2}))?\s*$/.exec(text || '');
  if (!m) return null;
  let hours = Number(m[1]) % 12;
  const minutes = Number(m[2] || 0);
  if (minutes > 59 || Number(m[1]) > 12 || Number(m[1]) < 1) return null;
  if (ampm === 'pm') hours += 12;
  const when = new Date();
  when.setHours(hours, minutes, 0, 0);
  if (when.getTime() <= Date.now()) when.setDate(when.getDate() + 1);
  return when.toISOString();
}

function MarketSearch({ onAdd, disabled }) {
  const [query, setQuery] = useState('');
  const [result, setResult] = useState(null);
  const [checked, setChecked] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function search(e) {
    e.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setError('');
    try {
      const r = await getJSON(
        `/collector/markets?q=${encodeURIComponent(query.trim())}`,
      );
      setResult(r);
      setChecked(
        r.markets.filter((mk) => mk.status === 'active').map((mk) => mk.ticker),
      );
      if (!r.markets.length) setError(`Nothing found for ${r.query}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <form className="row" onSubmit={search}>
        <input
          className="textInput"
          placeholder="Event / series / market ticker, e.g. KXMLBGAME"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ flex: 1 }}
          disabled={disabled}
        />
        <button type="submit" disabled={disabled || busy}>
          {busy ? 'Searching...' : 'Search'}
        </button>
      </form>
      {error && <div className="warn">{error}</div>}
      {result && result.markets.length > 0 && (
        <div
          className="card"
          style={{ maxHeight: 160, overflow: 'auto', marginTop: 4 }}
        >
          <div className="muted">
            {result.markets.length} market(s) for {result.kind} {result.query}
          </div>
          {result.markets.map((mk) => (
            <label
              key={mk.ticker}
              className="fileListItem"
              htmlFor={`mk-${mk.ticker}`}
            >
              <input
                id={`mk-${mk.ticker}`}
                type="checkbox"
                checked={checked.includes(mk.ticker)}
                onChange={() =>
                  setChecked((c) =>
                    c.includes(mk.ticker)
                      ? c.filter((t) => t !== mk.ticker)
                      : [...c, mk.ticker],
                  )
                }
              />
              <span className="name mono">{mk.ticker}</span>
              <span className="muted">
                {mk.subtitle || mk.title} | {mk.status}
                {mk.yes_bid_dollars
                  ? ` | ${mk.yes_bid_dollars}/${mk.yes_ask_dollars}`
                  : ''}
              </span>
            </label>
          ))}
          <div className="row">
            <button
              type="button"
              disabled={!checked.length}
              onClick={() => onAdd(checked)}
            >
              Add {checked.length} to tickers
            </button>
            <button type="button" onClick={() => setResult(null)}>
              Clear
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function EventTrackForm({ onStarted }) {
  const { workspace, settings } = useGlobal();
  const [input, setInput] = useState('');
  const [saveDirPath, setSaveDirPath] = useState(null);
  const [scheduleAhead, setScheduleAhead] = useState(false);
  const [timeInput, setTimeInput] = useState('');
  const [ampm, setAmpm] = useState('pm');
  const [stopAfter, setStopAfter] = useState('');
  const [processInfo, setProcessInfo] = useState(null);
  const [busy, setBusy] = useState(false);

  function addTickers(tickers) {
    const existing = input.split(/[\s,]+/).filter(Boolean);
    const merged = [
      ...existing,
      ...tickers.filter((t) => !existing.includes(t)),
    ];
    setInput(merged.join(', '));
  }

  async function chooseDirectory() {
    const directory = await window.electronAPI.selectDirectory(
      saveDirPath || workspace?.dir,
    );
    if (directory) setSaveDirPath(directory);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const body = { tickers: [input], save_dir: saveDirPath };
    if (scheduleAhead) {
      const at = nextScheduledTime(timeInput, ampm);
      if (!at) {
        setProcessInfo({
          error: true,
          text: 'Enter a start time like 7:30 or 7',
        });
        return;
      }
      body.start_at = at;
    }
    if (stopAfter) body.stop_after_minutes = Number(stopAfter);
    setBusy(true);
    setProcessInfo({ text: 'validating...' });
    try {
      const job = await postJSON('/collector/jobs', body);
      const when = job.start_at
        ? `starts ${new Date(job.start_at * 1000).toLocaleString()}`
        : 'recording';
      setProcessInfo({ text: `${when} -> ${job.file}` });
      setInput('');
      onStarted();
    } catch (err) {
      setProcessInfo({ error: true, text: err.message });
    } finally {
      setBusy(false);
    }
  }

  const credsOk = settings?.credentials?.[settings?.kalshi_env]?.ok;

  return (
    <div className="card" style={{ marginBottom: 6 }}>
      <MarketSearch onAdd={addTickers} disabled={busy} />
      <form
        onSubmit={handleSubmit}
        style={{ display: 'flex', flexDirection: 'row', marginTop: 4 }}
      >
        <textarea
          name="market_tickers"
          style={{ resize: 'none', flex: 1 }}
          rows="5"
          placeholder="Market tickers, comma separated"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={busy}
        />
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            padding: '2px',
            gap: 2,
          }}
        >
          <label className="row" htmlFor="schedule-ahead">
            <input
              id="schedule-ahead"
              type="checkbox"
              checked={scheduleAhead}
              onChange={() => setScheduleAhead(!scheduleAhead)}
            />
            Schedule ahead
          </label>
          <div className="row">
            <input
              className="textInput"
              type="text"
              size="4"
              placeholder="7:30"
              value={timeInput}
              onChange={(e) => setTimeInput(e.target.value)}
              disabled={!scheduleAhead}
            />
            {['am', 'pm'].map((v) => (
              <label key={v} htmlFor={`ampm-${v}`}>
                <input
                  id={`ampm-${v}`}
                  type="radio"
                  name="time_ampm"
                  value={v}
                  checked={ampm === v}
                  onChange={() => setAmpm(v)}
                  disabled={!scheduleAhead}
                />
                {v.toUpperCase()}
              </label>
            ))}
          </div>
          <label className="row" htmlFor="stop-after">
            Stop after
            <input
              id="stop-after"
              className="textInput"
              type="number"
              min="1"
              size="4"
              style={{ width: 60 }}
              placeholder="min"
              value={stopAfter}
              onChange={(e) => setStopAfter(e.target.value)}
            />
          </label>
          <button
            type="button"
            onClick={chooseDirectory}
            title={saveDirPath || workspace?.dir}
          >
            Choose Dir
          </button>
          <button type="submit" disabled={busy || !input.trim()}>
            TRACK
          </button>
        </div>
      </form>
      <div className="path" title={saveDirPath || workspace?.dir}>
        Saving to: {saveDirPath || workspace?.dir || '...'}
      </div>
      {settings && !credsOk && (
        <div className="warn">
          No Kalshi {settings.kalshi_env} keys found - set the keys folder in
          File → Settings.
        </div>
      )}
      {processInfo && (
        <div className={processInfo.error ? 'bad' : 'ok'}>
          {processInfo.text}
        </div>
      )}
    </div>
  );
}

const STATUS_CLASS = {
  recording: 'ok',
  connecting: 'warn',
  reconnecting: 'warn',
  scheduled: 'muted',
  error: 'bad',
  finished: 'muted',
  stopped: 'muted',
};

function JobList({ jobs, now, onChange }) {
  const { workspace, setCurrentReplayFile, refreshWorkspace } = useGlobal();
  if (!jobs.length) return null;

  async function act(fn) {
    try {
      await fn();
    } finally {
      onChange();
    }
  }

  return (
    <div>
      <div className="sectionTitle">Recordings</div>
      {jobs.map((job) => {
        const active = !['stopped', 'finished', 'error'].includes(job.status);
        const inWorkspace =
          workspace && job.save_path.startsWith(workspace.dir);
        const age = job.last_message_at
          ? Math.round(now / 1000 - job.last_message_at)
          : null;
        return (
          <div key={job.id} className="card" style={{ marginBottom: 4 }}>
            <div className="row">
              <span className="mono" style={{ flex: 1 }}>
                {job.file}
              </span>
              <span className={STATUS_CLASS[job.status] || ''}>
                {job.status}
              </span>
            </div>
            <div className="muted">
              {job.tickers.length} market(s) | {job.deltas.toLocaleString()}{' '}
              updates | {formatBytes(job.bytes_written)}
              {age !== null && active ? ` | last update ${age}s ago` : ''}
              {job.reconnects ? ` | ${job.reconnects} reconnect(s)` : ''}
              {job.stop_at
                ? ` | stops ${new Date(job.stop_at * 1000).toLocaleTimeString()}`
                : ''}
            </div>
            {job.error && (
              <div className={job.status === 'error' ? 'bad' : 'warn'}>
                {job.error}
              </div>
            )}
            <div className="row">
              {active ? (
                <button
                  type="button"
                  onClick={() =>
                    act(() => postJSON(`/collector/jobs/${job.id}/stop`))
                  }
                >
                  Stop
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() =>
                    act(() => deleteJSON(`/collector/jobs/${job.id}`))
                  }
                >
                  Remove
                </button>
              )}
              {inWorkspace && job.messages > 0 && (
                <button
                  type="button"
                  onClick={async () => {
                    await refreshWorkspace();
                    setCurrentReplayFile(job.file);
                  }}
                >
                  replay
                </button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function MarketTracker() {
  const { engineOnline, refreshWorkspace } = useGlobal();
  const [numTrackedEvents, setNumTrackedEvents] = useState(1);
  const [jobs, setJobs] = useState([]);
  const [now, setNow] = useState(0);

  const activeJobs = useRef(new Set());

  const loadJobs = useCallback(async () => {
    try {
      const list = await getJSON('/collector/jobs');
      setJobs(list);
      setNow(Date.now());
      // When a recording finishes, refresh the Workspace so the file shows its final size.
      const active = new Set(
        list
          .filter((j) => !['stopped', 'finished', 'error'].includes(j.status))
          .map((j) => j.id),
      );
      if ([...activeJobs.current].some((id) => !active.has(id)))
        void refreshWorkspace();
      activeJobs.current = active;
    } catch {
      /* engine offline */
    }
  }, [refreshWorkspace]);

  useEffect(() => {
    if (!engineOnline) return undefined;
    const first = setTimeout(loadJobs, 0);
    const timer = setInterval(loadJobs, 2000);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [engineOnline, loadJobs]);

  return (
    <Panel className="panel" collapsible minSize={200}>
      <div className="panelTitleContainer">
        <div className="panelTitle">Market Tracker</div>
        <div className="MarketTrackerInteriorContainer">
          <div className="panelBody">
            <div className="row">
              <button
                type="button"
                onClick={() =>
                  window.electronAPI.openExternal('https://kalshi.com/markets')
                }
              >
                Find Open Markets
              </button>
              {!engineOnline && (
                <span className="warn">Starting engine...</span>
              )}
            </div>
            <span>
              Search markets or enter market tickers as a comma separated list:
            </span>
            {Array.from({ length: numTrackedEvents }).map((_, i) => (
              <EventTrackForm
                key={i}
                onStarted={() => {
                  void loadJobs();
                  void refreshWorkspace();
                }}
              />
            ))}
            <div className="row">
              <button
                type="button"
                onClick={() => setNumTrackedEvents(numTrackedEvents + 1)}
              >
                Add Event
              </button>
              <button
                type="button"
                disabled={numTrackedEvents <= 1}
                onClick={() => setNumTrackedEvents(numTrackedEvents - 1)}
              >
                Remove Event
              </button>
            </div>
            <JobList
              now={now}
              jobs={jobs}
              onChange={() => {
                void loadJobs();
                void refreshWorkspace();
              }}
            />
          </div>
        </div>
      </div>
    </Panel>
  );
}
