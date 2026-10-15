/**
 * "AI model" selector for the AI Strategy Research panel.
 *
 *   1. Claude account - Sign in with Claude (Anthropic's browser OAuth via the Anthropic CLI).
 *   2. Local Qwen     - packaged Ollama + Qwen model stored inside the project folder (engine/runtime).
 *
 * All credential handling happens in the Python service; this component only shows status and
 * triggers actions.
 */
import { useCallback, useEffect, useState } from 'react';
import { getJSON, postJSON } from '../../api/engine';

function formatBytes(n) {
  if (!n) return '';
  return n > 1e9 ? `${(n / 1e9).toFixed(2)} GB` : `${(n / 1e6).toFixed(0)} MB`;
}

function ProgressLine({ setup }) {
  if (!setup || setup.state === 'idle') return null;
  return (
    <div className={setup.state === 'error' ? 'air-warn' : 'air-muted'}>
      {setup.message}
      {setup.percent !== null && setup.percent !== undefined && (
        <>
          {' '}
          - {setup.percent}% ({formatBytes(setup.done_bytes)} of{' '}
          {formatBytes(setup.total_bytes)})
          <div className="air-progress">
            <div style={{ width: `${setup.percent}%` }} />
          </div>
        </>
      )}
    </div>
  );
}

export default function ModelSelector({ onModeChanged, onStatus, disabled }) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    try {
      const s = await getJSON('/ai/llm/status');
      setStatus(s);
      onStatus(s);
    } catch {
      setStatus(null);
    }
  }, [onStatus]);

  // Poll quickly while something is in progress, slowly otherwise.
  const busy =
    status &&
    (status.claude.login_in_progress ||
      [
        'downloading',
        'verifying',
        'extracting',
        'pulling',
        'starting',
      ].includes(status.local.setup.state) ||
      (status.mode === 'local' &&
        status.local.runtime_installed &&
        !status.local.running));
  useEffect(() => {
    const first = setTimeout(refresh, 0);
    const timer = setInterval(refresh, busy ? 2000 : 15000);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [refresh, busy]);

  async function act(path, options) {
    setError('');
    try {
      return await postJSON(path, options?.body ?? {});
    } catch (e) {
      setError(e.message);
      return null;
    } finally {
      refresh();
    }
  }

  async function chooseMode(mode) {
    if (!status || mode === status.mode) return;
    const out = await act('/ai/llm/mode', { body: { mode } });
    if (out) onModeChanged(mode);
  }

  if (!status) return null;
  const { claude, local } = status;

  return (
    <div className="air-model">
      <div className="air-row">
        <span className="air-sectionTitle">AI model</span>
        <label className="air-file">
          <input
            type="radio"
            name="air-mode"
            checked={status.mode === 'claude'}
            onChange={() => chooseMode('claude')}
            disabled={disabled}
          />
          Claude account
        </label>
        <label className="air-file">
          <input
            type="radio"
            name="air-mode"
            checked={status.mode === 'local'}
            onChange={() => chooseMode('local')}
            disabled={disabled}
          />
          Local Qwen (this computer)
        </label>
      </div>

      {status.mode === 'claude' && (
        <div className="air-modelBody">
          {claude.signed_in ? (
            <div className="air-row">
              <span className="air-ok">
                {claude.source === 'claude_account'
                  ? 'Signed in with your Claude account'
                  : 'Using an API key from the environment'}{' '}
                ({claude.model})
              </span>
              {claude.source === 'claude_account' && (
                <button type="button" onClick={() => act('/ai/auth/logout')}>
                  Sign out
                </button>
              )}
            </div>
          ) : (
            <div className="air-row">
              <button
                type="button"
                onClick={() => act('/ai/auth/login')}
                disabled={claude.login_in_progress}
              >
                {claude.login_in_progress
                  ? 'Waiting for browser...'
                  : 'Sign in with Claude'}
              </button>
              <span className="air-muted">{claude.detail}</span>
            </div>
          )}
          <ProgressLine setup={claude.install} />
          <div className="air-muted">
            Uses your Claude Console (API) account; usage is billed to the
            organization you pick when signing in. Claude.ai Pro/Max chat
            subscriptions can&apos;t be used here.
          </div>
        </div>
      )}

      {status.mode === 'local' && (
        <div className="air-modelBody">
          {local.ready ? (
            <span className="air-ok">
              Ready: {local.model} running privately on this computer
            </span>
          ) : (
            <div className="air-row">
              {!(local.runtime_installed && local.model_present) && (
                <button
                  type="button"
                  onClick={() => act('/ai/local/setup')}
                  disabled={[
                    'downloading',
                    'verifying',
                    'extracting',
                    'pulling',
                    'starting',
                  ].includes(local.setup.state)}
                >
                  Install local model
                </button>
              )}
              <span className="air-muted">{local.problem}</span>
            </div>
          )}
          <ProgressLine
            setup={local.setup.state === 'done' ? null : local.setup}
          />
          <div className="air-muted">
            Ollama + {local.model}, stored inside the project folder
            (engine/runtime) (about 5 GB on first install). Nothing leaves your
            machine; answers are slower than Claude.
          </div>
        </div>
      )}
      {error && <div className="air-warn">{error}</div>}
    </div>
  );
}
