import { Group, Panel, Separator } from 'react-resizable-panels';
import CustomMenu from './components/CustomMenu';
import MarketTracker from './components/MarketTracker';
import Workspace from './components/Workspace';
import Replayer from './components/Replayer';
import AIResearchPanel from './components/ai/AIResearchPanel';
import { GlobalProvider } from './contexts/GlobalContext';
import './App.css';

export default function App() {
  return (
    <GlobalProvider>
      <div className="topMenu">
        <CustomMenu />
        <div className="entireCanvas">
          <Group orientation="vertical">
            <Panel collapsible minSize={200} defaultSize="55%">
              <Group orientation="horizontal">
                <MarketTracker />
                <Separator className="verticalSeperator" />
                <Workspace />
                <Separator className="verticalSeperator" />
                <AIResearchPanel />
              </Group>
            </Panel>
            <Separator className="horizontalSeperator" />
            <Replayer />
          </Group>
        </div>
      </div>
    </GlobalProvider>
  );
}
