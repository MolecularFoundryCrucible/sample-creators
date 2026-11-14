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

export function syncSelectedProject(project) {
  if (!project || typeof window === 'undefined') return;
  if (typeof window.setProject === 'function') {
    window.setProject(project).catch(() => {});
  }
}

export function useCurrentUser() {
  const [user, setUser] = useState(() => (
    typeof window !== 'undefined' && window.__crucibleUser !== undefined
      ? toUserInfo(window.__crucibleUser)
      : undefined
  )); // undefined = still loading

  useEffect(() => {
    let cancelled = false;
    let receivedEvent = false;
    const onChange = (event) => {
      receivedEvent = true;
      setUser(toUserInfo(event.detail));
    };
    window.addEventListener('crucible:user', onChange);

    if (window.__crucibleUser !== undefined) {
      setUser(toUserInfo(window.__crucibleUser));
    } else {
      const pending = window.__crucibleUserPromise
        ? window.__crucibleUserPromise
        : fetch(`${prefix}/api/user`, { credentials: 'same-origin' })
            .then((r) => (r.ok ? r.json() : null))
            .catch(() => null);
      pending.then((u) => {
        if (!cancelled && !receivedEvent) setUser(toUserInfo(u));
      });
    }

    return () => {
      cancelled = true;
      window.removeEventListener('crucible:user', onChange);
    };
  }, []);

  return user;
}
