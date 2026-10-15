/* eslint no-console: off */
/**
 * Starts and stops the Python engine (reactWebsite/electron-react/engine), which serves the
 * collector, the Kalshi simulator, strategy runs and the AI assistant on 127.0.0.1:<port>.
 *
 * Interpreter: KB_PYTHON env var, else engine/.venv, else "python".
 */
import path from 'path';
import fs from 'fs';
import http from 'http';
import { spawn, spawnSync, ChildProcess } from 'child_process';
import config from '../../engine/config.json';

let engine: ChildProcess | null = null;

// __dirname is release/app/dist/main in both `npm start` and `npm run build`.
const APP_DIR = path.join(__dirname, '../../../..');

function pythonExecutable(): string {
  if (process.env.KB_PYTHON) {
    return process.env.KB_PYTHON;
  }
  const venv =
    process.platform === 'win32'
      ? path.join(APP_DIR, 'engine', '.venv', 'Scripts', 'python.exe')
      : path.join(APP_DIR, 'engine', '.venv', 'bin', 'python');
  return fs.existsSync(venv) ? venv : 'python';
}

function engineResponds(): Promise<boolean> {
  return new Promise((resolve) => {
    const req = http.get(
      { host: config.host, port: config.port, path: '/health', timeout: 1000 },
      (res) => {
        res.resume();
        resolve(res.statusCode === 200);
      },
    );
    req.on('error', () => resolve(false));
    req.on('timeout', () => {
      req.destroy();
      resolve(false);
    });
  });
}

export async function startEngine(): Promise<void> {
  if (engine) {
    return;
  }
  if (await engineResponds()) {
    console.log(
      `[engine] already running on ${config.host}:${config.port}; reusing it`,
    );
    return;
  }
  const python = pythonExecutable();
  engine = spawn(
    python,
    [
      '-m',
      'uvicorn',
      'engine.server:app',
      '--host',
      config.host,
      '--port',
      String(config.port),
      '--no-access-log',
    ],
    { cwd: APP_DIR },
  );
  engine.stdout?.on('data', (data) => console.log(`[engine] ${data}`));
  // uvicorn writes its normal startup messages to stderr
  engine.stderr?.on('data', (data) => console.log(`[engine] ${data}`));
  engine.on('error', (err) => {
    console.error(`[engine] failed to start with "${python}": ${err.message}`);
    engine = null;
  });
  engine.on('close', (code) => {
    console.log(`[engine] exited (code ${code})`);
    engine = null;
  });
}

export function stopEngine(): void {
  if (!engine || engine.pid === undefined) {
    return;
  }
  if (process.platform === 'win32') {
    // The venv python.exe launches a child interpreter, which may start Ollama: kill the tree.
    spawnSync('taskkill', ['/pid', String(engine.pid), '/T', '/F']);
  } else {
    engine.kill('SIGTERM');
  }
  engine = null;
}
