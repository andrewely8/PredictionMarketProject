import {Panel} from "react-resizable-panels";
import { useState } from "react";
import '../App.css';



export default function Workspace() {
  const [files, setFiles] = useState([]);

  async function readDirectory() {
    const dir_path = "C:/Users/andre/Desktop/PredictionMarketProject/reactWebsite/electron-react/backendPython/collectedData";
    const f = await window.electronAPI.readDirectory(dir_path);
    setFiles(f);
    console.log(f);
  }

  return (
    <Panel className = "panel" collapsible minSize={200}>
      <div className = "panelTitleContainer">
        <div className = "panelTitle">Workspace</div>
        <div className = "MarketTrackerInteriorContainer">
          <span style = {{color: "white"}}>Hello </span>
          <button onClick = {readDirectory}>Test</button>
          <div style = {{flexDirection: "row"}}>
            {files.map((item,i) => (
              <span key={i} style = {{display: "flex", color: "white"}}>{item}</span>
            ))}
          </div>
        </div>
      </div>
    </Panel>
  );
}