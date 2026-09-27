
import '../App.css';



function MenuButton({buttonLabel, buttonOptions}) {
  return (
    <div className="dropdown">
      <button>{buttonLabel}</button>
      <div className = "dropdown-content">
        {buttonOptions.map((opt, i) => (<a href="#" key={i}>{opt}</a>))}
      </div>
    </div>
  );
}

export default function CustomMenu() {
  return (
    <div style={{display: "flex", flexDirection: "row"}} >
      <MenuButton 
        buttonLabel={"File"} 
        buttonOptions={["Option 1", "Option 2", "Option 3"]}/>
      <MenuButton 
        buttonLabel="View" 
        buttonOptions={["Market Tracker", "Workspace", "Replayer"]}/>
      <MenuButton 
        buttonLabel={"Help"} 
        buttonOptions={["Option 1", "Option 2", "Option 3"]}/>
    </div>
  );
}