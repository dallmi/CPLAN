/* Every call is same-origin and cookie-authenticated. Mutations never throw:
   they resolve to {ok, message} so a caller can toast the server's own
   validation text (422 carries it) instead of inventing one. */

async function post(url, body) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (response.ok) return { ok: true };
  if (response.status === 401) { window.location.reload(); return { ok: false, message: 'Session expired.' }; }
  if (response.status === 403) return { ok: false, message: 'You do not have permission.' };
  if (response.status === 422) return { ok: false, message: await validationMessage(response) };
  return { ok: false, message: 'The change could not be saved.' };
}

/* 422 bodies carry the portal.* function's own RAISE EXCEPTION text, e.g.
   "user x already exists". Postgres appends a CONTEXT block — take line one. */
async function validationMessage(response) {
  try {
    const body = await response.json();
    const message = body?.detail?.message;
    if (typeof message === 'string' && message.trim()) {
      return message.split('\n')[0].replace(/^ERROR:\s*/i, '').trim();
    }
  } catch (_) { /* not JSON */ }
  return 'That input was rejected.';
}

export async function getSession() {
  const response = await fetch('/api/me');
  return response.ok ? response.json() : null;
}

export async function signIn(username, password) {
  return (await post('/api/login', { username, password })).ok;
}

export async function signOut() {
  await fetch('/api/logout', { method: 'POST' });
}

export async function fetchProjects() {
  const response = await fetch('/api/portal/projects');
  return response.ok ? (await response.json()).projects : [];
}

export async function fetchUsers() {
  const response = await fetch('/api/portal/users');
  return response.ok ? (await response.json()).users : [];
}

const encode = encodeURIComponent;
export const setRole = (username, project, role) => post(`/api/portal/users/${encode(username)}/role`, { project, role });
export const revokeRole = (username, project) => post(`/api/portal/users/${encode(username)}/revoke`, { project });
export const resetPassword = (username, password) => post(`/api/portal/users/${encode(username)}/password`, { password });
export const setActive = (username, active) => post(`/api/portal/users/${encode(username)}/active`, { active });
export const setDisplayName = (username, displayName) => post(`/api/portal/users/${encode(username)}/display-name`, { display_name: displayName });
export const createUser = (payload) => post('/api/portal/users', payload);
