/* eslint no-console: off, promise/always-return: off */
/**
 * Electron main process: the window, native dialogs and the Python engine's lifecycle.
 * All trading, replay, collection and AI logic lives in the engine (../../engine).
 */
import path from 'path';
import { app, BrowserWindow, shell, ipcMain, dialog } from 'electron';
import log from 'electron-log';
import { resolveHtmlPath } from './util';
import startAutoUpdates from './updates';
import { startEngine, stopEngine } from './engine';

let mainWindow: BrowserWindow | null = null;

if (process.env.NODE_ENV === 'production') {
  process.setSourceMapsEnabled(true);
}

const isDebug =
  process.env.NODE_ENV === 'development' || process.env.DEBUG_PROD === 'true';

if (isDebug) {
  void import('electron-debug')
    .then(({ default: debug }) => debug())
    .catch(console.error);
}

const installExtensions = async () => {
  const { installExtension, REACT_DEVELOPER_TOOLS } =
    await import('electron-devtools-installer');
  return installExtension(REACT_DEVELOPER_TOOLS, {
    forceDownload: !!process.env.UPGRADE_EXTENSIONS,
  }).catch(console.log);
};

const createWindow = async () => {
  if (isDebug) {
    await installExtensions();
  }

  const RESOURCES_PATH = app.isPackaged
    ? path.join(process.resourcesPath, 'assets')
    : path.join(app.getAppPath(), 'assets');

  mainWindow = new BrowserWindow({
    show: false,
    width: 1500,
    height: 900,
    title: 'Kalshi Backtester',
    icon: path.join(RESOURCES_PATH, 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, '../preload/preload.js'),
    },
  });

  mainWindow.on('ready-to-show', () => {
    if (!mainWindow) {
      throw new Error('"mainWindow" is not defined');
    }
    if (process.env.START_MINIMIZED) {
      mainWindow.minimize();
    } else {
      mainWindow.show();
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  mainWindow.removeMenu();

  // Open links in the user's browser, never inside the app.
  mainWindow.webContents.setWindowOpenHandler((edata) => {
    if (edata.url.startsWith('https://')) {
      void shell.openExternal(edata.url);
    }
    return { action: 'deny' };
  });

  await mainWindow.loadURL(resolveHtmlPath('index.html'));
};

function reportWindowError(error: unknown) {
  log.error('Failed to create the application window', error);
  mainWindow?.destroy();
  mainWindow = null;
}

// --------------------------------------------------------------------------- IPC

ipcMain.handle(
  'dialog:select-directory',
  async (_event, defaultPath?: string) => {
    const result = await dialog.showOpenDialog({
      properties: ['openDirectory', 'createDirectory'],
      defaultPath,
    });
    return result.canceled ? null : result.filePaths[0];
  },
);

ipcMain.handle('shell:open-path', async (_event, target: string) => {
  // Opens a file (e.g. a strategy) in the user's default editor / a folder in the file manager.
  const error = await shell.openPath(target);
  return error || null;
});

ipcMain.handle('shell:show-item', (_event, target: string) => {
  shell.showItemInFolder(target);
});

ipcMain.handle('shell:open-external', async (_event, url: string) => {
  if (typeof url === 'string' && url.startsWith('https://')) {
    await shell.openExternal(url);
  }
});

ipcMain.handle('devtools:open', () => {
  mainWindow?.webContents.openDevTools();
});

// --------------------------------------------------------------------------- lifecycle

app.on('window-all-closed', () => {
  // Respect the OSX convention of keeping the application in memory after windows close.
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  stopEngine();
});

function onActivate() {
  // Reopening a macOS window must not initialize another updater.
  if (mainWindow === null) {
    void createWindow().catch(reportWindowError);
  }
}

app
  .whenReady()
  .then(async () => {
    void startEngine();
    await createWindow();
    startAutoUpdates();
    app.on('activate', onActivate);
  })
  .catch((error: unknown) => {
    reportWindowError(error);
    app.quit();
  });
