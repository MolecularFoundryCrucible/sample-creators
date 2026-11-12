// Fabrication traveler page (React island). Replaces manual-synthesis-ui's App.jsx for this
// view: login comes from the page; /fabrication/wafer/<id> opens that wafer directly.
import React from 'react';
import ReactDOM from 'react-dom/client';
import FabTraveler from './components/fab/FabTraveler';
import { useCurrentUser } from './user';
import './styles/App.css';

function TravelerApp({ initialWaferId }) {
  const user = useCurrentUser();
  if (user === undefined) return <p className="muted">Loading…</p>;
  if (!user) return <p className="muted">Log in to open the fabrication traveler.</p>;
  return <FabTraveler key={user.orcid} userInfo={user} initialWaferId={initialWaferId} />;
}

const root = document.getElementById('traveler-root');
if (root) {
  ReactDOM.createRoot(root).render(
    <React.StrictMode>
      <TravelerApp initialWaferId={root.dataset.waferId || null} />
    </React.StrictMode>
  );
}
