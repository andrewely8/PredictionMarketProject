import { MemoryRouter as Router, Routes, Route } from 'react-router-dom';
import { useState } from 'react';
import { Group, Panel, Separator} from "react-resizable-panels";
import CustomMenu from './components/CustomMenu.jsx';
import MarketTracker from './components/MarketTracker.jsx';
import Workspace from './components/Workspace.jsx';
import Replayer from './components/Replayer.jsx';
import icon from '../../assets/icon.svg';
import './App.css';


function Hello() {
  const [marketTrackerActive, setMarketTrackerActive] = useState(true)
  return (
    <div className = "topMenu">
      <CustomMenu/>
      <div className = "entireCanvas">
        <Group orientation="vertical" >
          <Panel collapsible minSize={200} >
            <Group orientation="horizontal">
              <MarketTracker />
              <Separator className = "verticalSeperator"/>
              <Workspace/>
            </Group>
          </Panel>
          <Separator className = "horizontalSeperator"/>
          <Replayer/>
        </Group>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<Hello/>} />
      </Routes>
    </Router>
  );
}
