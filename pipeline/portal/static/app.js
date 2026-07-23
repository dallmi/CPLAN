(() => {
  'use strict';
  const state = { user: null };

  async function apiFetch(url, options) {
    const response = await fetch(url, options);
    if (response.status === 401) { showLoginOverlay(); throw new Error('unauthenticated'); }
    return response;
  }

  function showToast(message) {
    const el = document.getElementById('toast');
    el.textContent = message; el.classList.add('show');
    setTimeout(() => el.classList.remove('show'), 2600);
  }

  function showLoginOverlay() {
    document.getElementById('login-error').classList.add('hidden');
    document.getElementById('login-overlay').classList.remove('hidden');
    document.getElementById('login-username').focus();
  }
  function hideLoginOverlay() { document.getElementById('login-overlay').classList.add('hidden'); }

  function canAdmin() { return state.user && state.user.role === 'admin'; }

  async function initSession() {
    const response = await fetch('/api/me');
    if (response.status === 401) { showLoginOverlay(); return null; }
    state.user = await response.json();
    return state.user;
  }

  function renderChrome() {
    const chip = document.getElementById('user-chip');
    if (state.user && state.user.auth) {
      document.getElementById('user-chip-name').textContent = `${state.user.username} · ${state.user.role}`;
      chip.classList.remove('hidden');
    } else {
      chip.classList.add('hidden');
    }
    document.getElementById('user-admin').classList.toggle('hidden', !canAdmin());
  }

  async function loadProjects() {
    const data = await (await apiFetch('/api/portal/projects')).json();
    const tiles = document.getElementById('project-tiles');
    tiles.innerHTML = data.projects.length
      ? data.projects.map(p => `<a class="tile" href="${p.url}"><div class="tile-name">${escapeHtml(p.name)}</div><div class="tile-url">${escapeHtml(p.url)}</div></a>`).join('')
      : '<p class="subtitle">No projects assigned yet.</p>';
  }

  async function loadUsers() {
    if (!canAdmin()) return;
    const data = await (await apiFetch('/api/portal/users')).json();
    document.getElementById('user-rows').innerHTML = data.users.map(u => `
      <tr data-username="${escapeHtml(u.username)}">
        <td>${escapeHtml(u.username)}</td>
        <td>${escapeHtml(u.project)}</td>
        <td>
          <select class="role-select">
            ${['viewer','contributor','editor','admin'].map(r => `<option value="${r}"${r===u.role?' selected':''}>${r}</option>`).join('')}
          </select>
        </td>
        <td>${u.active ? 'Active' : 'Disabled'}</td>
        <td class="actions-col">
          <button class="btn-ghost act-password" type="button">Reset password</button>
          <button class="btn-ghost act-active" type="button">${u.active ? 'Disable' : 'Enable'}</button>
        </td>
      </tr>`).join('');
    wireUserRowActions();
  }

  function wireUserRowActions() {
    document.querySelectorAll('#user-rows tr').forEach(row => {
      const username = row.dataset.username;
      row.querySelector('.role-select').onchange = async (e) => {
        await postJson(`/api/portal/users/${encodeURIComponent(username)}/role`, { project: 'cplan', role: e.target.value });
        showToast(`Role updated for ${username}`); loadUsers();
      };
      row.querySelector('.act-password').onclick = async () => {
        const pw = window.prompt(`New password for ${username}:`);
        if (!pw) return;
        await postJson(`/api/portal/users/${encodeURIComponent(username)}/password`, { password: pw });
        showToast(`Password reset for ${username}`);
      };
      row.querySelector('.act-active').onclick = async () => {
        const enabling = row.querySelector('.act-active').textContent === 'Enable';
        await postJson(`/api/portal/users/${encodeURIComponent(username)}/active`, { active: enabling });
        showToast(`${username} ${enabling ? 'enabled' : 'disabled'}`); loadUsers();
      };
    });
  }

  async function postJson(url, body) {
    const response = await apiFetch(url, { method: "POST", headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!response.ok) { showToast('Action failed — you may not have permission.'); throw new Error('request failed'); }
    return response;
  }

  function openUserModal() {
    document.getElementById('uf-error').classList.add('hidden');
    document.getElementById('user-form').reset();
    document.getElementById('uf-project').value = 'cplan';
    document.getElementById('user-modal').classList.remove('hidden');
  }
  function closeUserModal() { document.getElementById('user-modal').classList.add('hidden'); }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  async function boot() {
    const user = await initSession();
    if (!user) return;
    renderChrome();
    await loadProjects();
    await loadUsers();
  }

  document.getElementById('login-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const username = document.getElementById('login-username').value.trim();
    const password = document.getElementById('login-password').value;
    const response = await fetch('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password }) });
    if (!response.ok) { document.getElementById('login-error').classList.remove('hidden'); return; }
    hideLoginOverlay();
    await boot();
  });

  document.getElementById('user-chip-logout').addEventListener('click', async () => {
    await fetch('/api/logout', { method: 'POST' });
    window.location.reload();
  });

  document.getElementById('user-new').addEventListener('click', openUserModal);
  document.getElementById('uf-cancel').addEventListener('click', closeUserModal);
  document.getElementById('user-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const body = {
      username: document.getElementById('uf-username').value.trim(),
      password: document.getElementById('uf-password').value,
      project: document.getElementById('uf-project').value,
      role: document.getElementById('uf-role').value,
    };
    try {
      const response = await apiFetch('/api/portal/users', { method: "POST", headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!response.ok) {
        const err = document.getElementById('uf-error');
        err.textContent = response.status === 403 ? 'You do not have permission.' : 'Could not create user (check the inputs).';
        err.classList.remove('hidden');
        return;
      }
      closeUserModal(); showToast(`User ${body.username} created`); loadUsers();
    } catch (_) { /* 401 already reopened the overlay */ }
  });

  boot();
})();
