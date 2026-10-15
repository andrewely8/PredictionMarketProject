import {Panel} from "react-resizable-panels";
import { useState } from "react";
import '../App.css';



function EventTrackForm() {

  const [input, setInput] = useState("");
  const [disabled, setDisabled] = useState(false);
  const [processInfo, setProcessInfo] = useState(null);
  const [saveDirPath, setSaveDirPath] = useState("./backendPython/workspace");
  const [scheduleDisabled, setScheduleDisabled] = useState(false);

  function handleSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const formData = new FormData(form);
    const formJson = {
      ...Object.fromEntries(formData.entries()),
      save_dir: saveDirPath
    };
    console.log(formJson);
    setDisabled(true);
    setProcessInfo("validating...")

    sendJson(formJson);

  }

  function handleKeyDown(e) {
    // if (e.key === "Enter" && !e.shiftKey ) {
    //   e.preventDefault();
    //   e.currentTarget.form.requestSubmit();
    // }
  }


  async function chooseDirectory() {
    const directory = await window.electronAPI.selectDirectory();
    if (directory) {
      setSaveDirPath(directory)
      console.log(saveDirPath);
    }
  }

  function sendJson(msg) {
    window.electronAPI.sendToPython(msg);
  }


  return (

    <form method="post" onSubmit={handleSubmit} style = {{display: "flex", flexDirection: "row"}}>
      <textarea 
        name = "market_tickers" 
        style = {{resize: "none"}} 
        rows="5" 
        cols="40" 
        value={input}
        onChange = {(e) => setInput(e.target.value)}
        onKeyDown = {handleKeyDown}
        disabled={disabled}
        >    
      </textarea>
      {
        processInfo ? 
          <div style = {{display: "flex", flexDirection: "column", padding: "2px"}}>
          <span style = {{color: "white"}}>{processInfo}</span>
          <button 
            type="button" 
            onClick ={() => {setDisabled(false); setProcessInfo(null)}}
            >
            Cancel
          </button>
          </div>
        :
        <div style = {{display: "flex", flexDirection: "column", padding: "2px"}}>
          <div style = {{display: "flex"}}>
            <span style = {{color: "white"}}>Schedule ahead</span> 
            <input type="checkbox" name="scheduled_ahead" defaultChecked={!scheduleDisabled} onChange ={() => {setScheduleDisabled(!scheduleDisabled)}} />
          </div>
          <div style = {{display: "flex"}}>
            <input type="text" name="time_input" size="3" disabled={scheduleDisabled}/>
            <label style = {{color: "white"}}><input type="radio" name="time_ampm" value="am" disabled={scheduleDisabled}/>AM</label>
            <label style = {{color: "white"}}><input type="radio" name="time_ampm" value="pm" defaultChecked={true} disabled={scheduleDisabled}/>PM</label>
          </div>
          <button type = "button" onClick={chooseDirectory} style = {{margin: "2px"}}>Choose Dir</button>
          <button type="submit" disabled={disabled}>TRACK</button>
        </div>
      }
    </form>
  );
}



export default function MarketTracker() {
  const [numTrackedEvents, setNumTrackedEvents] = useState(1)
  
  function addEvent() {
    let newTrackedEvents = trackedEvents;
    newTrackedEvents.push(trackedEvents[-1]+1);
    setTrackedEvents(newTrackedEvents);
  }

  function openBrowser(link) {
    window.electronAPI.openExternalBrowser(link);
  }
  
  return (
    <Panel className = "panel" collapsible minSize={200}>
      <div className = "panelTitleContainer">
        <div className = "panelTitle">Market Tracker</div>
        <div className = "MarketTrackerInteriorContainer">

          <button 
            style = {{display: "flex", margin: "5px"}}
            onClick = {() => {openBrowser('https://pro.kalshi.com/workspace/markets?utm_campaign=pro_upsell&utm_medium=internal&utm_source=trading_portal&utm_content=navbar&pro_entrypoint=navbar')}}
          >
            Find Open Markets
          </button>

          <span style = {{color: "white"}}>Enter Market Tickers as comma seperated list: </span>
          
          {Array.from({length: numTrackedEvents}).map((_, i) => (
            <EventTrackForm key={i} />
            ))}
          <button type = "button"  style = {{margin: "2px"}} onClick = {() => setNumTrackedEvents(numTrackedEvents+1)}>Add Event</button>
          <button type = "button"  style = {{margin: "2px"}} onClick = {() => setNumTrackedEvents(numTrackedEvents-1)}>Remove Event</button>
        </div>
      </div>
    </Panel>
  );
}