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

/* Used to live verbatim in both drawer.js (reset password) and invite.js
   (initial password): one home for it now. Its word list and shape are a
   separate decision the owner is making elsewhere -- do not change them here. */
export function generatePassword() {
  const words = ['anchor', 'harbour', 'lantern', 'meadow', 'compass', 'basalt', 'willow', 'quarry'];
  const pick = () => words[Math.floor(Math.random() * words.length)];
  return `${pick()}-${pick()}-${Math.floor(10 + Math.random() * 89)}`;
}

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
// toast() used to take an (unused) `undo` callback and a permanently dead
// #toast-undo button -- no caller ever passed one. Removed rather than wired
// up: the drawer's own comment on destructive actions is explicit that a
// toast is not meant to be the recovery path for those, and no other action
// here has a genuine, safe "undo" (a role change already goes through a
// confirmable, re-visitable popover). If a real undo-able action shows up
// later, reintroduce the parameter then.
export function toast(message) {
  const el = document.getElementById('toast');
  document.getElementById('toast-text').textContent = message;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 4000);
}

/* Layered overlays (matrix role popover, person drawer, invite modal) each
   used to install their own document-level Escape listener, so Escape inside
   the invite modal also closed the drawer sitting behind it. One shared
   stack instead: every opener pushes its own close callback, and Escape only
   ever invokes the top of the stack. A close path that isn't Escape (a
   Cancel button, a backdrop click, a completed action) must still call
   popLayer with the same token so the stack does not think a closed layer is
   still open. */
const layerStack = [];

export function pushLayer(close) {
  const token = {};
  layerStack.push({ token, close });
  return token;
}

export function popLayer(token) {
  const index = layerStack.findIndex((layer) => layer.token === token);
  if (index !== -1) layerStack.splice(index, 1);
}

document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  const top = layerStack[layerStack.length - 1];
  if (top) top.close();
});
