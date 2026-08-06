/* Project tiles. A tile opens the project's own page, in this tab -- not the
   workspace in a new one. That page is where the manual, the technical
   documentation, data provenance, access and the generated reports live, and
   it carries its own application tile that opens the workspace (project.js,
   target="_blank" + rel="noopener"). Linking a home tile straight at the
   workspace made those six resources reachable only by typing /project/{slug}
   by hand, which nothing anywhere tells anyone to do. */
import { fetchProjects } from './api.js';
import { state } from './state.js';
import { esc, roleChip, toast } from './ui.js';

export async function loadHome() {
  const projects = await fetchProjects();
  state.projectsLoadFailed = projects === null;
  state.projects = projects || [];
  if (state.projectsLoadFailed) toast('Could not load your projects. Check your connection and try again.');
}

export function renderHome() {
  const tiles = document.getElementById('project-tiles');
  if (state.projectsLoadFailed) {
    tiles.innerHTML =
      '<div class="empty"><p class="empty-title">Could not load projects.</p>' +
      '<p class="empty-text">Something went wrong reaching the server. Try refreshing the page.</p></div>';
    return;
  }
  if (!state.projects.length) {
    tiles.innerHTML =
      '<div class="empty"><p class="empty-title">No projects yet.</p>' +
      '<p class="empty-text">You do not have access to any project. Ask a portal administrator.</p></div>';
    return;
  }
  tiles.innerHTML = state.projects.map((p) => `
    <a class="tile" href="/project/${esc(p.slug)}">
      <div class="tile-head">${logoMark(p)}<div class="tile-name">${esc(p.name)}</div></div>
      <div class="tile-purpose">${esc(p.purpose || '')}</div>
      <div class="tile-foot">${roleChip(p.role)}<span class="tile-open">Open →</span></div>
    </a>`).join('');
}

/* A project's own mark, when it publishes one. alt="" on purpose: the name it
   sits beside says the same thing, so a screen reader announcing both would
   read the project twice. A project with no logo contributes nothing, leaving
   the head exactly the name it has always been. */
function logoMark(p) {
  if (!p.logo) return '';
  return `<img class="tile-logo" src="${esc(p.logo)}" alt="" />`;
}
