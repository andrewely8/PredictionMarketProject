import { Panel } from 'react-resizable-panels';
import { useEffect, useState } from 'react';
import { useGlobal } from '../contexts/GlobalContext';
import { formatBytes, formatDollars, getJSON, postJSON } from '../api/engine';
import { analyzeDataPrompt, improveStrategyPrompt } from '../api/prompts';
import ReportView, { pnlClass } from './ReportView';
import '../App.css';

function DataFile({ file }) {
  const { currentReplayFile, setCurrentReplayFile, askAI } = useGlobal();
  return (
    <div
      className={`fileListItem ${currentReplayFile === file.name ? 'selected' : ''}`}
    >
      <span className="name" title={file.name}>
        {file.name}
      </span>
      <span className="muted">{formatBytes(file.size_bytes)}</span>
      <button type="button" onClick={() => setCurrentReplayFile(file.name)}>
        replay
      </button>
      <button
        type="button"
        title="Ask the AI to analyze this recording"
        onClick={() => askAI(analyzeDataPrompt(file.name), [file.name])}
      >
        AI
      </button>
    </div>
  );
}

function StrategyFile({ file }) {
  const {
    workspace,
    currentTestFile,
    setCurrentTestFile,
    currentReplayFile,
    askAI,
  } = useGlobal();
  const latest = workspace?.reports.find((r) => r.strategy === file.name);
  return (
    <div
      className={`fileListItem ${currentTestFile === file.name ? 'selected' : ''}`}
    >
      <span className="name" title={file.name}>
        {file.name}
      </span>
      {latest && (
        <span
          className={pnlClass(latest.pnl)}
          title={`last run on ${latest.data_file}`}
        >
          {formatDollars(latest.pnl)}
        </span>
      )}
      <button type="button" onClick={() => setCurrentTestFile(file.name)}>
        test
      </button>
      <button
        type="button"
        title="Open in your editor"
        onClick={() =>
          window.electronAPI.openPath(`${workspace.dir}/${file.name}`)
        }
      >
        edit
      </button>
      <button
        type="button"
        title="Ask the AI to improve this strategy"
        onClick={() => {
          const dataFile = latest?.data_file ?? currentReplayFile;
          askAI(
            improveStrategyPrompt({
              strategy: file.name,
              dataFile,
              reportFile: latest?.report_file,
              pnl: latest?.pnl,
            }),
            dataFile ? [dataFile] : [],
          );
        }}
      >
        AI
      </button>
    </div>
  );
}

function NewStrategy({ onCreated }) {
  const { engineOnline } = useGlobal();
  const [templates, setTemplates] = useState([]);
  const [name, setName] = useState('');
  const [template, setTemplate] = useState('starter');
  const [message, setMessage] = useState(null);

  // Load once the engine is up (the panel renders before the engine has started).
  useEffect(() => {
    if (!engineOnline) return;
    getJSON('/workspace/templates')
      .then(setTemplates)
      .catch(() => setTemplates([]));
  }, [engineOnline]);

  async function create(e) {
    e.preventDefault();
    try {
      const out = await postJSON('/workspace/strategies', { name, template });
      setMessage({ ok: true, text: `Created ${out.name}` });
      setName('');
      onCreated(out.name);
    } catch (err) {
      setMessage({ ok: false, text: err.message });
    }
  }

  const summary = templates.find((t) => t.template === template)?.summary;
  return (
    <form className="card" onSubmit={create}>
      <div className="row">
        <input
          className="textInput"
          placeholder="new_strategy.py"
          value={name}
          onChange={(e) => setName(e.target.value)}
          style={{ flex: 1, minWidth: 120 }}
        />
        <select
          value={template}
          onChange={(e) => setTemplate(e.target.value)}
          aria-label="Template"
        >
          {templates.map((t) => (
            <option key={t.template} value={t.template}>
              {t.template}
            </option>
          ))}
        </select>
        <button type="submit" disabled={!name.trim()}>
          New strategy
        </button>
      </div>
      {summary && <div className="muted">{summary}</div>}
      {message && (
        <div className={message.ok ? 'ok' : 'bad'}>{message.text}</div>
      )}
    </form>
  );
}

export default function Workspace() {
  const {
    workspace,
    workspaceError,
    refreshWorkspace,
    settings,
    updateSettings,
    setCurrentTestFile,
    askAI,
    engineOnline,
  } = useGlobal();
  const [viewReport, setViewReport] = useState(null);

  async function chooseWorkspace() {
    const dir = await window.electronAPI.selectDirectory(
      settings?.workspace_dir,
    );
    if (dir) await updateSettings({ workspace_dir: dir });
  }

  return (
    <Panel className="panel" collapsible minSize={200}>
      <div className="panelTitleContainer">
        <div className="panelTitle">Workspace</div>
        <div className="MarketTrackerInteriorContainer">
          <div className="panelBody">
            <div className="row">
              <button
                type="button"
                onClick={refreshWorkspace}
                disabled={!engineOnline}
              >
                Refresh
              </button>
              <button
                type="button"
                onClick={chooseWorkspace}
                disabled={!settings}
              >
                Change folder
              </button>
              <button
                type="button"
                onClick={() =>
                  workspace && window.electronAPI.openPath(workspace.dir)
                }
                disabled={!workspace}
              >
                Open folder
              </button>
            </div>
            <div className="path" title={workspace?.dir}>
              {workspace?.dir ??
                (engineOnline ? 'Loading...' : 'Starting engine...')}
            </div>
            {workspaceError && <div className="bad">{workspaceError}</div>}

            <span className="sectionTitle">data files:</span>
            {workspace?.data_files.length === 0 && (
              <div className="muted">
                No recordings yet - record one with the Market Tracker.
              </div>
            )}
            {workspace?.data_files.map((f) => (
              <DataFile file={f} key={f.name} />
            ))}

            <span className="sectionTitle">strategy files:</span>
            {workspace?.strategy_files.map((f) => (
              <StrategyFile file={f} key={f.name} />
            ))}
            <NewStrategy
              onCreated={async (name) => {
                await refreshWorkspace();
                setCurrentTestFile(name);
                window.electronAPI.openPath(`${workspace.dir}/${name}`);
              }}
            />

            <span className="sectionTitle">run reports:</span>
            {workspace?.reports.length === 0 && (
              <div className="muted">
                Run a strategy in the Replayer to create one.
              </div>
            )}
            {workspace?.reports.slice(0, 15).map((r) => (
              <div key={r.report_file} className="fileListItem">
                <span className="name" title={r.report_file}>
                  {r.strategy} <span className="muted">on {r.data_file}</span>
                </span>
                <span className={pnlClass(r.pnl)}>{formatDollars(r.pnl)}</span>
                <span className="muted">{r.fills} fills</span>
                <button
                  type="button"
                  onClick={() => setViewReport(r.report_file)}
                >
                  view
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
      {viewReport && (
        <ReportView
          reportFile={viewReport}
          onClose={() => setViewReport(null)}
          onAskAI={(report) => {
            askAI(
              improveStrategyPrompt({
                strategy: report.strategy,
                dataFile: report.data_file,
                reportFile: viewReport,
                pnl: report.account?.pnl,
              }),
              [report.data_file],
            );
            setViewReport(null);
          }}
        />
      )}
    </Panel>
  );
}
