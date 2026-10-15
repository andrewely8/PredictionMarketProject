import { useState } from 'react';
import { useGlobal } from '../contexts/GlobalContext';
import SettingsDialog from './SettingsDialog';
import Modal from './Modal';

function MenuButton({ label, options }) {
  return (
    <div className="dropdown">
      <button type="button">{label}</button>
      <div className="dropdown-content">
        {options.map((opt) => (
          <button
            type="button"
            key={opt.label}
            className="menuItem"
            disabled={opt.disabled}
            onClick={opt.onClick}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function GettingStarted({ onClose }) {
  return (
    <Modal title="Getting started" onClose={onClose}>
      <ol style={{ margin: 0, paddingLeft: 20, lineHeight: 1.6 }}>
        <li>
          <b>File → Settings</b>: point the app at the folder with your Kalshi
          API keys (keys.json + key files). Only the Market Tracker uses them.
        </li>
        <li>
          <b>Market Tracker</b>: search an event or series ticker (e.g.
          KXMLBGAME), tick markets, press TRACK. Each recording is a .jsonl file
          in your workspace.
        </li>
        <li>
          <b>Workspace</b>: <i>New strategy</i> from a template, then{' '}
          <i>edit</i> it. Strategies are written exactly like live Kalshi bots
          (websocket + REST).
        </li>
        <li>
          <b>Replayer</b>: pick a recording (<i>replay</i>) and a strategy (
          <i>test</i>), then
          <i> Run Strategy TEST</i>. The simulator replays the order book on the
          Replayer clock and fills your orders; P&amp;L, fills and the strategy
          console update live. Every run saves a report.
        </li>
        <li>
          <b>AI Strategy Research</b>: <i>Ask AI to improve</i> sends the
          strategy and its report to the assistant. It writes an improved
          version and backtests it; <i>Add to Workspace</i>, then retest it in
          the Replayer.
        </li>
      </ol>
    </Modal>
  );
}

export default function CustomMenu() {
  const { settings, updateSettings, refreshWorkspace, workspace } = useGlobal();
  const [dialog, setDialog] = useState(null);

  async function chooseWorkspace() {
    const dir = await window.electronAPI.selectDirectory(
      settings?.workspace_dir,
    );
    if (dir) await updateSettings({ workspace_dir: dir });
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'row' }}>
      <MenuButton
        label="File"
        options={[
          {
            label: 'Choose workspace folder...',
            onClick: chooseWorkspace,
            disabled: !settings,
          },
          {
            label: 'Open workspace folder',
            onClick: () =>
              workspace && window.electronAPI.openPath(workspace.dir),
            disabled: !workspace,
          },
          {
            label: 'Settings...',
            onClick: () => setDialog('settings'),
            disabled: !settings,
          },
        ]}
      />
      <MenuButton
        label="View"
        options={[
          { label: 'Refresh workspace', onClick: refreshWorkspace },
          { label: 'Reload window', onClick: () => window.location.reload() },
        ]}
      />
      <MenuButton
        label="Help"
        options={[
          { label: 'Getting started', onClick: () => setDialog('help') },
          {
            label: 'Kalshi API documentation',
            onClick: () =>
              window.electronAPI.openExternal('https://docs.kalshi.com'),
          },
          {
            label: 'Open devtools',
            onClick: () => window.electronAPI.openDevtools(),
          },
        ]}
      />
      {dialog === 'settings' && (
        <SettingsDialog onClose={() => setDialog(null)} />
      )}
      {dialog === 'help' && <GettingStarted onClose={() => setDialog(null)} />}
    </div>
  );
}
