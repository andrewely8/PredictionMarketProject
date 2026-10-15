import '@testing-library/jest-dom';
import { render, screen, waitFor } from '@testing-library/react';
import App from '../renderer/App';

const WORKSPACE = {
  dir: 'C:/ws',
  data_files: [{ name: 'game.jsonl', size_bytes: 2048, modified: 0 }],
  strategy_files: [{ name: 'my_strategy.py', size_bytes: 100, modified: 0 }],
  reports: [],
};

function respond(url: string): unknown {
  if (url.endsWith('/health')) return { status: 'ok' };
  if (url.endsWith('/settings'))
    return {
      workspace_dir: 'C:/ws',
      kalshi_env: 'production',
      credentials: { production: { ok: true } },
    };
  if (url.endsWith('/workspace')) return WORKSPACE;
  if (url.endsWith('/workspace/templates'))
    return [{ template: 'starter', summary: 'Starter' }];
  if (url.endsWith('/collector/jobs')) return [];
  if (url.endsWith('/ai/health'))
    return {
      status: 'ok',
      ready: false,
      problem: 'Not signed in',
      mode: 'claude',
      model: 'claude-opus-5-5',
    };
  if (url.endsWith('/ai/llm/status'))
    return {
      mode: 'claude',
      ready: false,
      problem: 'Not signed in',
      claude: {
        signed_in: false,
        detail: 'Not signed in',
        install: { state: 'idle' },
        model: 'claude-opus-5-5',
      },
      local: { ready: false, setup: { state: 'idle' }, model: 'qwen3.5:4b' },
    };
  return {};
}

beforeEach(() => {
  // jsdom gaps used by the panels: ResizeObserver (react-resizable-panels) and element scrolling.
  (global as any).ResizeObserver = class {
    observe() {}

    unobserve() {}

    disconnect() {}
  };
  Element.prototype.scrollTo = jest.fn();
  global.fetch = jest.fn((url: string) =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(respond(url)) }),
  ) as unknown as typeof fetch;
  (global as any).WebSocket = jest.fn(() => ({ close: jest.fn() }));
  (window as any).electronAPI = {
    selectDirectory: jest.fn(),
    openPath: jest.fn(),
    showItemInFolder: jest.fn(),
    openExternal: jest.fn(),
    openDevtools: jest.fn(),
  };
});

describe('App', () => {
  it('renders the four panels and loads the workspace from the engine', async () => {
    render(<App />);
    for (const title of [
      'Market Tracker',
      'Workspace',
      'AI Strategy Research',
      'Replayer',
    ]) {
      expect(screen.getByText(title)).toBeInTheDocument();
    }
    await waitFor(() =>
      expect(screen.getAllByText('game.jsonl').length).toBeGreaterThan(0),
    );
    expect(screen.getByText('my_strategy.py')).toBeInTheDocument();
    expect(screen.getByText('Run Strategy TEST')).toBeDisabled();
  });
});
