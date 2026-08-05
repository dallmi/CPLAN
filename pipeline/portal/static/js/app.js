/* Boot and navigation. Every render module owns one page and is called from here. */
import { getSession, signIn, signOut } from './api.js';
import { state } from './state.js';
import { initials } from './ui.js';
import { renderHome, loadHome } from './home.js';
import { renderUsers, loadUsers, wireUsers } from './users.js';
import { renderMatrix, wireMatrix } from './matrix.js';
import { wireDrawer } from './drawer.js';
import { wireInvite } from './invite.js';

// Not exported: nothing outside this module calls navigation directly, and
// exporting it invited a caller to bypass the nav buttons' own state.
function show(page) {
  state.page = page;
  document.querySelectorAll('.nav-item').forEach((b) => b.classList.toggle('active', b.dataset.page === page));
  document.querySelectorAll('.page').forEach((p) => p.classList.toggle('active', p.id === `page-${page}`));
  document.querySelectorAll('.popover').forEach((p) => p.remove());
}

function capitalize(word) {
  return word ? word.charAt(0).toUpperCase() + word.slice(1) : '';
}

function paintUserChip(session) {
  document.getElementById('user-chip-avatar').textContent = initials(session.username);
  document.getElementById('user-chip-name').textContent = session.username;
  document.getElementById('user-chip-role').textContent = capitalize(session.role);
}

async function enterApp(session) {
  document.getElementById('screen-signin').hidden = true;
  document.getElementById('screen-app').hidden = false;
  paintUserChip(session);
  await Promise.all([loadHome(), loadUsers()]);
  renderHome();
  renderUsers();
  renderMatrix();
  show('home');
}

function showSignIn() {
  document.getElementById('screen-app').hidden = true;
  document.getElementById('screen-signin').hidden = false;
}

document.querySelectorAll('.nav-item').forEach((b) => { b.onclick = () => show(b.dataset.page); });

document.getElementById('signin-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const ok = await signIn(
    document.getElementById('si-user').value.trim(),
    document.getElementById('si-pass').value,
  );
  document.getElementById('si-error').hidden = ok;
  if (ok) await enterApp(await getSession());
});

document.getElementById('sign-out').addEventListener('click', async () => {
  await signOut();
  window.location.reload();
});

wireUsers();
wireMatrix();
wireDrawer();
wireInvite();

const session = await getSession();
if (session) { await enterApp(session); } else { showSignIn(); }
