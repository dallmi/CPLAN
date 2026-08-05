/* Account creation. The password is generated and shown once — the portal sends
   no email, so the admin passes it on. The role picker explains each role in a
   sentence rather than offering four bare words in a dropdown.

   Phase 1 scope: groups do not exist. This form grants exactly one project and
   one role at a time; additional access is added afterwards from the matrix. */
import { createUser } from './api.js';
import { state, ROLES, ROLE_LABEL, ROLE_DESC, project } from './state.js';
import { esc, toast, generatePassword, pushLayer, popLayer } from './ui.js';

// The modal moved focus in on open but never gave it back on close. Recorded
// on open, restored on every close path (Cancel, backdrop, Escape, or a
// completed submit).
let inviteLayerToken = null;
let inviteTrigger = null;

// The matrix encodes a grant as `username:slug` in a data-cell attribute and
// splits it on ':' (matrix.js openRolePopover). A username containing a colon
// would silently break that lookup, so the charset is restricted to what a
// system identifier needs: letters, digits, dot, hyphen, underscore. The
// server enforces the same pattern (CreateUserPayload in pipeline/portal/app.py)
// so this check is a courtesy that fails fast, not the only guard.
const USERNAME_PATTERN = /^[A-Za-z0-9._-]+$/;
const USERNAME_HELP = 'Letters, numbers, dot, hyphen and underscore only.';

export function openInvite() {
  document.getElementById('iv-username').value = '';
  document.getElementById('iv-password').value = generatePassword();
  document.getElementById('iv-error').hidden = true;
  document.getElementById('iv-project').innerHTML =
    state.projects.map((p) => `<option value="${esc(p.slug)}">${esc(p.name)}</option>`).join('');
  document.getElementById('iv-roles').innerHTML = [...ROLES].reverse().map((r, index) => `
    <label class="role-choice">
      <input type="radio" name="iv-role" value="${r}"${index === ROLES.length - 1 ? ' checked' : ''} />
      <span><span class="rc-name">${ROLE_LABEL[r]}</span><span class="rc-desc">${esc(ROLE_DESC[r])}</span></span>
    </label>`).join('');
  document.getElementById('invite-modal').classList.add('open');
  inviteTrigger = document.activeElement;
  inviteLayerToken = pushLayer(closeInvite);
  document.getElementById('iv-username').focus();
}

export function closeInvite() {
  document.getElementById('invite-modal').classList.remove('open');
  if (inviteLayerToken) { popLayer(inviteLayerToken); inviteLayerToken = null; }
  if (inviteTrigger && typeof inviteTrigger.focus === 'function') inviteTrigger.focus();
  inviteTrigger = null;
}

export function wireInvite() {
  document.getElementById('invite-open').onclick = openInvite;
  document.getElementById('iv-generate').onclick = () => {
    document.getElementById('iv-password').value = generatePassword();
  };
  document.querySelectorAll('[data-close-modal]').forEach((b) => { b.onclick = closeInvite; });

  document.getElementById('invite-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const error = document.getElementById('iv-error');
    const username = document.getElementById('iv-username').value.trim();
    if (!username) {
      error.textContent = 'Choose a username.';
      error.hidden = false;
      return;
    }
    if (!USERNAME_PATTERN.test(username)) {
      error.textContent = USERNAME_HELP;
      error.hidden = false;
      return;
    }
    const slug = document.getElementById('iv-project').value;
    const role = document.querySelector('input[name="iv-role"]:checked').value;
    const result = await createUser({
      username,
      password: document.getElementById('iv-password').value,
      project: slug,
      role,
    });
    if (!result.ok) {
      error.textContent = result.message;
      error.hidden = false;
      return;
    }
    closeInvite();
    const { loadUsers, renderUsers } = await import('./users.js');
    const { renderMatrix } = await import('./matrix.js');
    await loadUsers();
    renderUsers();
    renderMatrix();
    toast(`${username} created as ${ROLE_LABEL[role]} on ${project(slug).name}.`);
  });
}
