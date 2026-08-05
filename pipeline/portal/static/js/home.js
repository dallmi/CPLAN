/* Project tiles. target="_blank" so the workspace opens in its own tab and the
   portal stays put; rel="noopener" severs the reverse window handle. */
import { fetchProjects } from './api.js';
import { state } from './state.js';
import { esc, roleChip } from './ui.js';

export async function loadHome() {
  state.projects = await fetchProjects();
}

export function renderHome() {
  const tiles = document.getElementById('project-tiles');
  if (!state.projects.length) {
    tiles.innerHTML =
      '<div class="empty"><p class="empty-title">No projects yet.</p>' +
      '<p class="empty-text">You do not have access to any project. Ask a portal administrator.</p></div>';
    return;
  }
  tiles.innerHTML = state.projects.map((p) => `
    <a class="tile" href="${esc(p.url)}" target="_blank" rel="noopener">
      <div class="tile-name">${esc(p.name)}</div>
      <div class="tile-purpose">${esc(p.purpose || '')}</div>
      <div class="tile-foot">${roleChip(p.role)}<span class="tile-open">Open →</span></div>
    </a>`).join('');
}
