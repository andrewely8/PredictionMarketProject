import {Panel} from "react-resizable-panels";
import { useState } from "react";
import { useGlobal } from "../contexts/GlobalContext.tsx";
import '../App.css';

function DataFile({fileName}) {
  const Global = useGlobal();

  function onReplayClick() {
    //let newFilePath = Global.workspaceDir + "/" + fileName
    Global.setCurrentReplayFile(fileName);
    console.log(Global.currentReplayFile);
  };

  return (
    <div className="fileListItem">
      <span>{fileName}</span>
      <button style = {{marginLeft: "5px"}} onClick = {onReplayClick}>replay</button>
    </div>
  );
}


function StrategyFile({fileName}) {
  const Global = useGlobal();

  function onTestClick() {
    //let newFilePath = Global.workspaceDir + "/" + fileName
    Global.setCurrentTestFile(fileName);
    console.log(Global.currentTestFile);
  };

  return (
    <div className="fileListItem">
      <span>{fileName}</span>
      <button style = {{marginLeft: "5px"}} onClick = {onTestClick}>test</button>
    </div>
  );
}


export default function Workspace() {
  const [dataFiles, setDataFiles] = useState([]);
  const [strategyFiles, setStrategyFiles] = useState([]);
  const Global = useGlobal();

  async function readDirectory() {
    
    const f = await window.electronAPI.readDirectory(Global.workspaceDir);
    let df = [];
    let sf = [];
    for (let i = 0; i < f.length; i++) {
      let lastFive = f[i].substr(f[i].length - 5);
      console.log(lastFive);
      if (lastFive === "jsonl") {
        df.push(f[i])
      }
      else {
        sf.push(f[i])
      }
    }
    setDataFiles(df);
    setStrategyFiles(sf);
    console.log(f);
  }

  function SetReplayerFile(file_name) {

  }

  return (
    <Panel className = "panel" collapsible minSize={200}>
      <div className = "panelTitleContainer">
        <div className = "panelTitle">Workspace</div>
        <div className = "MarketTrackerInteriorContainer">
          <button onClick = {readDirectory}>Refresh</button>

          <div style = {{flexDirection: "row"}}>
            <span style = {{color: "white"}}>data files:</span>
            {dataFiles.map((item,i) => (
              <DataFile fileName = {item} key={i}/>
            ))}
            <span style = {{display: "flex", color: "white"}}>strategy files:</span>
            {strategyFiles.map((item,i) => (
              <StrategyFile fileName = {item} key={i}/>
            ))}
          </div>
        </div>
      </div>
    </Panel>
  );
}