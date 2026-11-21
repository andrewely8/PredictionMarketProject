import {Panel} from "react-resizable-panels";
import { useState, useEffect, useCallback, useRef } from "react";
import { useGlobal } from "../contexts/GlobalContext.tsx";
import { validateScheduledTime } from '../utils/validateTimeInput';
import { getScheduledEvents, createScheduledEvent } from "../api/scheduledEvents";
import { getKalshiMarketSearch } from "../api/kalshiMarketSearch";
import { APP_CONFIG } from "../config/constants.js";
import '../App.css';

// TODO:
// 1) Construct a scheduler file that is loaded upon opening the application,
//    read into current list of events in Market Tracker Window/Pannel and actual data collection pipeline,
//    and written to during new scheduled ahead form submissions.
// 2) Check that for each market ticker list input, the listed tickers are apart of the same event.
// 3) Allow user searching for events / series / tickers to select and add to list.
//    Tickers should be grouped by events and added to different input lists. 
// 4) error handling via UI messages.

//function openBrowser
// opens users local browser to the link url
// link: a url
function openBrowser(link) {
  window.electronAPI.openExternalBrowser(link);
}



//function loadEvents
// fetches scheduled events from js client api
// returns: events as a list
async function loadEvents() {
  const data = await getScheduledEvents();
  return Object.entries(data).map(([id, event]) => ({id, ...event,}));
}


//
//
//
function groupEvents(events) {
  
}



//function EventTrackFrom
// react component for event scheduling form
// onEventCreated: callback function for when form is submitted
// onRemove: callback function for when form is deleted
// returns: jsx
function EventTrackForm({ onEventCreated, onRemove }) {
  const [input, setInput] = useState("");
  const [disabled, setDisabled] = useState(false);
  const [processInfo, setProcessInfo] = useState(null);
  const [saveDirPath, setSaveDirPath] = useState(APP_CONFIG.recording.defaultSaveDirectory);
  const [scheduleDisabled, setScheduleDisabled] = useState(false);

  async function chooseDirectory() {
    const directory = await window.electronAPI.selectDirectory();
    if (directory) {
      setSaveDirPath(directory)
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const formData = new FormData(e.currentTarget);
    const formJson = {
      ...Object.fromEntries(formData.entries()),
      save_dir: saveDirPath,
    };
    setDisabled(true);
    setProcessInfo("validating...");
    try {
      if (formJson.scheduled_ahead === "on") {
        const isoTime = validateScheduledTime(
          formJson.date_input,
          formJson.time_input,
          formJson.time_ampm
        );
        if (!isoTime.success) {
          throw new Error("Invalid scheduled time");
        }
        const jsonWithTime = {
          ...formJson,
          iso_time: isoTime.iso_time,
          status: "scheduled",
        };
        console.log("jsonWithTime INPUT: ", jsonWithTime);
        const response = await createScheduledEvent(jsonWithTime);
        await onEventCreated();
        onRemove();
      } else {
        const jsonWithTime = {
          ...formJson,
          scheduled_ahead: "off",
          date_input: "",
          time_input: "",
          time_ampm: "",
          iso_time: new Date().toISOString(),
          status: "starting",
        };
        console.log("jsonWithTime INPUT: ", jsonWithTime);
        const response = await createScheduledEvent(jsonWithTime);
        await onEventCreated();
        onRemove();
        setProcessInfo("Submitted successfully");
      }
    } catch (error) {
      console.error("Submission failed:", error);
      setProcessInfo("Submission failed");
    } finally {
      setDisabled(false);
    }
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
          <input type="text" name="date_input" size="3" disabled={scheduleDisabled} placeholder="MM/DD/YYYY"/>
          <div style = {{display: "flex"}}>
            <input type="text" name="time_input" size="3" disabled={scheduleDisabled}/>
            <label style = {{color: "white"}}><input type="radio" name="time_ampm" value="am" disabled={scheduleDisabled}/>AM</label>
            <label style = {{color: "white"}}><input type="radio" name="time_ampm" value="pm" defaultChecked={true} disabled={scheduleDisabled}/>PM</label>
          </div>
          <button type = "button" onClick={chooseDirectory} style = {{margin: "2px"}}>Choose Dir</button>
          <button type="submit" disabled={disabled} style = {{margin: "2px"}}>TRACK</button>
          <button type="button" onClick={onRemove} disabled={disabled} style = {{margin: "2px"}}>Remove Event</button>
        </div>
      }
    </form>
  );
}



//function TrackedEvent
// react component for events currently scheduled or currently being recorded
// eventData: json-like object containing events information
// returns: jsx
function TrackedEvent({eventData}) {

  const displayTime = new Date(eventData.iso_time).toLocaleString();

  return(
    <div className = "eventTrackerForm" style = {{color: "white"}}>
      <p>tracking tickers: {eventData.market_tickers}</p>
      <p>Saving to: {eventData.save_dir}</p>
      {eventData.status === "scheduled" ?
        <p className = "blueColorText">Scheduled For: {displayTime}</p>
      :
        <p className = "greenColorText">Currently Recording</p>
      }
    </div>
  )
}



