/* portal.users returns one row per user x project x role. The UI thinks in
   people, so rows are pivoted into accounts carrying a per-project map.

   Phase 1 scope: groups do not exist yet, and every grant here is direct.
   accountsFromRows() pivots the raw rows into one object per person with a
   flat per-project role map -- no inheritance, no effective()-style resolver.
   A later phase adds those once groups land. */

export const ROLES = ['viewer', 'contributor', 'editor', 'admin'];
export const ROLE_LABEL = { admin: 'Admin', editor: 'Editor', contributor: 'Contributor', viewer: 'Viewer' };
export const ROLE_DESC = {
  admin: 'Everything an editor can do, plus deleting activities and managing access.',
  editor: 'Create activities and edit any activity, including other people’s.',
  contributor: 'Create activities and edit only the ones they created.',
  viewer: 'Read everything. Change nothing.',
};

export const state = {
  me: null, projects: [], users: [], page: 'home', userSort: { key: 'name', dir: 1 },
  // Set by loadHome()/loadUsers() in home.js/users.js: true when the last
  // read failed (offline, non-2xx), so home/users/matrix can render a
  // distinguishable error state instead of a false "0 of 0" empty result.
  projectsLoadFailed: false, usersLoadFailed: false,
};

export const rank = (role) => (role ? ROLES.indexOf(role) : -1);
export const project = (slug) => state.projects.find((p) => p.slug === slug);

export function accountsFromRows(rows) {
  const byUser = new Map();
  rows.forEach((r) => {
    if (!byUser.has(r.username)) {
      byUser.set(r.username, {
        username: r.username,
        name: r.display_name || r.username,
        active: r.active,
        lastSignIn: r.last_sign_in,
        grants: {},
      });
    }
    const account = byUser.get(r.username);
    // Defensive: a user should hold one assignable role per project, but role
    // membership is additive, so keep the strongest if the data ever disagrees.
    if (rank(r.role) > rank(account.grants[r.project])) account.grants[r.project] = r.role;
  });
  return [...byUser.values()];
}

export const accessFor = (account, slug) => account.grants[slug] || null;
export const projectCount = (account) => Object.keys(account.grants).length;
export const highestRole = (account) =>
  Object.values(account.grants).reduce((best, r) => (rank(r) > rank(best) ? r : best), null);

export function statusOf(account) {
  if (!account.active) return 'disabled';
  return account.lastSignIn ? 'active' : 'pending';
}

export function formatSignIn(iso) {
  if (!iso) return 'Never';
  return new Date(iso).toLocaleString(undefined, {
    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}
