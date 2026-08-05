/* The shipped portal had no search, no filter and no sort — fine at six users,
   unusable at sixty. Filtering is client-side: the endpoint deliberately
   returns the full set, matching the rest of this local-first deployment. */
import { fetchUsers } from './api.js';
import { state, accountsFromRows, highestRole, projectCount, statusOf, rank } from './state.js';
import { esc, roleChip, statusCell, signInLabel, toast } from './ui.js';
import { openDrawer } from './drawer.js';

export async function loadUsers() {
  const rows = await fetchUsers();
  state.usersLoadFailed = rows === null;
  state.users = rows === null ? [] : accountsFromRows(rows);
  if (state.usersLoadFailed) toast('Could not load users. Check your connection and try again.');
}

function filtered() {
  const query = document.getElementById('user-search').value.trim().toLowerCase();
  const role = document.getElementById('user-filter-role').value;
  const status = document.getElementById('user-filter-status').value;
  const list = state.users.filter((u) => {
    if (query && !(u.name.toLowerCase().includes(query) || u.username.toLowerCase().includes(query))) return false;
    if (status && statusOf(u) !== status) return false;
    if (role && !Object.values(u.grants).includes(role)) return false;
    return true;
  });
  const { key, dir } = state.userSort;
  list.sort((a, b) => {
    if (key === 'projects') return (projectCount(a) - projectCount(b)) * dir;
    if (key === 'role') return (rank(highestRole(a)) - rank(highestRole(b))) * dir;
    return a.name.localeCompare(b.name) * dir;
  });
  return list;
}

export function renderUsers() {
  const table = document.getElementById('user-table');
  const empty = document.getElementById('user-empty');
  const loadError = document.getElementById('user-load-error');

  if (state.usersLoadFailed) {
    document.getElementById('user-count').textContent = '';
    table.hidden = true;
    empty.hidden = true;
    loadError.hidden = false;
    return;
  }
  loadError.hidden = true;

  const list = filtered();
  document.getElementById('user-count').textContent = `${list.length} of ${state.users.length} users`;
  // The header row must not float above the "no users match" panel with no
  // body beneath it -- hide the table itself, not just the empty panel.
  table.hidden = list.length === 0;
  empty.hidden = list.length > 0;
  document.getElementById('user-rows').innerHTML = list.map((u) => `
    <tr${u.active ? '' : ' class="is-disabled"'}>
      <td>
        <button class="name-btn" type="button" data-open="${esc(u.username)}">${esc(u.name)}</button>
        <div class="cell-sub">${esc(u.username)}</div>
      </td>
      <td>${roleChip(highestRole(u))}</td>
      <td class="num">${projectCount(u)}</td>
      <td>${statusCell(u)}</td>
      <td class="num">${esc(signInLabel(u.lastSignIn))}</td>
      <td class="cell-actions"><button class="btn sm" type="button" data-open="${esc(u.username)}">Manage</button></td>
    </tr>`).join('');
  document.querySelectorAll('#user-rows [data-open]').forEach((el) => {
    el.onclick = () => openDrawer(el.dataset.open);
  });
}

export function wireUsers() {
  ['user-search', 'user-filter-role', 'user-filter-status'].forEach((id) => {
    document.getElementById(id).oninput = renderUsers;
  });
  document.getElementById('user-clear-filters').onclick = () => {
    ['user-search', 'user-filter-role', 'user-filter-status'].forEach((id) => {
      document.getElementById(id).value = '';
    });
    renderUsers();
  };
  // The click handler binds to the inner <button> (a keyboard user can Tab to
  // and Enter/Space it) while data-sort and aria-sort stay on the <th>, where
  // a screen reader expects sort state to live.
  document.querySelectorAll('#user-table th.sortable').forEach((th) => {
    th.querySelector('.sort-btn').onclick = () => {
      const key = th.dataset.sort;
      state.userSort = { key, dir: state.userSort.key === key ? -state.userSort.dir : 1 };
      document.querySelectorAll('#user-table th').forEach((h) => {
        h.removeAttribute('aria-sort');
        const arrow = h.querySelector('.sort-arrow');
        if (arrow) arrow.textContent = '';
      });
      th.setAttribute('aria-sort', state.userSort.dir === 1 ? 'ascending' : 'descending');
      th.querySelector('.sort-arrow').textContent = state.userSort.dir === 1 ? '↑' : '↓';
      renderUsers();
    };
  });
}
