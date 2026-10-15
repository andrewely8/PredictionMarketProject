/**
 * AI Strategy Research panel: chat with the research agent about recordings, strategies and run
 * reports. Credentials and model calls live in the engine (/ai/...); nothing secret reaches here.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Panel } from 'react-resizable-panels';
import { useGlobal } from '../../contexts/GlobalContext';
import { ENGINE_URL, getJSON, postJSON, request } from '../../api/engine';
import ReportView from '../ReportView';
import ModelSelector from './ModelSelector';
import './AIResearchPanel.css';

const RUN_ACTIVE = ['starting', 'waiting', 'running'];

function ListSection({ title, items }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="air-section">
      <div className="air-sectionTitle">{title}</div>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function ArtifactCard({ artifact, onOpen, notify }) {
  const { refreshWorkspace, setCurrentTestFile } = useGlobal();
  const [run, setRun] = useState(null);
  const [added, setAdded] = useState(null);
  const [deleted, setDeleted] = useState(false);
  const [viewReport, setViewReport] = useState(null);
  const isPython = artifact.filename.endsWith('.py');
  const running = run && RUN_ACTIVE.includes(run.status);

  useEffect(() => {
    if (!running) return undefined;
    const timer = setTimeout(async () => {
      try {
        setRun(await getJSON(`/strategy/runs/${run.id}`));
      } catch (e) {
        setRun({ ...run, status: 'failed', error: e.message });
      }
    }, 1000);
    return () => clearTimeout(timer);
  }, [run, running]);

  const guard = (fn) => () => fn().catch((e) => notify(`Error: ${e.message}`));

  async function saveAs() {
    // A blob download makes Electron show its native "Save As" dialog.
    const res = await request(`/ai/artifacts/${artifact.id}/download`);
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement('a');
    a.href = url;
    a.download = artifact.filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function addToWorkspace() {
    const out = await postJSON(`/ai/artifacts/${artifact.id}/add-to-workspace`);
    setAdded(out.filename);
    await refreshWorkspace();
    notify(
      out.filename === artifact.filename
        ? `Added ${out.filename} to the workspace.`
        : `A file named ${artifact.filename} already existed; saved as ${out.filename}.`,
    );
  }

  async function remove() {
    if (!window.confirm(`Delete generated file ${artifact.filename}?`)) return;
    await request(`/ai/artifacts/${artifact.id}`, { method: 'DELETE' });
    setDeleted(true);
  }

  if (deleted) {
    return (
      <div className="air-artifact air-deleted">
        {artifact.filename} (deleted)
      </div>
    );
  }
  return (
    <div className="air-artifact">
      <div className="air-artifactHead">
        <b>{artifact.filename}</b>
        <span className="air-badge">{artifact.type}</span>
      </div>
      <div className="air-muted">{artifact.description}</div>
      <div className="air-buttons">
        <button type="button" onClick={guard(() => onOpen(artifact))}>
          Open
        </button>
        <button type="button" onClick={guard(saveAs)}>
          Save As
        </button>
        {!added ? (
          <button type="button" onClick={guard(addToWorkspace)}>
            Add to Workspace
          </button>
        ) : (
          isPython && (
            <button type="button" onClick={() => setCurrentTestFile(added)}>
              Use in Replayer
            </button>
          )
        )}
        {isPython && (
          <button
            type="button"
            disabled={running}
            onClick={guard(async () =>
              setRun(await postJSON(`/ai/artifacts/${artifact.id}/test`, {})),
            )}
          >
            {running ? 'Testing...' : 'Test'}
          </button>
        )}
        {running && (
          <button
            type="button"
            onClick={guard(async () =>
              setRun(await postJSON(`/strategy/runs/${run.id}/stop`)),
            )}
          >
            Stop
          </button>
        )}
        <button type="button" onClick={guard(remove)}>
          Delete
        </button>
      </div>
      {run && (
        <div className={`air-run air-run-${run.status}`}>
          Backtest on {run.data_file}: <b>{run.status}</b>
          {run.error ? ` - ${run.error}` : ''}
          {run.report_file && (
            <button
              type="button"
              onClick={() => setViewReport(run.report_file)}
            >
              View report
            </button>
          )}
        </div>
      )}
      {viewReport && (
        <ReportView
          reportFile={viewReport}
          onClose={() => setViewReport(null)}
        />
      )}
    </div>
  );
}

export default function AIResearchPanel() {
  const { engineOnline, workspace, aiRequest } = useGlobal();
  const [health, setHealth] = useState(null);
  const [selected, setSelected] = useState([]);
  const [sessionId, setSessionId] = useState(null);
  const [sessionFiles, setSessionFiles] = useState('');
  const [messages, setMessages] = useState([]);
  const [activity, setActivity] = useState([]);
  const [busy, setBusy] = useState(false);
  const [input, setInput] = useState('');
  const [notice, setNotice] = useState('');
  const [viewer, setViewer] = useState(null);
  const historyRef = useRef(null);
  const inputRef = useRef(null);
  const dataFiles = (workspace?.data_files ?? []).map((f) => f.name);

  useEffect(() => {
    if (!engineOnline) return undefined;
    let cancelled = false;
    getJSON('/ai/health')
      .then((h) => !cancelled && setHealth(h))
      .catch(() => !cancelled && setHealth(null));
    return () => {
      cancelled = true;
    };
  }, [engineOnline]);

  // The model selector polls /ai/llm/status; keep the readiness shown here in sync with it.
  const handleModelStatus = useCallback((s) => {
    setHealth((h) =>
      h
        ? {
            ...h,
            mode: s.mode,
            model: s.model,
            ready: s.ready,
            problem: s.problem,
          }
        : h,
    );
  }, []);

  // Requests from other panels ("AI" buttons, "Ask AI to improve") arrive prefilled.
  useEffect(() => {
    if (!aiRequest) return;
    setInput(aiRequest.message);
    if (aiRequest.dataFiles.length) setSelected(aiRequest.dataFiles);
    setNotice('Request prepared - review it and press Send.');
    inputRef.current?.focus();
  }, [aiRequest]);

  useEffect(() => {
    historyRef.current?.scrollTo(0, historyRef.current.scrollHeight);
  }, [messages, activity]);

  function toggle(file) {
    setSelected((cur) =>
      cur.includes(file) ? cur.filter((f) => f !== file) : [...cur, file],
    );
  }

  async function ensureSession() {
    const body = { data_files: selected.filter((f) => dataFiles.includes(f)) };
    const key = `${workspace?.dir}|${[...body.data_files].sort().join(',')}`;
    if (sessionId) {
      if (key !== sessionFiles) {
        await request(`/ai/sessions/${sessionId}/files`, {
          method: 'PUT',
          body: JSON.stringify(body),
        });
        setSessionFiles(key);
      }
      return sessionId;
    }
    const s = await postJSON('/ai/sessions', body);
    setSessionId(s.session_id);
    setSessionFiles(key);
    return s.session_id;
  }

  function resetConversation() {
    if (sessionId)
      request(`/ai/sessions/${sessionId}`, { method: 'DELETE' }).catch(
        () => {},
      );
    setSessionId(null);
    setSessionFiles('');
    setMessages([]);
    setActivity([]);
  }

  function handleEvent(ev, tools) {
    if (ev.event === 'tool_start') {
      tools.push({
        id: ev.id,
        tool: ev.tool,
        label: ev.label,
        status: 'running',
      });
    } else if (ev.event === 'tool_end') {
      const t = tools.find((x) => x.id === ev.id);
      if (t) t.status = ev.status;
    }
    setActivity([...tools]);
  }

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput('');
    setNotice('');
    setBusy(true);
    setMessages((m) => [...m, { role: 'user', text, files: [...selected] }]);
    const tools = [];
    setActivity([]);
    try {
      const sid = await ensureSession();
      const res = await fetch(`${ENGINE_URL}/ai/sessions/${sid}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || res.statusText);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let final = null;
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();
        lines.filter(Boolean).forEach((line) => {
          const ev = JSON.parse(line);
          if (ev.event === 'final') final = ev;
          else if (ev.event === 'error') throw new Error(ev.detail);
          else handleEvent(ev, tools);
        });
      }
      if (!final)
        throw new Error('The engine closed the stream without an answer.');
      setMessages((m) => [
        ...m,
        {
          role: 'assistant',
          response: final.response,
          artifacts: final.artifacts,
          tools,
        },
      ]);
    } catch (e) {
      if (String(e.message).startsWith('Unknown session')) setSessionId(null);
      setMessages((m) => [...m, { role: 'error', text: e.message, tools }]);
    } finally {
      setBusy(false);
      setActivity([]);
    }
  }

  async function openArtifact(artifact) {
    setViewer(await getJSON(`/ai/artifacts/${artifact.id}`));
  }

  const offline = !engineOnline || !health;
  const notReady = health && !health.ready;

  return (
    <Panel className="panel" collapsible minSize={250}>
      <div className="panelTitleContainer">
        <div className="panelTitle air-title">AI Strategy Research</div>
        <div className="MarketTrackerInteriorContainer air-root">
          <div className="air-status">
            {offline && <span className="air-warn">Starting engine...</span>}
            {notReady && <span className="air-warn">{health.problem}</span>}
            {health && health.ready && (
              <span className="air-muted">
                Ready: {health.model}
                {health.langsmith?.tracing
                  ? ` | LangSmith: ${health.langsmith.project}`
                  : ''}
              </span>
            )}
          </div>

          {health && (
            <ModelSelector
              onModeChanged={resetConversation}
              onStatus={handleModelStatus}
              disabled={busy}
            />
          )}

          <div className="air-files">
            <div className="air-row">
              <span>Data files</span>
              <button type="button" onClick={resetConversation} disabled={busy}>
                New conversation
              </button>
            </div>
            {dataFiles.length === 0 && (
              <div className="air-muted">No .jsonl files in the workspace.</div>
            )}
            {dataFiles.map((f) => (
              <label key={f} className="air-file" htmlFor={`air-file-${f}`}>
                <input
                  id={`air-file-${f}`}
                  type="checkbox"
                  checked={selected.includes(f)}
                  onChange={() => toggle(f)}
                  disabled={busy}
                />
                {f}
              </label>
            ))}
          </div>

          <div className="air-history" ref={historyRef}>
            {messages.length === 0 && (
              <div className="air-muted">
                Ask about the selected recordings, or use the AI buttons in the
                Workspace and &quot;Ask AI to improve&quot; in the Replayer.
                Outputs are research hypotheses and backtests, not profitability
                claims.
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`air-msg air-${m.role}`}>
                {m.role === 'user' && (
                  <>
                    <div className="air-text">{m.text}</div>
                    <div className="air-muted">
                      Files: {m.files.length ? m.files.join(', ') : 'none'}
                    </div>
                  </>
                )}
                {m.role === 'error' && (
                  <div className="air-text">Error: {m.text}</div>
                )}
                {m.role === 'assistant' && (
                  <>
                    {m.tools.length > 0 && (
                      <div className="air-muted">
                        Tools used:{' '}
                        {m.tools
                          .filter((t) => t.tool !== 'structure_answer')
                          .map((t) => t.tool)
                          .join(', ')}
                      </div>
                    )}
                    <div className="air-text">{m.response.message}</div>
                    <ListSection
                      title="Observations (measured)"
                      items={m.response.observations}
                    />
                    <ListSection
                      title="Hypotheses (untested)"
                      items={m.response.hypotheses}
                    />
                    <ListSection
                      title="Backtest results"
                      items={m.response.backtest_results}
                    />
                    <ListSection title="Caveats" items={m.response.caveats} />
                    <ListSection
                      title="Next steps"
                      items={m.response.next_steps}
                    />
                    {(m.artifacts || []).map((a) => (
                      <ArtifactCard
                        key={a.id}
                        artifact={a}
                        onOpen={openArtifact}
                        notify={setNotice}
                      />
                    ))}
                  </>
                )}
              </div>
            ))}
            {busy && (
              <div className="air-activity">
                <div className="air-spinner">Agent working...</div>
                {activity.map((t) => {
                  let icon = '✓';
                  if (t.status === 'running') icon = '⏳';
                  else if (t.status === 'error') icon = '⚠';
                  return (
                    <div key={t.id} className={`air-tool air-tool-${t.status}`}>
                      {icon} {t.label}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {notice && <div className="air-notice">{notice}</div>}

          <div className="air-compose">
            <div className="air-muted">
              Using:{' '}
              {selected.length ? selected.join(', ') : 'no data files selected'}
            </div>
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) send();
              }}
              placeholder="Ask about the selected data or your strategies (Ctrl+Enter to send)"
              rows={3}
              disabled={busy || offline}
            />
            <button
              type="button"
              onClick={send}
              disabled={busy || offline || notReady || !input.trim()}
              title={notReady ? health.problem : undefined}
            >
              {busy ? 'Working...' : 'Send'}
            </button>
          </div>
        </div>
      </div>

      {viewer && (
        <div className="air-modal" role="dialog" aria-label={viewer.filename}>
          <div className="air-modalBody">
            <div className="air-row">
              <b>{viewer.filename}</b>
              <button type="button" onClick={() => setViewer(null)}>
                Close
              </button>
            </div>
            <pre>{viewer.content}</pre>
          </div>
        </div>
      )}
    </Panel>
  );
}
