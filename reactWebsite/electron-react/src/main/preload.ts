/**
 * The only bridge between the renderer and Electron: native dialogs and shell helpers.
 * Everything else (data, simulator, strategies, AI) goes to the engine over localhost HTTP.
 */
import { contextBridge, ipcRenderer } from 'electron';

const electronAPI = {
  selectDirectory: (defaultPath?: string): Promise<string | null> =>
    ipcRenderer.invoke('dialog:select-directory', defaultPath),
  openPath: (target: string): Promise<string | null> =>
    ipcRenderer.invoke('shell:open-path', target),
  showItemInFolder: (target: string): Promise<void> =>
    ipcRenderer.invoke('shell:show-item', target),
  openExternal: (url: string): Promise<void> =>
    ipcRenderer.invoke('shell:open-external', url),
  openDevtools: (): Promise<void> => ipcRenderer.invoke('devtools:open'),
};

contextBridge.exposeInMainWorld('electronAPI', electronAPI);

export type ElectronAPI = typeof electronAPI;
