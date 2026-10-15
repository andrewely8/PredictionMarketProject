# Kalshi Backtester — desktop app

The Electron + React app and its Python engine. See the [repository README](../../README.md) for
what the app does and the full pipeline, and [engine/README.md](engine/README.md) for the engine,
the Kalshi-compatible simulator and the AI assistant.

## Development

```bash
npm install                                   # Node 24+
python -m venv engine/.venv
engine/.venv/Scripts/python -m pip install -r engine/requirements.txt
npm start                                     # app + engine (engine logs are prefixed [engine])
```

| Command | What it does |
|---|---|
| `npm start` | Dev mode with hot reload. Electron starts the engine from `engine/.venv` (override with `KB_PYTHON`) |
| `npm run build` | Production build into `release/app/dist` |
| `npm test` | Jest UI tests |
| `npm run lint` | ESLint + Prettier |
| `npx tsc --noEmit` | Type check |
| `engine/.venv/Scripts/python -m pytest engine/tests -c engine/tests/pytest.ini` | Engine tests |

## Layout

```text
src/main/        main.ts (window, IPC for dialogs/shell), engine.ts (engine process), preload.ts
src/renderer/    App.tsx, components/ (MarketTracker, Workspace, Replayer, ai/), api/engine.ts,
                 contexts/GlobalContext.tsx
engine/          Python engine (FastAPI on 127.0.0.1:8000)
settings.local.json   your settings (git-ignored), managed through File → Settings
```

The app was started from electron-react-boilerplate; its build tooling (`.erb/`, electron-vite,
electron-builder) is unchanged.
