import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { getJSON, putJSON } from '../api/engine';

export type FileItem = { name: string; size_bytes: number; modified: number };
export type ReportItem = {
  report_file: string;
  run_id: string;
  strategy: string;
  data_file: string;
  status: string;
  started: string;
  pnl: number | null;
  fees: number | null;
  fills: number | null;
  max_drawdown: number | null;
  coverage: number | null;
};
export type WorkspaceListing = {
  dir: string;
  data_files: FileItem[];
  strategy_files: FileItem[];
  reports: ReportItem[];
};
export type AIRequest = { id: number; message: string; dataFiles: string[] };

type GlobalValue = {
  engineOnline: boolean;
  settings: Record<string, any> | null;
  updateSettings: (changes: Record<string, unknown>) => Promise<void>;
  workspace: WorkspaceListing | null;
  workspaceError: string | null;
  refreshWorkspace: () => Promise<void>;
  currentReplayFile: string | null;
  setCurrentReplayFile: (name: string | null) => void;
  currentTestFile: string | null;
  setCurrentTestFile: (name: string | null) => void;
  aiRequest: AIRequest | null;
  askAI: (message: string, dataFiles?: string[]) => void;
};

const GlobalContext = createContext<GlobalValue | null>(null);

export function GlobalProvider({ children }: { children: ReactNode }) {
  const [engineOnline, setEngineOnline] = useState(false);
  const [settings, setSettings] = useState<Record<string, any> | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceListing | null>(null);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [currentReplayFile, setCurrentReplayFile] = useState<string | null>(
    null,
  );
  const [currentTestFile, setCurrentTestFile] = useState<string | null>(null);
  const [aiRequest, setAIRequest] = useState<AIRequest | null>(null);

  const refreshWorkspace = useCallback(async () => {
    try {
      setWorkspace(await getJSON<WorkspaceListing>('/workspace'));
      setWorkspaceError(null);
    } catch (e) {
      setWorkspaceError((e as Error).message);
    }
  }, []);

  const loadSettings = useCallback(async () => {
    setSettings(await getJSON('/settings'));
  }, []);

  // Wait for the engine (Electron starts it alongside the window), then load everything.
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      let online = false;
      try {
        await getJSON('/health');
        online = true;
      } catch {
        online = false;
      }
      if (cancelled) return;
      setEngineOnline((was) => {
        if (online && !was) {
          void loadSettings();
          void refreshWorkspace();
        }
        return online;
      });
      timer = setTimeout(poll, online ? 10000 : 1500);
    }
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [loadSettings, refreshWorkspace]);

  const updateSettings = useCallback(
    async (changes: Record<string, unknown>) => {
      setSettings(await putJSON('/settings', { changes }));
      if ('workspace_dir' in changes) {
        setCurrentReplayFile(null);
        setCurrentTestFile(null);
        await refreshWorkspace();
      }
    },
    [refreshWorkspace],
  );

  const askAI = useCallback((message: string, dataFiles: string[] = []) => {
    setAIRequest({ id: Date.now(), message, dataFiles });
  }, []);

  const value = useMemo(
    () => ({
      engineOnline,
      settings,
      updateSettings,
      workspace,
      workspaceError,
      refreshWorkspace,
      currentReplayFile,
      setCurrentReplayFile,
      currentTestFile,
      setCurrentTestFile,
      aiRequest,
      askAI,
    }),
    [
      engineOnline,
      settings,
      updateSettings,
      workspace,
      workspaceError,
      refreshWorkspace,
      currentReplayFile,
      currentTestFile,
      aiRequest,
      askAI,
    ],
  );

  return (
    <GlobalContext.Provider value={value}>{children}</GlobalContext.Provider>
  );
}

export function useGlobal(): GlobalValue {
  const value = useContext(GlobalContext);
  if (!value) {
    throw new Error('useGlobal must be used inside <GlobalProvider>');
  }
  return value;
}
