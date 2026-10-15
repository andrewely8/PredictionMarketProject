import { createContext, useContext, useState } from 'react';

const GlobalContext = createContext(null);

export function GlobalProvider({ children }) {
  const [workspaceDir, setWorkspaceDir] = useState("C:/Users/andre/Desktop/PredictionMarketProject/reactWebsite/electron-react/backendPython/workspace");
  const [currentReplayFile, setCurrentReplayFile] = useState(null);
  const [currentTestFile, setCurrentTestFile] = useState(null);
  
  return (
    <GlobalContext.Provider
      value={{
        workspaceDir,
        setWorkspaceDir,
        currentReplayFile, 
        setCurrentReplayFile,
        currentTestFile, 
        setCurrentTestFile
      }}
    >
      {children}
    </GlobalContext.Provider>
  );
}

export function useGlobal() {
  return useContext(GlobalContext);
}
