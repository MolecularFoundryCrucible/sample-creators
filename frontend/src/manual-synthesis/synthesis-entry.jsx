// Synthesis upload page (React island). Replaces manual-synthesis-ui's App.jsx for this view:
// login comes from the page, and the summary's "log out" uses the page's logout.
import React, { useState } from 'react';
import ReactDOM from 'react-dom/client';
import MainForm from './components/MainForm';
import Summary from './components/Summary';
import { useCurrentUser } from './user';
import './styles/App.css';

function SynthesisApp() {
  const user = useCurrentUser();
  const [summary, setSummary] = useState(null);

  if (user === undefined) return <p className="muted">Loading…</p>;
  if (!user) return <p className="muted">Log in to upload synthesis data.</p>;

  if (summary) {
    return (
      <Summary
        message={summary.message}
        summary={summary.details}
        onAddMore={() => setSummary(null)}
        onLogout={() => { setSummary(null); window.logoutUser?.(); }}
      />
    );
  }
  return (
    <MainForm
      key={user.orcid}
      userInfo={user}
      onUploadSuccess={(message, details) => setSummary({ message, details })}
    />
  );
}

const root = document.getElementById('synthesis-root');
if (root) {
  ReactDOM.createRoot(root).render(
    <React.StrictMode>
      <SynthesisApp />
    </React.StrictMode>
  );
}
