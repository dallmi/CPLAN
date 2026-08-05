/* One person's account and access in one place. Destructive steps confirm
   first: unlike a role change, disabling an account and removing every grant
   are not something a toast-undo should be the only guard for.

   accessFor() returns a direct role or null for every project -- every grant
   shown here is direct, with nothing else to attribute it to. */
import { resetPassword, setActive, revokeRole } from './api.js';
import { state, accessFor } from './state.js';
import { esc, initials, roleChip, statusCell, signInLabel, toast } from './ui.js';

function generatePassword() {
  const words = ['anchor', 'harbour', 'lantern', 'meadow', 'compass', 'basalt', 'willow', 'quarry'];
  const pick = () => words[Math.floor(Math.random() * words.length)];
  return `${pick()}-${pick()}-${Math.floor(10 + Math.random() * 89)}`;
}

export function openDrawer(username) {
  const account = state.users.find((u) => u.username === username);
  if (!account) return;

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
  document.getElementById('person-drawer').classList.add('open');
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
    for (const slug of slugs) {
      const result = await revokeRole(account.username, slug);
      if (!result.ok) { toast(result.message); return; }
    }
    await refresh();
    toast(`All access removed for ${account.name}.`);
  }
}

export function closeDrawer() {
  document.getElementById('person-drawer').classList.remove('open');
}

export function wireDrawer() {
  document.querySelectorAll('[data-close-drawer]').forEach((b) => { b.onclick = closeDrawer; });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeDrawer(); });
}
