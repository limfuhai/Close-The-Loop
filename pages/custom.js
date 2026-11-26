import AgentTab from '../components/AgentTab';

export default function CustomAgentsPage(props) {
  // This passes all props received from _app.js to the AgentTab component
  return <AgentTab {...props} />;
}