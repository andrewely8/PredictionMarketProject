// Disable no-unused-vars, broken for spread args
/* eslint no-unused-vars: off */
import { contextBridge, ipcRenderer, IpcRendererEvent } from 'electron';

export type Channels = 'ipc-example';

const electronHandler = {
  ipcRenderer: {
    sendMessage(channel: Channels, ...args: unknown[]) {
      ipcRenderer.send(channel, ...args);
    },
    on(channel: Channels, func: (...args: unknown[]) => void) {
      const subscription = (_event: IpcRendererEvent, ...args: unknown[]) =>
        func(...args);
      ipcRenderer.on(channel, subscription);

      return () => {
        ipcRenderer.removeListener(channel, subscription);
      };
    },
    once(channel: Channels, func: (...args: unknown[]) => void) {
      ipcRenderer.once(channel, (_event, ...args) => func(...args));
    },
  },
};

contextBridge.exposeInMainWorld('electron', electronHandler);
contextBridge.exposeInMainWorld("electronAPI", {
  selectDirectory: () => ipcRenderer.invoke("select-directory"),
  openDevtools: () => ipcRenderer.invoke("open-devtools"),
  readDirectory: (dir_path) => ipcRenderer.invoke("read-directory", dir_path),
  readFile: (file_path) => ipcRenderer.invoke("read-json-file", file_path),
  processTick: (tick) => ipcRenderer.invoke("process-tick", tick),
  sendToPython: (msg) => ipcRenderer.send("python-message", msg),

  
});
export type ElectronHandler = typeof electronHandler;
