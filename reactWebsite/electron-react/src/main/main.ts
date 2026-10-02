/* eslint global-require: off, no-console: off, promise/always-return: off */

/**
 * This module executes inside of electron's main process. You can start
 * electron renderer process from here and communicate with the other processes
 * through IPC.
 *
 * When running `npm run build`, this file is compiled to
 * `./release/app/dist/main/main.js` using electron-vite.
 */
import path from 'path';
import fs from 'fs';
import readline from 'readline';
import { spawn } from "child_process";
import { app, BrowserWindow, shell, ipcMain, dialog } from 'electron';
import log from 'electron-log';
import MenuBuilder from './menu'; 
import { resolveHtmlPath } from './util';
import startAutoUpdates from './updates';
import Backtester from './backtest';

let mainWindow: BrowserWindow | null = null;

ipcMain.on('ipc-example', async (event, arg) => {
  const msgTemplate = (pingPong: string) => `IPC test: ${pingPong}`;
  console.log(msgTemplate(arg));
  event.reply('ipc-example', msgTemplate('pong'));
});

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

  const getAssetPath = (...paths: string[]): string => {
    return path.join(RESOURCES_PATH, ...paths);
  };

  mainWindow = new BrowserWindow({
    show: false,
    width: 1024,
    height: 728,
    icon: getAssetPath('icon.png'),
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
  // const menuBuilder = new MenuBuilder(mainWindow);
  // menuBuilder.buildMenu();

  // Open urls in the user's browser
  mainWindow.webContents.setWindowOpenHandler((edata) => {
    shell.openExternal(edata.url);
    return { action: 'deny' };
  });

  await mainWindow.loadURL(resolveHtmlPath('index.html'));
};

/**
 * Add event listeners...
 */

app.on('window-all-closed', () => {
  // Respect the OSX convention of having the application in memory even
  // after all windows have been closed
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

function reportWindowError(error: unknown) {
  log.error('Failed to create the application window', error);
  mainWindow?.destroy();
  mainWindow = null;
}

function onActivate() {
  // Reopening a macOS window must not initialize another updater.
  if (mainWindow === null) {
    void createWindow().catch(reportWindowError);
  }
}



ipcMain.handle("select-directory", async () => {
  const result = await dialog.showOpenDialog({
    properties: ["openDirectory"],
  });

  if (result.canceled) {
    return null;
  }

  return result.filePaths[0];
});



ipcMain.handle("read-directory", async (_, dirPath) => {
  const files = await fs.promises.readdir(dirPath);
  console.log(files);
  return files;
});




let filePath = '';
let dataArray = [];
let backtest: Backtester;

ipcMain.handle("read-json-file", async (_, newFilePath) => {
  dataArray = []; // Reset dataArray to empty before pushing onto it.
  if (newFilePath.substr(newFilePath.length-4) === "null") {
    console.log("no file path to load");
    return null;
  }
  
  filePath = newFilePath;
  
  const rl = readline.createInterface({
    input: fs.createReadStream(newFilePath),
    crlfDelay: Infinity
  });

  rl.on('line', (line) => {
    if (line.trim() !== '') {
      dataArray.push(JSON.parse(line));
    }
  });

  const initialBooks = await new Promise((resolve, reject) => {
    rl.on('close', async () => {
      try {
        backtest = new Backtester(dataArray);
        const books = backtest.getTopOrderbooks();
        resolve(books);
      } catch (error) {
        reject(error);
      }
    });
  });

  return initialBooks;
});



ipcMain.handle("process-tick", async (_, tick) => {
  // console.log(file);
  // return "successful process-tick function call";



});




let pythonProcess: ReturnType<typeof spawn> | null = null;

function startPython() {

  if (pythonProcess) {
    return;
  }

  const pythonPath = "python";
  const scriptPath = path.join(__dirname, "../../../../backendPython/collectMarketData.py");

  pythonProcess = spawn(pythonPath,[scriptPath]);

  pythonProcess.stdout.on("data", (data) => {console.log(`Python: ${data}`)});
  pythonProcess.stderr.on("data", (data) => {console.error("PYTHON ERROR:", data.toString());});
  pythonProcess.on("close", () => {pythonProcess = null;});
}



app.on("before-quit", () => {
  pythonProcess?.kill();
});


ipcMain.on("python-message", (_, message) => {
  if (!pythonProcess) {
    console.log("No python process to send to");
    return;
  }
  pythonProcess.stdin.write(
    JSON.stringify(message) + "\n"
  );
});


ipcMain.handle("open-devtools", async () => {
  mainWindow.webContents.openDevTools()
});




app
  .whenReady()
  .then(async () => {
    startPython();
    await createWindow();
    startAutoUpdates();
    app.on('activate', onActivate);
  })
  .catch((error: unknown) => {
    reportWindowError(error);

    app.quit();
  });