//function MarketSearcher
// react component for searching markets
// returns: jsx
function MarketSearcher() {
  const [searchQuery, setSearchQuery] = useState("");
  const [result, setResult] = useState(null);
  const [selectAll, setSelectAll] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const requestId = useRef(0);

  async function search(jsonQuery, id) {
    setBusy(true);
    setError('');
    try {
      console.log("SENDING jsonQuery = ", jsonQuery);
      const r = await getKalshiMarketSearch(jsonQuery);
      console.log("RESULT r= ", r)
      if (id !== requestId.current) {
        return;
      }
      r.markets.forEach(event => {
        event.selected = false;
      });
      setResult(r);
      if (!r.markets.length) {
        setError(`Nothing found for ${jsonQuery}`);
      }
    } catch (err) {
      if (id === requestId.current) {
        setError(err.message);
      }
    } finally {
      if (id === requestId.current) {
        setBusy(false);
      }
    }
  }

  useEffect(() => {
    const id = ++requestId.current;
    const query = searchQuery.trim();

    setResult(null);
    setError('');
    setBusy(false);
    if (!query){
      return;
    }
    const jsonQuery = {
      query: query,
    };
    const timeout = setTimeout(() => {
      search(jsonQuery, id);
    }, 300);

    return () => clearTimeout(timeout);
  }, [searchQuery]);


  function updateSelectedStatus(currentTicker) {
    setResult(prev => ({
      ...prev,
      markets: prev.markets.map(event =>
        event.ticker === currentTicker
          ? { ...event, selected: !event.selected }
          : event
      )
    }));
  }

  function updateSelectedStatusSelectAll() {
    setResult(prev => ({
      ...prev,
      markets: prev.markets.map(event => ({
        ...event,
        selected: !selectAll
      }))
    }));
    setSelectAll(!selectAll);
  }

  return (
    <div className = "eventTrackerForm" style = {{color: "white"}} >
      <div style={{display: "flex", flexDirection:"row"}}>
        <input
          type="search"
          placeholder="Search markets..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        <button 
          style = {{display: "flex", margin: "5px"}}
          onClick = {() => {openBrowser('https://pro.kalshi.com/workspace/markets?utm_campaign=pro_upsell&utm_medium=internal&utm_source=trading_portal&utm_content=navbar&pro_entrypoint=navbar')}}
        >
          Find Open Markets
        </button>
      </div>
      <span>Results:</span>
      {result ?
        <div>
          {result.markets.map((event) => (
            <div
              key={event.ticker} 
              className = "eventTrackerForm"
              style = {{margin: "2px", display: "flex", flexDirection: "column"}}
            >
              <span>title: {event.title}</span> 
              <span>subtitle: {event.subtitle}</span> 
              <span>ticker: {event.ticker}</span>
              <button 
                style = {{margin: "5px"}}
                onClick = {() => {updateSelectedStatus(event.ticker)}}
              >
                {event.selected ?
                  "UnSelect"
                :
                  "Select"
                }  
              </button> 
            </div>
            
          ))}
        </div>
      :
        <p>{error}</p>
      }
      <div style = {{display: "flex", flexDirection: "row"}}>
      <button 
        style = {{display: "flex", margin: "5px"}}
        onClick = {() => {updateSelectedStatusSelectAll()}}
      >
        { selectAll ?
          "UnSelect All"
          :
          "Select All"
        }
      </button>
      <button 
        style = {{display: "flex", margin: "5px"}}
        onClick = {() => {console.log("pressed")}}
      >
        Add Selected
      </button>
      </div>
    </div>
  );
}



//function MarketTracker
// main react component for this file
// returns: jsx
export default function MarketTracker() {
  const Global = useGlobal();
  const [formIds, setFormIds] = useState([0]);
  const [nextFormId, setNextFormId] = useState(1);
  const [scheduledEvents, setScheduledEvents] = useState([]);

  const refreshEvents = useCallback(async () => {
    const events = await loadEvents();
    setScheduledEvents(events);
  }, []);

  useEffect(() => {
    refreshEvents().catch(console.error);
  }, [refreshEvents]);

  return (
    <Panel className = "panel" collapsible minSize={200}>
      <div className = "panelTitleContainer">
        <div className = "panelTitle">Market Tracker</div>
        <div className = "MarketTrackerInteriorContainer">
          <MarketSearcher/>
          <div className="eventTrackerForm">
            <span style = {{color: "white"}}>Enter market tickers as comma seperated lists: </span>
            {formIds.map((id) => (
              <EventTrackForm
                key={id}
                onEventCreated={refreshEvents}
                onRemove={() => {
                  setFormIds(prev => prev.filter(formId => formId !== id));
                }}
              />
            ))}
            <button
              type="button"
              onClick={() => {
                setFormIds(prev => [...prev, nextFormId]);
                setNextFormId(prev => prev + 1);
              }}
            >
              Add Event
            </button>
            <button
              type="button"
              onClick={() => {
                console.log("pressed");
              }}
            >
              Track All
            </button>
          </div>
          <div>
            <span style = {{color: "white"}}>Currently Tracking: </span>
            {scheduledEvents.map((event) => (
              <TrackedEvent key={event.id} eventData={event}/> 
            ))}
          </div>
        </div>
      </div>
    </Panel>
  );
}