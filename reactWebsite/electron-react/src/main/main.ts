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
import {Backtester, topBook} from './backtest';

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
let currentTopBooks: Map<string, topBook>;

ipcMain.handle("read-json-file", async (_, newFilePath) => {
  dataArray = []; // Reset dataArray to empty before pushing onto it.
  if (newFilePath.substr(newFilePath.length-4) === "null") {
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

  currentTopBooks = initialBooks;
  return initialBooks;
});


function topBooksEqual(a: topBook, b: topBook): boolean {
  return (
    a.best_yes_bid_dollars === b.best_yes_bid_dollars &&
    a.best_yes_bid_volume === b.best_yes_bid_volume &&
    a.best_yes_ask_dollars === b.best_yes_ask_dollars &&
    a.best_yes_ask_volume === b.best_yes_ask_volume &&
    a.best_no_bid_dollars === b.best_no_bid_dollars &&
    a.best_no_bid_volume === b.best_no_bid_volume &&
    a.best_no_ask_dollars === b.best_no_ask_dollars &&
    a.best_no_ask_volume === b.best_no_ask_volume
  );
}

function topBookMapsEqual(a: Map<string, topBook>,b: Map<string, topBook>): boolean {
  if (a.size !== b.size) {
    return false;
  }

  for (const [ticker, bookA] of a) {
    const bookB = b.get(ticker);

    if (!bookB) {
      return false;
    }

    if (!topBooksEqual(bookA, bookB)) {
      return false;
    }
  }

  return true;
}

ipcMain.handle("process-tick", async (_, tick) => {
  if (!backtest) {
    return null;
  }

  backtest.processTick(tick);
  const newTopBooks = backtest.getTopOrderbooks();

  if (!topBookMapsEqual(newTopBooks,currentTopBooks)) {
    currentTopBooks = newTopBooks;
    return newTopBooks;
  } else{
    return null;
  }


});



let pythonProcessStrategy: ReturnType<typeof spawn> | null = null;

function startPythonStrategy(filePath) {
  if (pythonProcessStrategy) {
    return;
  }

  pythonProcessStrategy = spawn("python", [filePath]);

  pythonProcessStrategy.stdout.on("data", (data) => {console.log(`Python: ${data}`)});
  pythonProcessStrategy.stderr.on("data", (data) => {console.error("PYTHON ERROR:", data.toString());});
  pythonProcessStrategy.on("close", () => {pythonProcessStrategy = null;});

}


let pythonProcessFastAPI: ReturnType<typeof spawn> | null = null;

function startPythonFastAPI() {
  if (pythonProcessFastAPI) {
    return;
  }

  const dirPath = path.join(__dirname, "../../../../backendPython/kalshiApiSim");

  pythonProcessFastAPI = spawn("python",["-m","uvicorn","main:app","--host", "127.0.0.1","--port","8000"],{cwd: dirPath});

  console.log("NOTE: uvicorn writes succesful messages to stderr.")
  pythonProcessFastAPI.stdout.on("data", (data) => {console.log(`Python: ${data}`)});
  pythonProcessFastAPI.stderr.on("data", (data) => {console.error("PYTHON ERROR:", data.toString());});
  pythonProcessFastAPI.on("close", () => {pythonProcessFastAPI = null;});

}


let pythonProcessCollectData: ReturnType<typeof spawn> | null = null;

function startPythonCollectData() {

  if (pythonProcessCollectData) {
    return;
  }

  const pythonPath = "python";
  const scriptPath = path.join(__dirname, "../../../../backendPython/collectMarketData.py");

  pythonProcessCollectData = spawn(pythonPath,[scriptPath]);

  pythonProcessCollectData.stdout.on("data", (data) => {console.log(`Python: ${data}`)});
  pythonProcessCollectData.stderr.on("data", (data) => {console.error("PYTHON ERROR:", data.toString());});
  pythonProcessCollectData.on("close", () => {pythonProcessCollectData = null;});
}



app.on("before-quit", () => {
  pythonProcessCollectData?.kill();
  pythonProcessFastAPI?.kill();
  pythonProcessStrategy?.kill();
});



ipcMain.on("run-python-strategy", async (_, filepath) => {
  if (pythonProcessStrategy) {
    pythonProcessStrategy.kill();
    return;
  }

  startPythonStrategy(filepath);

});




ipcMain.on("python-message", (_, message) => {
  if (!pythonProcessCollectData) {
    console.log("No python process to send to");
    return;
  }
  pythonProcessCollectData.stdin.write(
    JSON.stringify(message) + "\n"
  );
});


ipcMain.handle("open-devtools", async () => {
  mainWindow.webContents.openDevTools()
});

ipcMain.on("open-browser", (_,link) => {
  shell.openExternal(link);
})



app
  .whenReady()
  .then(async () => {
    startPythonCollectData();
    startPythonFastAPI();
    await createWindow();
    startAutoUpdates();
    app.on('activate', onActivate);
  })
  .catch((error: unknown) => {
    reportWindowError(error);

    app.quit();
  });
