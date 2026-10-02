import { useState, useEffect } from "react";
import {Panel} from "react-resizable-panels";
import { useStopwatch } from '../utils/customUseTimer';
import { useGlobal } from "../contexts/GlobalContext.tsx";
import '../App.css';


export default function Replayer() {
  const speeds = ["1","2","5","10","50","100"];
  const Global = useGlobal();
  const [speedIndex,setSpeedIndex] = useState(0);
  const [currentOrderbooks, setCurrentOrderbooks] = useState(null);
  const {
    totalSeconds,
    totalMilliseconds,
    milliseconds,
    seconds,
    minutes,
    hours,
    days,
    isRunning,
    start,
    pause,
    reset,
    setPlaybackSpeed,
  } = useStopwatch({ autoStart: false, interval: 1 });


  //TODO:
  // this file (replayer.jsx) controls a (the) timer.
  // every tick of the timer, it sends the tick to a
  // electron main.ts function. This function preforms
  // the logic that updates the orderbook, and returns a curent
  // orderbook (full build) back to replayer.jsx.
  // So, electron main.ts will hold the data file, and process the
  // data file, similar to how backend.py functions. 
  // ( also, Replayer.jsx should only rerender if it recives new orderbook
  // top orders which will change the visual of the component, hence
  // renders are not going to be every tick, or even every main.ts func call,
  // only when top of book changes).

  useEffect(() => {
    const filePath = Global.workspaceDir + "/" + Global.currentReplayFile
    
    const getResp = async () => { 
      const resp = await window.electronAPI.readFile(filePath);
      setCurrentOrderbooks(resp);
      console.log(resp);
    }
    getResp();


  },[Global.currentReplayFile])


  useEffect(() => {
    const getResp = async () => {
      const resp = await window.electronAPI.processTick(totalMilliseconds);
      if (resp) {
        setCurrentOrderbooks(resp);
      }
    }
    getResp();

  },[totalMilliseconds])


  return (
    <Panel className = "panel" collapsible minSize={200}>
      <div className = "panelTitleContainer">
        <div className = "panelTitle">Replayer</div>
          <div className = "MarketTrackerInteriorContainer">
            <div style = {{flexDirection: "column"}}>
              <span style = {{color: "white", display: "flex"}}>Data File: {Global.currentReplayFile} </span>
             
              <div style = {{color: "white", display: "flex"}}>
                <span style = {{marginRight : "10px"}}>Current Time: </span><span>{(hours <10) ? 0 : null}{hours}:{(minutes <10) ? 0 : null}{minutes}:{(seconds <10) ? 0 : null}{seconds}</span>
              </div>
              <div>
                <button 
                  disabled = {Global.currentReplayFile ? false : true} 
                  onClick = {() => {isRunning ? pause() : start()}}
                >
                  {isRunning ? "pause" : "play" }
                </button>
                <span style = {{color: "white", marginLeft: "10px"}}>Playback speed:</span>
                <button 
                  disabled = {Global.currentReplayFile ? false : true} 
                  onClick = {() => {
                    setPlaybackSpeed(Number(speeds[((speedIndex+1)%speeds.length)])); 
                    setSpeedIndex((speedIndex+1)%speeds.length);
                  }}
                >
                  {speeds[speedIndex]}
                </button>
                <button 
                  disabled = {Global.currentReplayFile ? false : true} 
                  onClick = {() => {reset()}}
                >
                  reset
                </button>

                <div style = {{ flexDirection: "row", color: "white", marginBottom: "10px"}}>
                  {currentOrderbooks &&
                    [...currentOrderbooks.entries()].map(([ticker, book],i) => (
                      <div key={i} style = {{ marginTop: "10px"}}>
                        <span>{ticker}</span>
                          <div>
                            
                            <div>
                              <span style = {{ margin: "5px"}}>best_yes_bid_dollars: {book.best_yes_bid_dollars}</span>
                              <span style = {{ margin: "5px"}}>best_yes_bid_volume: {book.best_yes_bid_volume}</span>
                            </div>

                            <div>
                              <span style = {{ margin: "5px"}}>best_yes_ask_dollars: {book.best_yes_ask_dollars}</span>
                              <span style = {{ margin: "5px"}}>best_yes_ask_volume: {book.best_yes_ask_volume}</span>
                            </div>

                            <div>
                              <span style = {{ margin: "5px"}}>best_no_bid_dollars: {book.best_no_bid_dollars}</span>
                              <span style = {{ margin: "5px"}}>best_no_bid_volume: {book.best_no_bid_volume}</span>
                            </div>

                            <div>
                              <span style = {{ margin: "5px"}}>best_no_ask_dollars: {book.best_no_ask_dollars}</span>
                              <span style = {{ margin: "5px"}}>best_no_ask_volume: {book.best_no_ask_volume}</span>
                            </div>

                          </div>
                      </div>
                  ))}
                </div>
                
              </div>
            </div>
          </div>
      </div>
    </Panel>
  );
}



 

