import { useState } from 'react';
import { useGlobal } from '../contexts/GlobalContext';
import Modal from './Modal';

function CredentialLine({ env, status }) {
  if (!status) return null;
  return (
    <div className={status.ok ? 'ok' : 'warn'}>
      {env}: {status.ok ? 'keys found' : status.problem}
    </div>
  );
}

export default function SettingsDialog({ onClose }) {
  const { settings, updateSettings } = useGlobal();
  const [form, setForm] = useState(() => ({
    secret_dir: settings?.secret_dir ?? '',
    kalshi_env: settings?.kalshi_env ?? 'production',
    sim_starting_balance: settings?.sim_starting_balance ?? 1000,
    sim_taker_fee_rate: settings?.sim_taker_fee_rate ?? 0.07,
    sim_maker_fee_rate: settings?.sim_maker_fee_rate ?? 0,
  }));
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);

  if (!settings) return null;
  const set = (key) => (e) => {
    setSaved(false);
    setForm({ ...form, [key]: e.target.value });
  };

  async function chooseSecretDir() {
    const dir = await window.electronAPI.selectDirectory(form.secret_dir);
    if (dir) setForm({ ...form, secret_dir: dir });
  }

  async function save() {
    setError('');
    try {
      await updateSettings({
        ...form,
        sim_starting_balance: Number(form.sim_starting_balance),
        sim_taker_fee_rate: Number(form.sim_taker_fee_rate),
        sim_maker_fee_rate: Number(form.sim_maker_fee_rate),
      });
      setSaved(true);
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <Modal title="Settings" onClose={onClose}>
      <div className="sectionTitle">
        Kalshi API keys (used only for recording market data)
      </div>
      <div className="muted">
        A folder containing keys.json plus kalshiProductionKey.txt and/or
        kalshiDemoKey.txt. Keys never leave your computer; they are not sent to
        strategies or the AI.
      </div>
      <div className="row">
        <input
          className="textInput"
          style={{ flex: 1 }}
          value={form.secret_dir}
          onChange={set('secret_dir')}
        />
        <button type="button" onClick={chooseSecretDir}>
          Choose...
        </button>
      </div>
      <CredentialLine
        env="production"
        status={settings.credentials?.production}
      />
      <CredentialLine env="demo" status={settings.credentials?.demo} />
      <label className="row" htmlFor="kalshi-env">
        Record from
        <select
          id="kalshi-env"
          value={form.kalshi_env}
          onChange={set('kalshi_env')}
        >
          <option value="production">production (real markets)</option>
          <option value="demo">demo</option>
        </select>
      </label>

      <div className="sectionTitle">Simulator account</div>
      <label className="row" htmlFor="sim-balance">
        Starting balance ($)
        <input
          id="sim-balance"
          className="textInput"
          type="number"
          min="0"
          value={form.sim_starting_balance}
          onChange={set('sim_starting_balance')}
        />
      </label>
      <label className="row" htmlFor="sim-taker">
        Taker fee rate
        <input
          id="sim-taker"
          className="textInput"
          type="number"
          min="0"
          step="0.0025"
          value={form.sim_taker_fee_rate}
          onChange={set('sim_taker_fee_rate')}
        />
        <span className="muted">
          Kalshi: fee = ceil(rate x contracts x P x (1 - P)) per fill; 0.07 by
          default
        </span>
      </label>
      <label className="row" htmlFor="sim-maker">
        Maker fee rate
        <input
          id="sim-maker"
          className="textInput"
          type="number"
          min="0"
          step="0.0025"
          value={form.sim_maker_fee_rate}
          onChange={set('sim_maker_fee_rate')}
        />
      </label>

      <div className="row">
        <button type="button" onClick={save}>
          Save
        </button>
        {saved && <span className="ok">Saved</span>}
        {error && <span className="bad">{error}</span>}
      </div>
    </Modal>
  );
}
