/* One person's account and access in one place. Destructive steps confirm
   first: unlike a role change, disabling an account and removing every grant
   are not something a toast-undo should be the only guard for.

   Phase 1 scope: groups do not exist yet. accessFor() returns a direct role
   or null for every project -- there is no inherited-from-a-group case, so
   this drawer has no Groups section and no per-group "Remove" button. */
import { resetPassword, setActive, revokeRole } from './api.js';
import { state, accessFor, project } from './state.js';
import { esc, initials, roleChip, statusCell, signInLabel, toast, generatePassword, pushLayer, popLayer } from './ui.js';

// The row button behind the scrim otherwise keeps focus while the drawer
// covers it, and closing had nowhere to send focus back to. Recorded only
// the first time the drawer opens -- runAction() re-opens the same drawer
// after a mutation to refresh its contents, and that reopen must not forget
// the original trigger or push a second layer onto the stack.
let drawerLayerToken = null;
let drawerTrigger = null;

export function openDrawer(username) {
  const account = state.users.find((u) => u.username === username);
  if (!account) return;

  const panel = document.getElementById('person-drawer');
  const wasOpen = panel.classList.contains('open');

  document.getElementById('drawer-avatar').textContent = initials(account.name);
  document.getElementById('drawer-name').textContent = account.name;
  document.getElementById('drawer-meta').textContent =
    `${account.username} · last sign-in ${signInLabel(account.lastSignIn)}`;

  document.getElementById('drawer-body').innerHTML = `
    <div class="drawer-section">
      <h3>Account</h3>
      <div class="access-row">
        <div><div class="access-project">Status</div>
             <div class="access-note">${account.active ? 'Can sign in' : 'Cannot sign in'}</div></div>
        ${statusCell(account)}
      </div>
      <div class="access-row">
        <div><div class="access-project">Password</div>
             <div class="access-note">Set by an administrator</div></div>
        <button class="btn sm" type="button" data-act="reset">Reset password</button>
      </div>
    </div>

    <div class="drawer-section">
      <h3>Project access</h3>
      ${state.projects.map((p) => {
        const role = accessFor(account, p.slug);
        return `<div class="access-row">
          <div><div class="access-project">${esc(p.name)}</div>
               <div class="access-note">${role ? 'Direct grant' : 'No access'}</div></div>
          ${roleChip(role)}
        </div>`;
      }).join('')}
    </div>

    <div class="drawer-section">
      <h3>Danger zone</h3>
      <div class="drawer-danger">
        <button class="btn danger" type="button" data-act="${account.active ? 'disable' : 'enable'}">
          ${account.active ? 'Disable account' : 'Enable account'}</button>
        <button class="btn danger" type="button" data-act="remove">Remove all access</button>
      </div>
      <p class="footnote" style="margin-top:12px">Disabling keeps the account and its grants but blocks sign-in.
      Nothing this person created is deleted.</p>
    </div>`;

  document.getElementById('drawer-body').querySelectorAll('[data-act]').forEach((button) => {
    button.onclick = () => runAction(button.dataset.act, account);
  });
  panel.classList.add('open');

  if (!wasOpen) {
    drawerTrigger = document.activeElement;
    drawerLayerToken = pushLayer(closeDrawer);
  }
  document.querySelector('#person-drawer [data-close-drawer].icon-btn').focus();
}

async function runAction(action, account) {
  const { loadUsers, renderUsers } = await import('./users.js');
  const { renderMatrix } = await import('./matrix.js');
  const refresh = async () => {
    await loadUsers();
    renderUsers();
    renderMatrix();
    openDrawer(account.username);
  };

  if (action === 'reset') {
    const password = generatePassword();
    if (!window.confirm(`Reset ${account.name}'s password to:\n\n${password}\n\nPass it on yourself — the portal sends no email.`)) return;
    const result = await resetPassword(account.username, password);
    toast(result.ok ? `Password reset for ${account.name}.` : result.message);
    return;
  }

  if (action === 'disable' || action === 'enable') {
    const disabling = action === 'disable';
    if (disabling && !window.confirm(`Disable ${account.name}? They will not be able to sign in.`)) return;
    const result = await setActive(account.username, !disabling);
    if (!result.ok) { toast(result.message); return; }
    await refresh();
    toast(`${account.name} ${disabling ? 'can no longer sign in' : 'can sign in again'}.`);
    return;
  }

  if (action === 'remove') {
    const slugs = Object.keys(account.grants);
    if (!slugs.length) { toast(`${account.name} has no access to remove.`); return; }
    if (!window.confirm(`Remove ${account.name} from all ${slugs.length} project(s)? The account itself stays.`)) return;

    // Sequential and deliberate: a failure stops the loop rather than firing
    // every remaining revoke. But whatever already succeeded is now real on
    // the server, so the UI must be refreshed -- and the message must say
    // what actually happened -- whether the loop ran to completion or not.
    const removedNames = [];
    let failure = null;
    for (const slug of slugs) {
      const result = await revokeRole(account.username, slug);
      if (!result.ok) { failure = result; break; }
      removedNames.push(project(slug)?.name || slug);
    }
    await refresh();
    if (failure) {
      toast(removedNames.length
        ? `Removed ${account.name} from ${removedNames.join(', ')}, then stopped: ${failure.message}`
        : failure.message);
      return;
    }
    toast(`All access removed for ${account.name}.`);
  }
}

export function closeDrawer() {
  document.getElementById('person-drawer').classList.remove('open');
  if (drawerLayerToken) { popLayer(drawerLayerToken); drawerLayerToken = null; }
  if (drawerTrigger && typeof drawerTrigger.focus === 'function') drawerTrigger.focus();
  drawerTrigger = null;
}

export function wireDrawer() {
  document.querySelectorAll('[data-close-drawer]').forEach((b) => { b.onclick = closeDrawer; });
}
