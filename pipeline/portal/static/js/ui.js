/* Shared render helpers. The role chip is a grey density ramp: the heavier the
   fill, the more the role can do, so the matrix reads without colour-coding
   text (which the design system forbids).

   initials() lives here and only here: it used to be written out separately
   in app.js and project.js. app.js now imports it from this module.
   project.js keeps its own copy -- it is a plain (non-module) script and
   cannot import an ES module -- with a comment noting the duplication is
   deliberate. */
import { ROLE_LABEL, statusOf, formatSignIn } from './state.js';

export const esc = (value) =>
  String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export const initials = (name) => name.split(/[\s.]+/).filter(Boolean).map((p) => p[0]).join('').slice(0, 2).toUpperCase();

export const roleChip = (role) =>
  role ? `<span class="role role-${role}">${ROLE_LABEL[role]}</span>` : '<span class="role role-none">—</span>';

export function statusCell(account) {
  const status = statusOf(account);
  const label = { active: 'Active', disabled: 'Disabled', pending: 'Never signed in' }[status];
  return `<span class="status ${status}"><span class="status-dot"></span>${label}</span>`;
}

export const signInLabel = formatSignIn;

export function closePopover() {
  document.querySelectorAll('.popover').forEach((p) => p.remove());
}

let toastTimer = null;
export function toast(message, undo) {
  const el = document.getElementById('toast');
  document.getElementById('toast-text').textContent = message;
  const undoButton = document.getElementById('toast-undo');
  undoButton.hidden = !undo;
  undoButton.onclick = () => { if (undo) undo(); el.classList.remove('show'); };
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 4000);
}
