(() => {
  'use strict';
  // The project page: one fetch, one render. The slug comes from the path, so
  // the page is linkable and the browser's back button works.
  const slug = location.pathname.split('/')[2];

  const ROLE_LABEL = { admin: 'Admin', editor: 'Editor', contributor: 'Contributor', viewer: 'Viewer' };
  function label(role) { return ROLE_LABEL[role] || role; }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  async function load() {
    const response = await fetch(`/api/portal/projects/${encodeURIComponent(slug)}`);
    if (response.status === 401) { location.href = '/'; return; }
    if (!response.ok) { showMissing(); return; }
    render(await response.json());
  }

  function showMissing() {
    document.getElementById('project-name').textContent = 'Project not found';
    document.getElementById('project-crumb').textContent = 'Not found';
    document.getElementById('project-purpose').textContent =
      'This project does not exist, or you do not have access to it.';
    document.getElementById('project-role').textContent = '';
    document.getElementById('project-tiles').innerHTML = '';
  }

  function render(project) {
    document.title = `${project.name} — CPLAN Portal`;
    document.getElementById('project-name').textContent = project.name;
    document.getElementById('project-crumb').textContent = project.name;
    document.getElementById('project-purpose').textContent = project.purpose || '';
    document.getElementById('project-role').textContent =
      project.role ? `You are ${label(project.role)} on this project.` : '';
    document.getElementById('project-tiles').innerHTML = project.tiles.map(tile => {
      const external = tile.kind === 'app' ? ' target="_blank" rel="noopener"' : '';
      const status = tile.status ? `<div class="tile-status">${escapeHtml(tile.status)}</div>` : '';
      return `<a class="tile${tile.primary ? ' tile-primary' : ''}" href="${escapeHtml(tile.href)}"${external}>`
        + `<div class="tile-name">${escapeHtml(tile.title)}</div>${status}</a>`;
    }).join('');
  }

  // The top bar shows only who is signed in — no role label here. Roles are
  // per project, and the page's own sentence above states this project's
  // role; a second, portal-wide "role" next to the username would repeat
  // the exact contradiction this page exists to avoid.
  async function loadUserChip() {
    const response = await fetch('/api/me');
    if (response.status === 401) { location.href = '/'; return; }
    const user = await response.json();
    document.getElementById('user-chip-name').textContent = user.username;
    document.getElementById('user-chip').classList.remove('hidden');
  }

  document.getElementById('user-chip-logout').addEventListener('click', async () => {
    await fetch('/api/logout', { method: 'POST' });
    window.location.href = '/';
  });

  loadUserChip();
  load();
})();
