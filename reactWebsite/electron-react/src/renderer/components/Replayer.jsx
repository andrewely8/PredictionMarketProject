import {Panel} from "react-resizable-panels";
import '../App.css';



export default function Replayer() {
  return (
    <Panel className = "panel" collapsible minSize={200}>
      <div className = "panelTitleContainer">
        <div className = "panelTitle">Replayer</div>
          <div className = "MarketTrackerInteriorContainer">
            <span style = {{color: "white"}}>Hello </span>
          </div>
      </div>
    </Panel>
  );
}