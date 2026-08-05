/* Boot and navigation. Every render module owns one page and is called from here. */
import { getSession, signIn, signOut } from './api.js';
import { state } from './state.js';
import { renderHome, loadHome } from './home.js';
import { renderUsers, loadUsers, wireUsers } from './users.js';
import { renderMatrix, wireMatrix } from './matrix.js';
import { wireDrawer } from './drawer.js';
import { wireInvite } from './invite.js';

export function show(page) {
  state.page = page;
  document.querySelectorAll('.nav-item').forEach((b) => b.classList.toggle('active', b.dataset.page === page));
  document.querySelectorAll('.page').forEach((p) => p.classList.toggle('active', p.id === `page-${page}`));
  document.querySelectorAll('.popover').forEach((p) => p.remove());
}

async function enterApp() {
  document.getElementById('screen-signin').hidden = true;
  document.getElementById('screen-app').hidden = false;
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
  if (ok) await enterApp();
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
if (session) { await enterApp(); } else { showSignIn(); }
