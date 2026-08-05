/* User x project, one cell per grant. Needs no dedicated endpoint: portal.users
   already returns one row per user x project x role, so this is a pure pivot.
   The chip's fill weight encodes privilege — see the ramp in styles.css. */
import { setRole, revokeRole } from './api.js';
import { state, ROLES, ROLE_LABEL, accessFor, project } from './state.js';
import { esc, roleChip, toast, closePopover } from './ui.js';
import { openDrawer } from './drawer.js';
import { loadUsers } from './users.js';

function visible() {
  const query = document.getElementById('matrix-search').value.trim().toLowerCase();
  const only = document.getElementById('matrix-filter-project').value;
  return {
    columns: only ? state.projects.filter((p) => p.slug === only) : state.projects,
    rows: state.users.filter(
      (u) => !query || u.name.toLowerCase().includes(query) || u.username.toLowerCase().includes(query),
    ),
  };
}

export function renderMatrix() {
  const filter = document.getElementById('matrix-filter-project');
  if (filter.options.length <= 1 && state.projects.length) {
    filter.innerHTML = '<option value="">All projects</option>' +
      state.projects.map((p) => `<option value="${esc(p.slug)}">${esc(p.name)}</option>`).join('');
  }

  const { columns, rows } = visible();
  document.getElementById('matrix-count').textContent =
    `${rows.length} users · ${columns.length} projects`;

  document.getElementById('matrix-head').innerHTML =
    '<th class="cell-user">User</th>' +
    columns.map((p) => {
      const withAccess = rows.filter((u) => accessFor(u, p.slug)).length;
      return `<th class="col-project">${esc(p.name)}<small>${withAccess} with access</small></th>`;
    }).join('');

  document.getElementById('matrix-rows').innerHTML = rows.map((u) => `
    <tr${u.active ? '' : ' class="is-disabled"'}>
      <td class="cell-user">
        <button class="name-btn" type="button" data-open="${esc(u.username)}">${esc(u.name)}</button>
        <div class="cell-sub">${esc(u.username)}${u.active ? '' : ' · disabled'}</div>
      </td>
      ${columns.map((p) => {
        const role = accessFor(u, p.slug);
        return `<td class="cell-role">
          <button class="cell-btn" type="button" data-cell="${esc(u.username)}:${esc(p.slug)}"
                  aria-label="${esc(u.name)} on ${esc(p.name)}: ${role ? ROLE_LABEL[role] : 'no access'}">
            ${roleChip(role)}
          </button></td>`;
      }).join('')}
    </tr>`).join('');

  document.querySelectorAll('#matrix-rows [data-open]').forEach((el) => {
    el.onclick = () => openDrawer(el.dataset.open);
  });
  document.querySelectorAll('#matrix-rows [data-cell]').forEach((el) => {
    el.onclick = (event) => { event.stopPropagation(); openRolePopover(el); };
  });
}

function openRolePopover(anchor) {
  closePopover();
  const [username, slug] = anchor.dataset.cell.split(':');
  const account = state.users.find((u) => u.username === username);
  const current = accessFor(account, slug);

  const popover = document.createElement('div');
  popover.className = 'popover';
  popover.innerHTML =
    `<div class="popover-title">${esc(project(slug).name)}</div>` +
    [...ROLES].reverse().map((r) =>
      `<button class="popover-option" type="button" role="menuitemradio" aria-checked="${current === r}" data-role="${r}">
         <span class="tick">${current === r ? '✓' : ''}</span>${ROLE_LABEL[r]}</button>`).join('') +
    '<div class="popover-sep"></div>' +
    `<button class="popover-option" type="button" role="menuitemradio" aria-checked="${!current}" data-role="">
       <span class="tick">${!current ? '✓' : ''}</span>No access</button>`;

  document.body.appendChild(popover);
  const box = anchor.getBoundingClientRect();
  popover.style.top = `${window.scrollY + box.bottom + 4}px`;
  popover.style.left = `${Math.min(
    window.scrollX + box.left,
    window.scrollX + document.documentElement.clientWidth - popover.offsetWidth - 12,
  )}px`;

  popover.querySelectorAll('[data-role]').forEach((option) => {
    option.onclick = async () => {
      const next = option.dataset.role;
      closePopover();
      const result = next
        ? await setRole(username, slug, next)
        : await revokeRole(username, slug);
      if (!result.ok) { toast(result.message); return; }
      await loadUsers();
      renderMatrix();
      toast(next
        ? `${account.name} is now ${ROLE_LABEL[next]} on ${project(slug).name}.`
        : `${account.name} lost access to ${project(slug).name}.`);
    };
  });
  popover.querySelector('.popover-option').focus();
}

function exportCsv() {
  const { columns, rows } = visible();
  const cell = (value) => `"${String(value ?? '').replace(/"/g, '""')}"`;
  const lines = [['Username', 'Name', ...columns.map((p) => p.name)].map(cell).join(',')];
  rows.forEach((u) => {
    lines.push([u.username, u.name, ...columns.map((p) => accessFor(u, p.slug) || '')].map(cell).join(','));
  });
  const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'cplan-access-matrix.csv';
  link.click();
  URL.revokeObjectURL(url);
}

export function wireMatrix() {
  document.getElementById('matrix-filter-project').innerHTML =
    '<option value="">All projects</option>';
  ['matrix-search', 'matrix-filter-project'].forEach((id) => {
    document.getElementById(id).oninput = renderMatrix;
  });
  document.getElementById('matrix-export').onclick = exportCsv;   // labelled "Export as CSV"
  document.addEventListener('click', (event) => {
    if (!event.target.closest('.popover') && !event.target.closest('[data-cell]')) closePopover();
  });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closePopover(); });
}
