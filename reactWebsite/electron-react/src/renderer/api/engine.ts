/**
 * Small client for the local Python engine (see engine/config.json for host and port).
 * All errors are thrown as Error with the engine's `detail` message when it has one.
 */
import config from '../../../engine/config.json';

export const ENGINE_URL = `http://${config.host}:${config.port}`;
export const ENGINE_WS = `ws://${config.host}:${config.port}`;

async function errorDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    const detail = body.detail ?? body.error?.message;
    return typeof detail === 'string' ? detail : JSON.stringify(detail);
  } catch {
    return `${res.status} ${res.statusText}`;
  }
}

export async function request(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  const res = await fetch(`${ENGINE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    throw new Error(await errorDetail(res));
  }
  return res;
}

export async function getJSON<T = any>(path: string): Promise<T> {
  return (await request(path)).json();
}

export async function postJSON<T = any>(
  path: string,
  body: unknown = {},
): Promise<T> {
  return (
    await request(path, { method: 'POST', body: JSON.stringify(body) })
  ).json();
}

export async function putJSON<T = any>(
  path: string,
  body: unknown = {},
): Promise<T> {
  return (
    await request(path, { method: 'PUT', body: JSON.stringify(body) })
  ).json();
}

export async function deleteJSON<T = any>(path: string): Promise<T> {
  return (await request(path, { method: 'DELETE' })).json();
}

export function formatDollars(
  value: number | null | undefined,
  digits = 2,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '-';
  const sign = value < 0 ? '-' : '';
  return `${sign}$${Math.abs(value).toFixed(digits)}`;
}

export function formatClock(tsMs: number | null | undefined): string {
  if (!tsMs) return '--:--:--';
  return new Date(tsMs).toLocaleTimeString([], { hour12: false });
}

export function formatDuration(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export function formatBytes(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)} GB`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)} KB`;
  return `${n} B`;
}
