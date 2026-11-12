// The logged-in user for the React islands, in the shape their components expect
// ({email, orcid, name, projects}). The page's login panel (shared.js) announces changes with
// a "crucible:user" event; on load we ask the server.
import { useEffect, useState } from 'react';

// eslint-disable-next-line no-undef
const prefix = typeof BASE_URL === 'string' ? BASE_URL : '';

function toUserInfo(user) {
  if (!user) return null;
  return {
    email: user.email || '',
    orcid: user.orcid || '',
    name: user.user_name || user.username || '',
    projects: user.projects || [],
    selectedProject: user.selected_project || '',
  };
}

export function useCurrentUser() {
  const [user, setUser] = useState(undefined); // undefined = still loading

  useEffect(() => {
    let cancelled = false;
    fetch(`${prefix}/api/user`, { credentials: 'same-origin' })
      .then((r) => (r.ok ? r.json() : null))
      .then((u) => { if (!cancelled) setUser(toUserInfo(u)); })
      .catch(() => { if (!cancelled) setUser(null); });

    const onChange = (event) => setUser(toUserInfo(event.detail));
    window.addEventListener('crucible:user', onChange);
    return () => {
      cancelled = true;
      window.removeEventListener('crucible:user', onChange);
    };
  }, []);

  return user;
}
