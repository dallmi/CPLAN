/* Every call is same-origin and cookie-authenticated. Mutations never throw:
   they resolve to {ok, message} so a caller can toast the server's own
   validation text (422 carries it) instead of inventing one. A network
   failure (offline, DNS, aborted request) is folded into that same contract
   rather than left to reject the promise -- otherwise an offline mutation
   throws an unhandled rejection with no toast. */

// A 401 means "your session is gone" for every mutating endpoint except
// /api/login itself, which returns 401 for a plain wrong password. Reloading
// on that one would wipe the sign-in form before the user ever sees why.
async function post(url, body, { sessionOn401 = true } = {}) {
  let response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (_) {
    return { ok: false, message: 'Could not reach the server. Check your connection and try again.' };
  }
  if (response.ok) return { ok: true };
  if (response.status === 401) {
    if (sessionOn401) { window.location.reload(); return { ok: false, message: 'Session expired.' }; }
    return { ok: false, message: 'Username or password is not correct.' };
  }
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
  try {
    const response = await fetch('/api/me');
    return response.ok ? response.json() : null;
  } catch (_) {
    return null;
  }
}

export async function signIn(username, password) {
  // /api/login is the one endpoint where a 401 is a wrong password, not an
  // expired session -- it must not reload the page out from under the user.
  return (await post('/api/login', { username, password }, { sessionOn401: false })).ok;
}

export async function signOut() {
  try {
    await fetch('/api/logout', { method: 'POST' });
  } catch (_) { /* signing out locally still proceeds */ }
}

// null means "the read failed" -- offline, a 500, anything short of a real
// answer. That is not the same thing as [], a genuinely empty result, and a
// caller must tell the two apart instead of silently rendering "0 of 0".
export async function fetchProjects() {
  try {
    const response = await fetch('/api/portal/projects');
    return response.ok ? (await response.json()).projects : null;
  } catch (_) {
    return null;
  }
}

export async function fetchUsers() {
  try {
    const response = await fetch('/api/portal/users');
    return response.ok ? (await response.json()).users : null;
  } catch (_) {
    return null;
  }
}

const encode = encodeURIComponent;
export const setRole = (username, project, role) => post(`/api/portal/users/${encode(username)}/role`, { project, role });
export const revokeRole = (username, project) => post(`/api/portal/users/${encode(username)}/revoke`, { project });
export const resetPassword = (username, password) => post(`/api/portal/users/${encode(username)}/password`, { password });
export const setActive = (username, active) => post(`/api/portal/users/${encode(username)}/active`, { active });
export const setDisplayName = (username, displayName) => post(`/api/portal/users/${encode(username)}/display-name`, { display_name: displayName });
export const createUser = (payload) => post('/api/portal/users', payload);
