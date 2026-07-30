(() => {
  'use strict';

  const A = window.CplanAnalytics;
  const COLORS = {grey:'#404040', bronze:'#B98E2C'};

  const state = {snapshotRows:[], rows:[], meta:null, syncRun:null, horizonWeeks:8, boardGroup:'channel', trendMode:'', calendarDate:new Date(), selected:null, editing:false, creating:false, packing:false, customChannels:[], dirty:false, showErrors:false, filteredRows:[], drawerOpener:null, discardModalOpen:false, draftModalOpen:false, deleteModalOpen:false, queueFilter:null, dateFrom:null, dateTo:null, packDrawerOpener:null};

  // Sentinel for the campaign filter -- the empty value already means "all",
  // so the absence needs a value of its own. Plain text, not a control
  // character: it is written into a DOM attribute and read back out.
  const NO_PACK = '__no_pack__';

  const esc = A.escapeHtml;
  const fmtNum = value => Number(value || 0).toLocaleString('en-GB');
  // "1 activities", "the 1 days before" -- a portfolio of one is a real state
  // (a new deployment, a narrow filter) and it read as a bug in three places at
  // once. Formats the count and agrees the noun in one call; the plural form
  // defaults to singular + "s".
  const plural = (count, one, many) => `${fmtNum(count)} ${Number(count)===1?one:(many||one+'s')}`;
  const fmtDate = value => {
    const date = A.parseDate(value);
    return date ? date.toLocaleDateString('en-GB',{day:'2-digit',month:'short',year:'numeric'}) : '—';
  };
  const fmtDateTime = value => {
    const date = A.parseDate(value);
    return date ? date.toLocaleString('en-GB',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}) : '—';
  };
  const isoLocal = value => {
    const date = A.parseDate(value);
    if (!date) return '';
    const offset = date.getTimezoneOffset() * 60000;
    return new Date(date.getTime() - offset).toISOString().slice(0,16);
  };
  const nonempty = value => value !== null && value !== undefined && String(value).trim() && value !== 'None' && value !== 'null';
  const split = value => A.normalizeMulti(value);
  const STANDALONE_PACK_PREFIX = 'STA-0000000';
  const campaignLabel = row => {
    const candidates = [row.campaign, row.communication_pack, row.tracking_pack_id];
    const found = candidates.find(value => nonempty(value) && value !== STANDALONE_PACK_PREFIX);
    return found || null;
  };

  // Tracking ID identity element: CLUSTER-PACKNUM-YYMMDD-ACTNUM-CHANNEL.
  // The invariant pack prefix is de-emphasised; date, sequence and channel stay
  // legible — the ID is the link between planning and downstream outcome data.
  const TRACKING_ID_RE = /^([A-Z0-9]+-[0-9]+)-(\d{6})-(\d+)-([A-Z]+)$/;
  const TRACKING_ID_TITLE = 'CLUSTER-PACKNUM-YYMMDD-ACTNUM-CHANNEL — pack prefix · start date · global sequence · channel code';

  // Two offset sheets -- the one glyph everybody reads as "copy". Drawn at 13px
  // on a 24px button so the target clears the minimum while the mark stays
  // quiet next to an 10px identifier.
  const COPY_ICON = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="1"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/></svg>';

  function trackingIdHtml(id, options) {
    const opts = options || {};
    if (!nonempty(id)) return '<span class="tracking-id">—</span>';
    const match = TRACKING_ID_RE.exec(String(id));
    const inner = match
      ? `<span class="tid-prefix">${esc(match[1])}-</span><span class="tid-date">${esc(match[2])}</span>-<span class="tid-seq">${esc(match[3])}</span>-<span class="tid-channel">${esc(match[4])}</span>`
      : esc(String(id));
    // Icon, not the word. "Copy" set beside a tracking ID reads as part of the
    // identifier -- in the pack drawer, where a card shows one ID and nothing
    // else on that line, the label sat closer to the last character of the ID
    // than to its own border. The glyph is universally understood for this one
    // action, and dropping the word buys the spacing the control needed.
    // aria-label carries the name the visible text no longer does.
    const copy = opts.copy ? `<button type="button" class="copy-btn" data-copy-id="${esc(String(id))}" aria-label="Copy tracking ID" title="Copy tracking ID">${COPY_ICON}</button>` : '';
    return `<span class="tracking-id" title="${esc(TRACKING_ID_TITLE)}">${inner}</span>${copy}`;
  }

  // Approximates the server's channel-abbreviation majority vote for live ID
  // stubs in the pack drawer: most common abbreviation already minted for this
  // channel, else the first three alphabetic characters, else GEN.
  function channelAbbr(channel) {
    const counts = new Map();
    state.snapshotRows.forEach(row => {
      if (String(row.channel || '') !== String(channel)) return;
      const match = TRACKING_ID_RE.exec(String(row.tracking_id || ''));
      if (match) counts.set(match[4], (counts.get(match[4]) || 0) + 1);
    });
    const winner = Array.from(counts.entries()).sort((a, b) => b[1] - a[1])[0];
    if (winner) return winner[0];
    const alpha = String(channel || '').replace(/[^a-zA-Z]/g, '').slice(0, 3).toUpperCase();
    return alpha.length >= 2 ? alpha : 'GEN';
  }

  function packIdPrefix() {
    const cpid = String(form().elements.communication_pack_cpid.value || '').trim();
    return /^[A-Z0-9]+-[0-9]+$/.test(cpid) ? cpid : STANDALONE_PACK_PREFIX;
  }

  const stubDate = value => {
    const date = A.parseDate(value);
    return date ? `${String(date.getFullYear()).slice(2)}${String(date.getMonth() + 1).padStart(2, '0')}${String(date.getDate()).padStart(2, '0')}` : '……';
  };

  // --- Priority donut -----------------------------------------------------
  // Restored after being removed on 2026-07-29. That removal was reasoned from
  // the demo portfolio, where the three priority levels sat at 35/34/31% -- as
  // near to equal as makes no difference, and a ring of three equal thirds says
  // nothing. Production is not shaped like that at all: roughly 65/18/16/1
  // across four levels, so the ring shows at a glance that the genuinely urgent
  // work is a small, identifiable slice of a very large pool. Same chart, and
  // the argument for dropping it simply did not survive the real data.

function donutHtml(entries, colorOf, centerText, centerSub) {
    if (!entries.length) return emptyState(EMPTY_ICONS.barChart, 'No data available', 'Nothing to show for the current selection.');
    const total = entries.reduce((sum, [, count]) => sum + count, 0);
    const shown = entries.slice(0, 8);
    const r = 56, cx = 70, cy = 70, circ = 2 * Math.PI * r, gap = shown.length > 1 ? 2.5 : 0;
    let offset = -circ / 4;
    const segments = shown.map(([label, count], i) => {
      const len = count / total * circ;
      const seg = `<circle r="${r}" cx="${cx}" cy="${cy}" fill="none" stroke="${colorOf(label, i)}" stroke-width="16" stroke-dasharray="${Math.max(len - gap, 0.5)} ${circ - Math.max(len - gap, 0.5)}" stroke-dashoffset="${-offset}"><title>${esc(label)} — ${fmtNum(count)}</title></circle>`;
      offset += len;
      return seg;
    }).join('');
    const legend = shown.map(([label, count], i) => `<div class="legend-row"><span class="swatch" style="background:${colorOf(label, i)}"></span>${esc(label)} — ${fmtNum(count)} (${Math.round(count / total * 100)}%)</div>`).join('');
    const rest = entries.length > shown.length ? `<div class="legend-row"><span class="swatch" style="background:var(--grey-1)"></span>+${entries.length - shown.length} more</div>` : '';
    const center = (centerText === undefined || centerText === null) ? fmtNum(total) : centerText;
    const subSvg = centerSub ? `<text x="${cx}" y="${cy + 20}" text-anchor="middle" font-size="9" fill="var(--grey-4)">${esc(centerSub)}</text>` : '';
    const centerSvg = center === '' ? '' : `<text x="${cx}" y="${cy + (centerSub ? 2 : 8)}" text-anchor="middle" class="donut-center" font-size="26" font-weight="300">${center}</text>` + subSvg;
    return `<div class="donut-wrap"><svg class="donut-svg" width="140" height="140" viewBox="0 0 140 140" role="img">${segments}${centerSvg}</svg><div class="donut-legend">${legend}${rest}</div></div>`;
  }

  // Ordered and coloured by rank, never alphabetically and never by size. The
  // source system's labels sort "1 - ..." before "4 - ..." by luck, the
  // studio's own words do not sort meaningfully at all, and either way the
  // reader is looking for the urgent slice -- so the most urgent level leads
  // the legend and carries the strongest colour. Bordeaux for the top level,
  // then bronze, then greys: the ramp is the studio's own, and weight falls
  // with urgency rather than with share.
  const PRIORITY_RAMP = ['#8A000A', '#B98E2C', '#7A7870', '#CCCABC'];
  function priorityEntries(rows) {
    const counts = new Map();
    rows.forEach(row => {
      const value = nonempty(row.priority) ? String(row.priority).trim() : 'No priority';
      counts.set(value, (counts.get(value) || 0) + 1);
    });
    return Array.from(counts.entries()).sort((a, b) => {
      const rank = A.priorityRank(b[0]) - A.priorityRank(a[0]);
      return rank || b[1] - a[1];
    });
  }
  function priorityColor(label) {
    const rank = A.priorityRank(label);
    // rank 4 (most urgent) -> index 0. Anything unrecognised lands mid-ramp
    // rather than borrowing the top colour.
    return PRIORITY_RAMP[Math.min(PRIORITY_RAMP.length - 1, Math.max(0, 4 - rank))];
  }

  // --- Division donut -----------------------------------------------------
  // Greys and bronzes, deliberately no bordeaux: a division is a category, not
  // a severity, and the studio's red is spoken for. Ordered by distance rather
  // than by family, alternating light and dark, so two divisions landing next
  // to each other in the ring never land on two shades of the same brown.
  //
  // grey-1 (#CCCABC) is missing from the sequence on purpose -- it is the
  // unassigned slice's colour below. It used to sit fourth here, which on the
  // four-division portfolio painted the last division and "No division" the
  // same shade, as two adjacent segments of one ring.
  const DONUT_SEQUENCE = ['#404040', '#B98E2C', '#8E8D83', '#6C5312', '#B8B3A2', '#5A5D5C', '#946F29'];
  const NO_DIVISION = 'No division';
  // business_division is multi-valued, so this counts MENTIONS: an activity
  // naming two divisions is one mention of each, and the ring's total is
  // therefore not the activity count. The centre says "mentions" and the card
  // head says why -- without that, two rings on one page invite a comparison
  // that does not hold.
  //
  // Rows carrying no division get their own slice rather than vanishing.
  // normalizeMulti drops empties, so the old chart quietly excluded them and
  // its percentages described only the assigned part of the portfolio.
  // business_division is required for internal activities but not external
  // ones, so the slice is a real answer -- "this much of the portfolio does not
  // name one" -- and it sits last on a flat grey, out of the sequence, because
  // it is the absence of a division rather than one more division.
  function divisionEntries(rows) {
    const named = countBy(rows, 'business_division');
    const none = rows.filter(row => !split(row.business_division).length).length;
    return none ? named.concat([[NO_DIVISION, none]]) : named;
  }
  function divisionColor(label, index) {
    return label === NO_DIVISION ? 'var(--grey-1)' : DONUT_SEQUENCE[index % DONUT_SEQUENCE.length];
  }

  function monthlyTrendHtml(rows) {
    const buckets = new Map();
    rows.forEach(row => {
      const date = A.parseDate(row.start_date);
      if (!date) return;
      const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
      const bucket = buckets.get(key) || {internal: 0, external: 0};
      bucket[row.source_type === 'external' ? 'external' : 'internal'] += 1;
      buckets.set(key, bucket);
    });
    const keys = Array.from(buckets.keys()).sort().slice(-18);
    if (!keys.length) return emptyState(EMPTY_ICONS.barChart, 'No dated activities in range', 'Adjust the time filter to see the monthly trend.');
    const totalOf = key => buckets.get(key).internal + buckets.get(key).external;
    const max = Math.max(...keys.map(totalOf), 1);
    const label = key => {
      const [y, m] = key.split('-');
      return `${['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][Number(m) - 1]} ${y.slice(2)}`;
    };
    // Stacked: internal (grey) at the base, external (bronze) on top — same
    // source-type colours as the timeline/calendar, so the split reads at a
    // glance without cross-referencing the toggle.
    // The falling edge is the single most misread thing on this screen. Every
    // fresh-eyes run asked the same question and none could answer it: is the
    // drop after this month a real decline, or simply planning that has not
    // happened yet? It is the latter, and the chart never said so. Activities
    // are created a median of N days before they start, so the current month
    // and everything after it are still filling and their bars will grow.
    //
    // Marked with a dashed outline, not a lighter colour: the house rule is
    // that colour never carries meaning on its own, and a reader comparing a
    // pale bar to a solid one cannot tell "fewer" from "not yet counted".
    const today = new Date();
    const currentKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`;
    const cols = keys.map(key => {
      const bucket = buckets.get(key), total = totalOf(key);
      const filling = key >= currentKey;
      // The split value inside its own segment, but only where it fits. The
      // chart body is 180px less 8px of padding and ~18px for the total label
      // above the stack, so a segment stands (value / max) * 154 pixels tall;
      // a 10px numeral needs about sixteen of them before it starts touching
      // its own edges. Below that the segment stays bare and the tooltip still
      // carries the number -- a clipped or overhanging label would cost more
      // than the value it adds, and the total above the bar is never in doubt.
      const STACK_PX = 154, LABEL_MIN_PX = 16;
      const fits = value => value / max * STACK_PX >= LABEL_MIN_PX;
      const stack = ['external', 'internal'].map(type => bucket[type]
        ? `<div class="trend-seg ${type}" style="height:${bucket[type] / total * 100}%" title="${fmtNum(bucket[type])} ${type}">${fits(bucket[type]) ? `<span class="trend-seg-value">${fmtNum(bucket[type])}</span>` : ''}</div>`
        : '').join('');
      return `<div class="trend-col${filling ? ' filling' : ''}"><span class="trend-value">${fmtNum(total)}</span><div class="trend-stack" style="height:${total / max * 100}%" title="${filling ? 'Still filling' : 'Complete month'}">${stack}</div></div>`;
    }).join('');
    const legend = `<div class="trend-legend"><i class="internal"></i><span>Internal</span><i class="external"></i><span>External</span><i class="filling"></i><span>Still filling</span></div>`;
    const stillFilling = keys.filter(key => key >= currentKey);
    const median = A.leadTimeStats(rows, 7).median;
    // 155 characters of prose reduced to a clause. The dashed outline and the
    // "Still filling" legend entry already carry the warning visually; the note
    // only has to supply the one fact they cannot -- how much growth is still
    // to come. The old wording spent most of its length telling the reader what
    // not to conclude, which the marking had already told them.
    const caption = stillFilling.length
      ? `<p class="trend-note">Dashed bars still fill — activities arrive a median of ${median === null ? 'several' : fmtNum(median)} days before they start.</p>`
      : '';
    return `<div class="trend">${cols}</div><div class="trend-labels">${keys.map(key => `<span class="trend-label${key >= currentKey ? ' filling' : ''}">${label(key)}</span>`).join('')}</div>${legend}${caption}`;
  }

  const AUDIENCE_BANDS = ['< 1000', '1–10k', '10–50k', '50–100k', '> 100k'];
  const MULTISELECT_FIELDS = ['strategic_objectives', 'business_division', 'region'];
  // Single source of truth lives in analytics.js so the dashboard readiness
  // badge / "Drafts" KPI / filter (all via A.planningCompleteness) and this
  // drawer share one variant-aware rule -- never two lists that can disagree.
  const REQUIRED_INTERNAL = A.REQUIRED_INTERNAL;
  const REQUIRED_EXTERNAL = A.REQUIRED_EXTERNAL;
  const FIELD_LABELS = {activity_name:'Activity name', channel:'Channel', priority:'Priority', strategic_objectives:'Communications pillars', activity_description:'Description', target_audience:'Target audience', audience:'Estimated audience size', business_division:'Business division', region:'Region', start_date:'Start date', end_date:'End date', time_zone:'Time zone', lead:'Lead', lead_team:'Lead team', campaign:'Campaign', communication_pack_cpid:'Communication pack', business_area:'Business area', partner_team:'Partner team', news_digest:'News digest', pack_name:'Pack name'};
  const CREATE_FIELDS = ['activity_name', 'activity_description', 'target_audience', 'business_division', 'business_area', 'region', 'channel', 'partner_team', 'lead_team', 'lead', 'start_date', 'end_date', 'time_zone', 'priority', 'strategic_objectives', 'campaign', 'communication_pack_cpid', 'audience'];
  const HISTORY_LIMIT = 30;
  const HISTORY_ACTOR_LABELS = {studio:'You', sync:'Source sync', seed:'Initial import'};

  const apiErrorMessage = (detail, status) => {
    if (Array.isArray(detail)) {
      const joined = detail.map(item => {
        const loc = Array.isArray(item.loc) ? (item.loc[0] === 'body' ? item.loc.slice(1) : item.loc).join('.') : '';
        return loc ? `${loc}: ${item.msg}` : (item.msg || 'Invalid value');
      }).join('; ');
      return joined || `Request failed (${status})`;
    }
    if (detail && typeof detail === 'object') {
      if (detail.code === 'version_conflict') return 'This activity changed since you opened it. Reload and review before saving.';
      if (detail.code === 'invalid_date_range') return 'End date cannot be before start date.';
      if (detail.code === 'invalid_source_field') return detail.message || 'Invalid source field.';
      return detail.message || `Request failed (${status})`;
    }
    if (typeof detail === 'string' && detail) return detail;
    return `Request failed (${status})`;
  };

  // --- session -------------------------------------------------------------
  // state.currentUser: {username, role, auth} — populated by initSession()
  // before any data loads. DatabasePlanningRepository.request() below is the
  // single fetch choke point for every /api/* call the studio makes
  // (activities, health, sync-runs, changes, create/patch/batch), so routing
  // it through apiFetch covers all of them: any 401 re-opens the login
  // overlay instead of surfacing as a normal request error. In legacy mode
  // (no CPLAN_AUTH_SECRET) /api/me returns 200 with auth:false and the
  // overlay never shows.
  async function apiFetch(url, options) {
    const response = await fetch(url, options);
    if (response.status === 401) {
      showLoginOverlay();
      throw new Error('unauthenticated');
    }
    return response;
  }

  function showLoginOverlay() {
    document.getElementById('login-overlay').classList.remove('hidden');
    document.getElementById('login-error').classList.add('hidden');
    // A mid-session 401 (e.g. an expired cookie) must not leave a stale
    // "unauthenticated"/save-error message sitting behind the overlay for
    // the next person to log in and see.
    document.getElementById('form-validation').textContent = '';
    document.getElementById('login-username').focus();
  }

  function hideLoginOverlay() {
    document.getElementById('login-overlay').classList.add('hidden');
    document.getElementById('login-error').classList.add('hidden');
  }

  // --- role gating -----------------------------------------------------
  // Comfort only: Postgres RLS/grants are the authority. A manipulated UI
  // can still call the API directly; the server answers with 403 and the
  // action simply fails (handled at the call sites, e.g. deleteActivity).
  function canCreate() {
    const role = state.currentUser && state.currentUser.role;
    return role === 'contributor' || role === 'editor' || role === 'admin';
  }

  function canEditActivity(activity) {
    const user = state.currentUser;
    if (!user) return false;
    if (user.role === 'editor' || user.role === 'admin') return true;
    return user.role === 'contributor' && Boolean(activity) && activity.created_by === user.username;
  }

  function canDelete() {
    return Boolean(state.currentUser) && state.currentUser.role === 'admin';
  }

  function applyRoleGating() {
    const allowed = canCreate();
    document.getElementById('activity-new').hidden = !allowed;
    document.getElementById('packs-new').hidden = !allowed;
    document.getElementById('overview-new').hidden = !allowed;
  }

  function updateUserChip() {
    const user = state.currentUser;
    const chip = document.getElementById('user-chip');
    if (!user || user.auth !== true) { chip.hidden = true; return; }
    document.getElementById('user-chip-name').textContent = `${user.username} · ${user.role}`;
    document.getElementById('user-chip-logout').textContent = 'Sign out';
    chip.hidden = false;
  }

  async function initSession() {
    const response = await fetch('/api/me');
    if (response.status === 401) {
      showLoginOverlay();
      return null;
    }
    state.currentUser = await response.json();
    document.body.dataset.role = state.currentUser.role;
    applyRoleGating();
    updateUserChip();
    return state.currentUser;
  }

  async function logout() {
    await fetch('/api/logout', {method:'POST'});
    window.location.reload();
  }

  async function deleteActivity(activityId) {
    const response = await apiFetch(`/api/activities/${encodeURIComponent(activityId)}`, { method: "DELETE" });
    if (response.status === 403) {
      toast('You do not have permission to delete activities.');
      return;
    }
    state.snapshotRows = state.snapshotRows.filter(row => String(row.id) !== String(activityId));
    closeDrawer();
    await loadAndRenderAll();
  }

  class DatabasePlanningRepository {
    async request(path, options) {
      const response = await apiFetch(path, Object.assign({headers:{'Content-Type':'application/json'}}, options || {}));
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        const error = new Error(apiErrorMessage(body.detail, response.status));
        error.status = response.status;
        throw error;
      }
      return body;
    }
    listActivities() { return this.request('/api/activities'); }
    health() { return this.request('/api/health'); }
    latestSyncRun() { return this.request('/api/sync-runs/latest'); }
    getActivityChanges(id) { return this.request(`/api/activities/${encodeURIComponent(id)}/changes`); }
    createActivity(payload) {
      return this.request('/api/activities', {method:'POST',body:JSON.stringify(payload)});
    }
    createActivitiesBatch(items) {
      return this.request('/api/activities/batch', {method:'POST',body:JSON.stringify({items})});
    }
    updateActivity(id, version, patch) {
      return this.request(`/api/activities/${encodeURIComponent(id)}`, {method:'PATCH',body:JSON.stringify(Object.assign({version},patch))});
    }
  }

  window.CplanRepositories = {DatabasePlanningRepository};
  const repository = new DatabasePlanningRepository();
  const backendLabel = () => state.meta&&state.meta.backend==='postgresql'?'PostgreSQL':state.meta&&state.meta.backend==='sqlite'?'SQLite':'Local database';

  // copyValue is optional: when set, the toast grows a "Copy ID" action
  // button (I5/C2 -- create/draft toasts carry the new tracking ID). Clears
  // any pending hide timer so a toast-triggered toast (e.g. clicking Copy)
  // does not get cut short by the first toast's own timeout.
  function toast(message, copyValue) {
    const el = document.getElementById('toast');
    el.textContent = message;
    if (copyValue) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'toast-action';
      btn.textContent = 'Copy ID';
      btn.onclick = () => {
        navigator.clipboard.writeText(copyValue).then(() => toast('Tracking ID copied')).catch(() => toast('Copy failed'));
      };
      el.appendChild(btn);
    }
    el.classList.add('show');
    window.clearTimeout(toast._timer);
    toast._timer = window.setTimeout(() => el.classList.remove('show'), copyValue ? 4000 : 2400);
  }

  function download(name, content, type) {
    // A Blob passes straight through: re-wrapping it would discard the MIME
    // type the builder set, and for .xlsx that type is what stops a browser
    // from filing the download as a generic binary.
    const blob = content instanceof Blob ? content : new Blob([content], {type:type || 'application/octet-stream'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url; link.download = name; link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function loadData() {
    const [result,health] = await Promise.all([repository.listActivities(),repository.health()]);
    return {rows:result.items,meta:{generated_at:new Date().toISOString(),backend:health.database}};
  }

  // Best-effort: the sync-runs endpoint is informational only. A missing endpoint,
  // network failure, or unexpected shape must never take down page init or the
  // rest of the Data Quality page — it just falls back to a "status unavailable"
  // line in the reconciliation card.
  async function loadSyncRun() {
    try {
      return await repository.latestSyncRun();
    } catch (error) {
      return null;
    }
  }

  // Global time filter: rows whose start_date falls outside [dateFrom, dateTo]
  // are excluded everywhere; rows without a parseable start date always pass
  // (they surface as data-quality findings instead of silently vanishing).
  function inTimeRange(row) {
    if (!state.dateFrom && !state.dateTo) return true;
    const date = A.parseDate(row.start_date);
    if (!date) return true;
    if (state.dateFrom && date < state.dateFrom) return false;
    if (state.dateTo && date > state.dateTo) return false;
    return true;
  }

  function refreshRows() {
    state.rows = state.snapshotRows.filter(inTimeRange);
    updateDraftCount();
  }

  function updateDraftCount() {
    const filtered = state.snapshotRows.length !== state.rows.length;
    document.getElementById('overview-as-of').textContent = filtered
      ? `Showing ${fmtNum(state.rows.length)} of ${fmtNum(state.snapshotRows.length)} activities in the selected range`
      : 'Live data across the full portfolio';
  }

  const isoDateInput = date => {
    if (!date) return '';
    const offset = date.getTimezoneOffset() * 60000;
    return new Date(date.getTime() - offset).toISOString().slice(0, 10);
  };

  function applyDatePreset(range) {
    const now = new Date();
    const y = now.getFullYear(), m = now.getMonth(), q = Math.floor(m / 3);
    switch (range) {
      case '30d': state.dateFrom = new Date(y, m, now.getDate() - 30); state.dateTo = endOfDay(now); break;
      case 'quarter': state.dateFrom = new Date(y, q * 3, 1); state.dateTo = new Date(y, q * 3 + 3, 0, 23, 59, 59); break;
      case 'ytd': state.dateFrom = new Date(y, 0, 1); state.dateTo = endOfDay(now); break;
      case '12m': state.dateFrom = new Date(y - 1, m, now.getDate()); state.dateTo = endOfDay(now); break;
      default: state.dateFrom = null; state.dateTo = null; break;
    }
    document.getElementById('date-from').value = isoDateInput(state.dateFrom);
    document.getElementById('date-to').value = isoDateInput(state.dateTo);
  }

  function endOfDay(date) {
    const copy = new Date(date);
    copy.setHours(23, 59, 59, 999);
    return copy;
  }


  function debounce(fn, wait) {
    let timer;
    return (...args) => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => fn(...args), wait);
    };
  }

  const EMPTY_ICONS = {
    checkCircle: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline>',
    calendar: '<rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line>',
    search: '<circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line>',
    layers: '<polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline>',
    barChart: '<line x1="18" y1="20" x2="18" y2="10"></line><line x1="12" y1="20" x2="12" y2="4"></line><line x1="6" y1="20" x2="6" y2="14"></line>',
    alertTriangle: '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line>'
  };

  function emptyState(svgPath, title, subtext) {
    return `<div class="empty"><svg class="empty-icon" viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${svgPath}</svg><strong class="empty-title">${esc(title)}</strong>${subtext?`<p class="empty-subtext">${esc(subtext)}</p>`:''}</div>`;
  }

  // `goto` turns the tile into the route to its own detail. The Overview used to
  // carry four separate jump links under four collection cards; a planner asked
  // for the number and the way to it in one place, so the figure itself is the
  // control. Without a goto the tile stays a plain div -- the analytics pages
  // read as a readout, not a menu, and a button there would promise navigation
  // that does not exist.
  function kpi(label, value, sub, tone, goto, delta) {
    const body = `<span class="kpi-label">${esc(label)}</span><strong class="kpi-value">${esc(value)}${delta||''}</strong><span class="kpi-sub">${esc(sub||'')}</span>`;
    return goto
      ? `<button type="button" class="kpi nav ${tone||''}" data-goto="${esc(goto)}">${body}</button>`
      : `<div class="kpi ${tone||''}">${body}</div>`;
  }

  // Themed collection card: one heading, a stack of figures. Taken from the
  // campaign analytics dashboard, which groups its measures the same way.
  //
  // Display only — no route, no delta. That is the deliberate difference from
  // kpi() above, which is still what the Timeline, Health and Packs pages use.
  function kpiGroup(title, cls, rows) {
    const body = rows.map(r =>
      `<div class="kpi-row${r.derived ? ' derived' : ''}"><span class="v">${esc(r.v)}</span><span class="l">${esc(r.l)}</span></div>`
    ).join('');
    return `<div class="kpi-group ${cls}"><div class="kpi-group-title">${esc(title)}</div>${body}</div>`;
  }

  // Channel colour. Taken from the Campaign Studio prototype, which pairs a
  // small solid square with the channel name so a column of channels can be
  // scanned by shape instead of read line by line.
  //
  // Two constraints the prototype did not have to meet. Its palette covers six
  // channels; the production portfolio carries roughly forty, so colours must
  // repeat -- which is why the name is always rendered beside the square and
  // never replaced by it. The square is an aid to scanning, not an identifier,
  // and nothing on any screen is decodable from colour alone. Second, the
  // palette is house tokens only: bordeaux, bronze and the greys, the same
  // values the prototype drew from.
  //
  // Assignment is by position in the sorted list of channels the portfolio
  // actually uses, so a channel keeps its colour across every screen and across
  // reloads, and adding a channel never reshuffles the others' colours -- it
  // appends. A hash would have been shorter and would have re-coloured the
  // whole table the day someone renamed a channel.
  // Ordered so that consecutive entries are far apart, not so that the palette
  // reads tidily. Sorted alphabetically the local portfolio put Intranet on
  // bronze-1 and Town Hall on bronze-2, two neighbouring browns that a 9px
  // square cannot tell apart. The sequence now alternates family (bordeaux,
  // bronze, grey) and weight (dark, light) so that channels landing next to
  // each other in the list also land far apart in colour.
  const CHANNEL_COLORS = ['#8A000A','#B98E2C','#404040','#8E8D83','#620004','#946F29','#7A7870','#B8B3A2'];
  let channelOrder = [];
  function refreshChannelOrder() {
    channelOrder = Array.from(new Set(state.snapshotRows.flatMap(row=>split(row.channel)))).sort();
  }
  function channelColor(channel) {
    const index = channelOrder.indexOf(String(channel||''));
    return index < 0 ? 'var(--grey-1)' : CHANNEL_COLORS[index % CHANNEL_COLORS.length];
  }
  // aria-hidden: the name sits right next to it, so a screen reader announcing
  // the swatch would only repeat what follows.
  function channelTag(channel) {
    if (!nonempty(channel)) return '<span class="muted">—</span>';
    return `<span class="channel-tag"><i class="channel-dot" style="background:${channelColor(channel)}" aria-hidden="true"></i>${esc(channel)}</span>`;
  }

  function countBy(rows, field) {
    const counts = new Map();
    rows.forEach(row => split(row[field]).forEach(value => counts.set(value,(counts.get(value)||0)+1)));
    return Array.from(counts.entries()).sort((a,b)=>b[1]-a[1]);
  }

  // Like countBy, but the category list comes from `allRows` while the counts
  // come from `windowRows`. A category that exists in the portfolio but has
  // nothing in the forward window is exactly a white spot, and it can only be
  // reported if it survives into the result with a zero.
  //
  // Categories that were never used at all cannot appear here: the entry form
  // builds its dropdowns from the data too, so the studio has no canonical list
  // of channels, regions or audiences to compare against. Anything never used
  // is invisible to this view by construction, not by oversight.
  function countByAgainst(allRows, windowRows, field) {
    const counts = new Map();
    allRows.forEach(row => split(row[field]).forEach(value => counts.set(value, 0)));
    windowRows.forEach(row => split(row[field]).forEach(value => counts.set(value,(counts.get(value)||0)+1)));
    return Array.from(counts.entries()).sort((a,b)=>b[1]-a[1]||String(a[0]).localeCompare(String(b[0])));
  }

  function barList(entries, bronze) {
    if (!entries.length) return emptyState(EMPTY_ICONS.barChart, 'No data available', 'Nothing to show for the current selection.');
    const max = Math.max(...entries.map(item=>item[1]),1);
    return `<div class="bar-list">${entries.slice(0,12).map(([label,value])=>`<div class="bar-row"><div class="bar-label" title="${esc(label)}">${esc(label)}</div><div class="bar-track"><div class="bar-fill ${bronze?'bronze':''}" style="width:${value/max*100}%"></div></div><div class="bar-value">${fmtNum(value)}</div></div>`).join('')}</div>`;
  }

  const missingLabels = missing => missing.map(field => FIELD_LABELS[field] || field);

  // analytics.js keeps the issue rule free of copy; the wording for each
  // descriptor lives here with the rest of the user-facing strings.
  const issueLabel = issue => {
    if (issue.kind === 'invalid-date') return 'End before start';
    if (issue.kind === 'short-notice') return `${issue.leadDays}d lead`;
    return FIELD_LABELS[issue.field] || issue.field;
  };

  // Two chips inline, the remainder folded into one overflow chip that still
  // carries a fix target -- a row with nine gaps must not blow up the column.
  const ISSUE_CHIPS_SHOWN = 2;
  function issueChips(id, issues) {
    // Every chip carries a title, not just the overflow one -- a plain chip
    // defaults to its own full label, since max-width:150px can ellipsis a
    // longer one (e.g. FIELD_LABELS.strategic_objectives) with no other way
    // to read it.
    const chip = (issue, text, title) =>
      `<button type="button" class="issue-chip ${esc(issue.kind)}" data-fix-id="${esc(id||'')}" data-fix-field="${esc(issue.field)}" title="${esc(title||text)}">${esc(text)}</button>`;
    const shown = issues.slice(0, ISSUE_CHIPS_SHOWN).map(issue => chip(issue, issueLabel(issue)));
    const rest = issues.slice(ISSUE_CHIPS_SHOWN);
    if (rest.length) shown.push(chip(rest[0], `+${rest.length}`, rest.map(issueLabel).join(', ')));
    return shown.join('');
  }

  function renderOverview() {
    const rows = state.rows;
    const now = new Date();
    const future30 = new Date(now); future30.setDate(now.getDate()+30);
    const active = rows.filter(row => {const s=A.parseDate(row.start_date),e=A.parseDate(row.end_date)||s;return s&&s<=now&&e>=now;});
    const upcoming = rows.filter(row => {const d=A.parseDate(row.start_date);return d&&d>=now&&d<=future30;}).sort((a,b)=>A.parseDate(a.start_date)-A.parseDate(b.start_date));
    const internal = rows.filter(row=>row.source_type==='internal').length;
    const external = rows.filter(row=>row.source_type==='external').length;
    // Scheduling conflicts are on ice (2026-07-30, user decision): at the real
    // portfolio's density the detector fires constantly, and nobody could say
    // what to do with the result. detectCollisions and its tests stay in
    // analytics.js so bringing the concept back is a wiring job, not a rebuild.
    const quality = A.dataQuality(rows);
    const lead = A.leadTimeStats(rows,7);

    const highPriority = rows.filter(row=>A.isHighPriority(row.priority));

    // Attention queue: aggregated by issue type instead of one row per finding.
    const incompleteRows = rows.filter(row=>A.planningCompleteness(row).score<100);
    const shortNoticeRows = rows.filter(A.isShortNotice);
    const invalidRows = rows.filter(A.hasInvalidDates);
    const totalIssues = incompleteRows.length+shortNoticeRows.length+invalidRows.length;
    document.getElementById('attention-count').textContent = totalIssues;
    // P10: the card's top border is a status signal, not decoration — red
    // only while findings are outstanding, neutral the moment the queue
    // clears (class consumed by styles.css: .priority-card.danger).
    const priorityCard = document.querySelector('.priority-card');
    if (priorityCard) priorityCard.classList.toggle('danger', totalIssues > 0);
    const missingCounts = new Map();
    incompleteRows.forEach(row=>A.planningCompleteness(row).missing.forEach(field=>missingCounts.set(field,(missingCounts.get(field)||0)+1)));
    const topMissing = Array.from(missingCounts.entries()).sort((a,b)=>b[1]-a[1])[0];
    // Signposts, not worklists. The remediation queues live under Planning and
    // the field-level view under Analytics, but a fresh-eyes run showed that
    // removing them from Overview entirely stranded the planner, the editor and
    // the data steward: all three lost their only route to completeness, lead
    // time and field coverage. One line each keeps the route without giving the
    // steering screen back to them. Rendered here, after topMissing exists, so
    // the third line can name the field instead of counting records.
    // Ranked, then capped at two. Four bands of identical weight made the reader
    // do the ranking the screen should have done -- asked which one mattered
    // before a meeting, a comms lead could not say. Rank is by how soon somebody
    // has to act: a clash needs a date moved this week, an unserved audience is a
    // gap worth filling, incomplete records and blank fields are steady-state
    // hygiene. The two that lose out are not orphaned -- every measure below
    // carries its own route, which is why the tiles became buttons.
    const signals=[];
    // Conflicts, incompleteness and short notice used to have a band each. They
    // now sit in the "Needs you first" queue directly below, grouped by type
    // with an action per group -- saying them twice on one screen was the
    // duplication that made this page feel crowded. What is left in the bands
    // is the blank-field finding and the coverage gap: neither is an activity
    // in a queue, so neither has anywhere else to appear.
    if(topMissing) signals.push({rank:3,html:`${esc(FIELD_LABELS[topMissing[0]]||topMissing[0])} is missing in ${fmtNum(topMissing[1])} of ${plural(rows.length,'activity','activities')}`,goto:'health:data-health',label:'Open data health',warn:false});
    // Coverage counts the gap, this names it. "3 of 4 audiences" tells a comms
    // lead that something is unserved without telling them what, and the
    // cross-tab that would answer it sits two clicks away behind a tab nobody
    // opens unprompted. Naming the audience turns a table you have to know
    // about into a finding that announces itself.
    // The "nothing planned for audience X · channel Y" band is gone from this
    // screen. It named categories with nothing in the next thirty days, which
    // at portfolio scale meant a paragraph of names directly under the tiles --
    // and the same absence is already visible as a zero-length bar in the
    // dimension it belongs to, on Health under Coverage by dimension. Losing
    // it also loses the only jump link into that section; it stays reachable
    // through the Health tab and its section anchors, which is a navigation
    // step rather than a dead end.
    const ranked = signals.sort((a,b)=>a.rank-b.rank);
    const shownSignals = ranked.slice(0,2);
    const hidden = ranked.slice(2);
    // A cap that stays quiet reads as "nothing else to see". Say what was held
    // back and where it lives, or the screen is lying by omission.
    //
    // The route is the next hidden signal's own route, not a fixed one. A
    // re-check of the previously-green tasks caught this: with a clash and an
    // idle audience taking both slots, the held-back finding was the blank-field
    // one, and a hard-coded "Open attention required" sent the data steward to
    // the planning queue instead of data health -- the exact stranding the
    // project's own lesson warns about, that moving a block moves the paths
    // that ran through it.
    document.getElementById('overview-collisions').innerHTML =
      shownSignals.map(s=>`<p class="notice ${s.warn?'warn':''}">${s.html} \u00b7 <button type="button" class="linklike" data-goto="${esc(s.goto)}">${esc(s.label)} \u2192</button></p>`).join('')
      + (hidden.length?`<p class="signal-rest">${plural(hidden.length,'further finding','further findings')} of lower urgency \u00b7 <button type="button" class="linklike" data-goto="${esc(hidden[0].goto)}">${esc(hidden[0].label)} \u2192</button></p>`:'');

    // Four themed collection cards, sixteen figures.
    //
    // This screen carried exactly these four cards once before, and they were
    // replaced by six flat tiles on the argument that sixteen figures cannot
    // rank themselves and the daily planner needs "what do I do next" instead.
    // They are back on request: the reader who asked for them wants the whole
    // portfolio in one scan, and the ranking job the tiles were doing is done
    // one card lower by "Needs you first", which groups findings by type and
    // carries an action per group.
    //
    // What went with the tiles: the routes and the movement chips. Three of the
    // four routes pointed at findings the queue below already lists. The fourth,
    // median lead time to Health, is now two clicks instead of one — accepted.
    //
    // Display only, with one exception: Readiness takes its accent from whether
    // anything is actually open. A permanently amber card is a false alarm on a
    // clean portfolio, which is why .priority-card.danger works the same way.
    // "In flight" counts a rolling seven days, matching "Coming up" below, and
    // its two rows say "within 7 days" rather than naming a calendar week. On a
    // Thursday the two readings share barely a day, and the code computes the
    // rolling one.
    const dash = (value, guard) => (guard ? value : '—');
    const readinessFindings = incompleteRows.length + quality.invalidDateRanges;
    const readinessTone = readinessFindings ? 'readiness' : 'clean';
    const cardsHtml = [
      kpiGroup('Portfolio', 'portfolio', [
        {v: fmtNum(rows.length), l: 'Total activities'},
        {v: fmtNum(internal), l: 'Internal'},
        {v: fmtNum(external), l: 'External'},
        {v: fmtNum(highPriority.length), l: 'Critical and high'}
      ]),
      kpiGroup('In flight', 'inflight', [
        {v: fmtNum(active.length), l: 'Active now'},
        {v: fmtNum(A.comingUp(rows, now, 7).length), l: 'Starts within 7 days'},
        {v: fmtNum(A.endingWithin(rows, now, 7).length), l: 'Ends within 7 days'},
        {v: fmtNum(upcoming.length), l: 'Next 30 days'}
      ]),
      kpiGroup('Readiness', readinessTone, [
        {v: fmtNum(incompleteRows.length), l: 'Incomplete'},
        {v: dash(`${quality.completenessRate}%`, rows.length), l: 'Complete', derived: true},
        {v: fmtNum(quality.missingPackIds), l: 'No pack'},
        {v: fmtNum(quality.invalidDateRanges), l: 'Invalid dates'}
      ]),
      kpiGroup('Lead time', 'leadtime', [
        {v: lead.median === null ? '—' : `${fmtNum(lead.median)}d`, l: 'Median lead'},
        {v: fmtNum(lead.shortNotice), l: 'On short notice'},
        {v: dash(`${lead.shortNoticeRate}%`, rows.length), l: 'Short-notice rate', derived: true},
        {v: fmtNum(lead.excluded), l: 'Excluded'}
      ])
    ].join('');
    document.getElementById('overview-kpis').innerHTML = cardsHtml;

    // The verdict paragraph is gone. It counted the deltas -- "2 of 3 measures
    // improved" -- which is arithmetic over chips the reader can already see,
    // and it carried a footnote explaining why those chips might mislead. Both
    // disappear with the rule above: a delta now appears only where the
    // comparison holds, so there is nothing left to caption and nothing left to
    // tally. Measured before removal: verdict and footnote were 206 of the
    // page's 868 characters of chrome, the single largest block of prose on a
    // screen whose owner opens it to find out what to do today.
    document.getElementById('overview-verdict').innerHTML='';

    const groups = [];
    if (incompleteRows.length) groups.push({severity:QUEUE_SEVERITY.incomplete,title:`${fmtNum(incompleteRows.length)} activities with missing fields`,meta:topMissing?`Largest gap: ${esc(FIELD_LABELS[topMissing[0]]||topMissing[0])} (${fmtNum(topMissing[1])})`:'',action:'Review list',queue:'incomplete'});
    if (shortNoticeRows.length) groups.push({severity:QUEUE_SEVERITY['short-notice'],title:`${fmtNum(shortNoticeRows.length)} activities on short notice`,meta:`Under 7 days lead time · median ${lead.median===null?'—':lead.median+'d'}`,action:'Review list',queue:'short-notice'});
    if (invalidRows.length) groups.push({severity:QUEUE_SEVERITY['invalid-date'],title:`${fmtNum(invalidRows.length)} invalid date ranges`,meta:'End date before start date',action:'Review list',queue:'invalid-date'});
    const deadlineRows = upcoming.filter(row=>A.planningCompleteness(row).score<100||shortNoticeRows.includes(row)).slice(0,5);
    const deadlines = deadlineRows.map(row=>{
      const completeness=A.planningCompleteness(row);
      const reason=completeness.score<100?`Missing: ${missingLabels(completeness.missing).slice(0,2).join(', ')}`:`Short notice: ${row.planning_lead_days}d lead`;
      const focus=completeness.missing[0]||'';
      // Red is reserved for a genuine date error (the project's colour
      // ruling); deadlineRows is otherwise incomplete or short-notice rows,
      // both of which read as amber -- never infer severity from the
      // completeness score, which says nothing about date validity.
      const severity=A.hasInvalidDates(row)?'critical':'high';
      return `<div class="list-row"><span class="severity-line ${severity}"></span><div><div class="list-title">${esc(row.activity_name||'Untitled')}</div><div class="list-meta">Starts ${fmtDate(row.start_date)} · ${esc(reason)}</div></div><button type="button" class="fix-link" data-fix-id="${esc(row.id||'')}" data-fix-field="${esc(focus)}">Fix now</button></div>`;
    }).join('');
    document.getElementById('attention-list').innerHTML = groups.length
      ? groups.map(group=>`<div class="queue-group"><span class="severity-line ${group.severity}"></span><div><div class="list-title">${group.title}</div><div class="list-meta">${group.meta}</div></div><button type="button" class="link-btn" data-queue="${group.queue}">${group.action}</button></div>`).join('')+(deadlines?`<div class="queue-heading">Nearest deadlines</div>${deadlines}`:'')
      : emptyState(EMPTY_ICONS.checkCircle, 'No planning issues detected', 'Nothing needs review right now.');

    document.getElementById('readiness-summary').innerHTML = `<div class="metric-line"><span>Fully complete</span><strong>${fmtNum(rows.length-quality.incomplete)}</strong></div><div class="progress"><span style="width:${quality.completenessRate}%"></span></div><div class="metric-line"><span>Missing pack/campaign</span><strong>${fmtNum(quality.missingPackIds)}</strong></div><div class="metric-line"><span>Invalid date range</span><strong>${fmtNum(quality.invalidDateRanges)}</strong></div><div class="metric-line"><span>Total activities</span><strong>${fmtNum(rows.length)}</strong></div>`;

    // Upcoming: grouped by week, channel chip per row.
    //
    // Capped at eight. Sixteen rows made this card 988px of content beside a
    // 172px chart, and the grid stretched the chart's card to match -- 893px of
    // empty card, measured, which is what "the page feels overloaded" looked
    // like from the other side. Eight covers roughly the first fortnight, which
    // is the horizon a planner acts on; the rest is one click away and the
    // footer says how many there are rather than trailing off silently.
    const UPCOMING_SHOWN = 8;
    const weekKey = date => {const d=new Date(date);const day=(d.getDay()+6)%7;d.setDate(d.getDate()-day);d.setHours(0,0,0,0);return d;};
    const weekGroups = new Map();
    upcoming.slice(0,UPCOMING_SHOWN).forEach(row=>{const key=weekKey(A.parseDate(row.start_date)).getTime();if(!weekGroups.has(key))weekGroups.set(key,[]);weekGroups.get(key).push(row);});
    const upcomingRest = Math.max(0, upcoming.length - UPCOMING_SHOWN);
    document.getElementById('upcoming-list').innerHTML = upcoming.length
      ? Array.from(weekGroups.entries()).map(([key,items])=>`<div class="week-heading">Week of ${fmtDate(new Date(Number(key)))}</div>`+items.map(row=>`<div class="list-row" data-open-id="${esc(row.id||'')}"><span class="severity-line medium"></span><div><div class="list-title">${esc(row.activity_name||'Untitled')}</div><div class="list-meta">${fmtDate(row.start_date)} · ${esc(row.lead_team||row.lead||'Unassigned')}</div></div><span>${row.channel?`<span class="chip"><i class="channel-dot" style="background:${channelColor(row.channel)}" aria-hidden="true"></i>${esc(row.channel)}</span>`:''}</span></div>`).join('')).join('')
        + (upcomingRest?`<div class="list-more">${fmtNum(upcomingRest)} more in the next 30 days · <button type="button" class="linklike" data-goto="overview:timeline">See them on the timeline →</button></div>`:'')
      : emptyState(EMPTY_ICONS.calendar, 'No activities in the next 30 days', 'Check back later or widen the planning horizon.');

    // Centre carries the pool the shares are read against -- "17% urgent" is
    // meaningless without knowing 17% of what.
    document.getElementById('priority-donut').innerHTML=donutHtml(priorityEntries(rows),priorityColor,null,'activities');
    // Two rings side by side, and the centres are what keeps them apart: one
    // counts activities, the other counts division mentions, so the totals
    // differ on any portfolio where an activity names two divisions or none.
    // Never let a ring render its centre bare here.
    document.getElementById('division-donut').innerHTML=donutHtml(divisionEntries(rows),divisionColor,null,'mentions');
    // Both rings and the monthly trend closed this page before the rebuild, and
    // all three were dropped on 2026-07-29 as portfolio shape rather than "what
    // do I do next". The trend came back first, then the priority ring, and the
    // division split now with it: on the real portfolio it answers who the
    // quarter is actually for, which the planner reads before deciding what to
    // move. It overlaps Coverage by dimension on Health, which counts the same
    // divisions as bars beside team, audience and region -- that page asks which
    // categories are thin, this ring asks how the whole splits, and the answer
    // is wanted here without a second navigation.
  }

  function renderTrend() {
    const rows = state.trendMode?state.rows.filter(row=>row.source_type===state.trendMode):state.rows;
    document.getElementById('monthly-trend').innerHTML = monthlyTrendHtml(rows);
  }

  function futureRows(weeks) {
    const now = new Date(); const end = new Date(now); end.setDate(end.getDate()+weeks*7);
    return state.rows.filter(row=>{const s=A.parseDate(row.start_date),e=A.parseDate(row.end_date)||s;return s&&e>=now&&s<=end;}).sort((a,b)=>A.parseDate(a.start_date)-A.parseDate(b.start_date));
  }

  const BOARD_GROUPS = {
    channel: {label:'channel', of:row=>split(row.channel)[0]||'No channel'},
    campaign: {label:'campaign', of:row=>campaignLabel(row)||'No campaign'},
    division: {label:'division', of:row=>split(row.business_division)[0]||'No division'}
  };
  const BOARD_LANE_LIMIT = 12;

  function renderBoard() {
    const rows = futureRows(state.horizonWeeks);
    const lead=A.leadTimeStats(rows,7);
    const coverage=A.weeklyCoverage(rows,state.horizonWeeks,new Date());
    const peak=coverage.reduce((best,w)=>w.count>(best?best.count:-1)?w:best,null);
    document.getElementById('planning-kpis').innerHTML=[kpi('In horizon',rows.length,`Next ${state.horizonWeeks} weeks`,''),kpi('Short notice',lead.shortNotice,`${lead.shortNoticeRate}% of valid`,lead.shortNotice?'warning':''),kpi('Median lead',lead.median===null?'—':`${lead.median}d`,`${lead.excluded} excluded`,''),kpi('Peak week',peak?peak.count:0,peak?fmtDate(peak.from):'—','')].join('');

    const grouping = BOARD_GROUPS[state.boardGroup]||BOARD_GROUPS.channel;
    document.getElementById('board-subtitle').textContent = `Swimlanes per ${grouping.label} · bars span start to end`;

    const lanes = new Map();
    rows.forEach(row=>{const key=grouping.of(row);if(!lanes.has(key))lanes.set(key,[]);lanes.get(key).push(row);});
    const weeks = coverage;
    let html=`<div class="timeline"><div class="timeline-grid" style="grid-template-columns:190px repeat(${weeks.length},minmax(58px,1fr))"><div class="timeline-head">Activity</div>${weeks.map(w=>`<div class="timeline-head">${fmtDate(w.from).replace(/\s\d{4}$/,'')}</div>`).join('')}`;
    Array.from(lanes.entries()).sort((a,b)=>b[1].length-a[1].length).forEach(([lane,laneRows])=>{
      html+=`<div class="timeline-group">${esc(lane)} (${laneRows.length})</div>`;
      laneRows.slice(0,BOARD_LANE_LIMIT).forEach(row=>{
        const start=A.parseDate(row.start_date),end=A.parseDate(row.end_date)||start;
                html+=`<div class="timeline-label" data-open-id="${esc(row.id||'')}" title="${esc(row.activity_name||'')}">${esc(row.activity_name||'Untitled')}</div>`;
        weeks.forEach((w,i)=>{
          const overlaps=start&&start<w.to&&end>=w.from;
          const isFirst=overlaps&&!(start<w.from);
          const isLast=overlaps&&!(end>=w.to);
          const cls=`timeline-bar${row.source_type==='external'?' external':''}${isFirst?' start':''}${isLast?' end':''}`;
          html+=`<div class="timeline-cell">${overlaps?`<span class="${cls}" title="${esc(row.channel||'')}"></span>`:''}</div>`;
        });
      });
      if(laneRows.length>BOARD_LANE_LIMIT)html+=`<div class="timeline-more">+${laneRows.length-BOARD_LANE_LIMIT} more in ${esc(lane)}</div>`;
    });
    html+='</div></div>';

    // An empty stretch is information, not blank space: name the gap.
    let gapNote='';
    let run=[];
    const flushRun=()=>{if(run.length>=3){const from=run[0].from,to=run[run.length-1].to;gapNote+=`<div class="board-gap-note">No activity planned ${fmtDate(from)} – ${fmtDate(new Date(to.getTime()-86400000))}</div>`;}run=[];};
    weeks.forEach(w=>{if(w.count===0)run.push(w);else flushRun();});
    flushRun();

    document.getElementById('planning-board').innerHTML=(rows.length?html:emptyState(EMPTY_ICONS.calendar, 'No upcoming activities in this horizon', 'Extend the horizon or adjust filters to see more.'))+gapNote;
  }

  function renderCalendar() {
    const date=state.calendarDate,year=date.getFullYear(),month=date.getMonth();
    document.getElementById('calendar-title').textContent=date.toLocaleDateString('en-GB',{month:'long',year:'numeric'});
    const first=new Date(year,month,1),days=new Date(year,month+1,0).getDate(),offset=(first.getDay()+6)%7,total=Math.ceil((offset+days)/7)*7;
    const today=new Date(); let html=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map(d=>`<div class="calendar-head">${d}</div>`).join('');
    for(let i=0;i<total;i+=1){const d=new Date(year,month,i-offset+1),other=d.getMonth()!==month,isToday=d.toDateString()===today.toDateString();const events=state.rows.filter(row=>{const rd=A.parseDate(row.start_date);return rd&&rd.toDateString()===d.toDateString();});html+=`<div class="calendar-day ${other?'other':''} ${isToday?'today':''}"><div class="cal-number">${d.getDate()}</div>${events.slice(0,4).map(row=>`<div class="cal-event ${row.source_type==='external'?'external':''}" data-open-id="${esc(row.id||'')}" title="${esc(row.activity_name||'')}">${esc(row.activity_name||'Untitled')}</div>`).join('')}${events.length>4?`<div class="cal-event">+${events.length-4} more</div>`:''}</div>`;}
    document.getElementById('planning-calendar').innerHTML=`<div class="calendar">${html}</div>`;
  }






  function renderCapacity() {
    const future=futureRows(26),weekly=A.weeklyCoverage(future,12,new Date()),max=Math.max(...weekly.map(w=>w.count),1);
    document.getElementById('weekly-load').innerHTML=`<div class="bar-list">${weekly.map(w=>`<div class="bar-row"><div class="bar-label">${fmtDate(w.from).replace(/\s\d{4}$/,'')}</div><div class="bar-track"><div class="bar-fill" style="width:${w.count/max*100}%"></div></div><div class="bar-value">${w.count}</div></div>`).join('')}</div>`;
    // Net-new per horizon instead of four identical decorative bars: what each
    // wider horizon adds is the coverage answer — "+0 beyond 4 weeks" is
    // itself the finding.
    const horizons=[4,8,12,26].map(weeks=>({weeks,count:futureRows(weeks).length}));
    let previousCount=0;
    document.getElementById('forward-coverage').innerHTML=horizons.map((item,index)=>{
      const label=item.weeks===26?'6 months':`${item.weeks} weeks`;
      const delta=item.count-previousCount;
      const detail=index===0?`${fmtNum(item.count)} activities`:(delta>0?`${fmtNum(item.count)} · +${fmtNum(delta)} beyond ${horizons[index-1].weeks===26?'6 months':horizons[index-1].weeks+' weeks'}`:`${fmtNum(item.count)} · no additions`);
      previousCount=item.count;
      return `<div class="metric-line"><span>${label}</span><strong>${detail}</strong></div>`;
    }).join('');
    const withOwner=rows=>rows.map(row=>Object.assign({},row,{lead_team:row.lead_team||row.lead||'Unassigned'}));
    // Categories come from the whole loaded portfolio, counts from the horizon.
    const allRows=state.snapshotRows.length?state.snapshotRows:state.rows;
    const dimensions=[
      ['Lead teams','lead_team',withOwner(allRows),withOwner(future)],
      ['Communications pillars','strategic_objectives',allRows,future],
      ['Target audiences','target_audience',allRows,future],
      ['Channels','channel',allRows,future],
      ['Regions','region',allRows,future],
    ];
    const panels=dimensions.map(([label,field,source,window])=>{
      const entries=countByAgainst(source,window,field);
      return `<div><h3>${esc(label)}</h3>${barList(entries)}</div>`;
    }).join('');
    // The banner that used to head this block listed every empty category by
    // name. Over five dimensions and a real portfolio that is a paragraph
    // before the reader reaches a single chart -- and the charts say it better:
    // countByAgainst keeps categories with nothing planned in the list at zero,
    // so an empty category is a visible bar of length nothing, in the dimension
    // it belongs to, rather than a name in a run-on sentence.
    document.getElementById('coverage-dimensions').innerHTML=`<div class="grid two">${panels}</div>`;
  }

  function populateActivityFilters() {
    const fill=(id,values,label)=>{const el=document.getElementById(id),current=el.value;el.innerHTML=`<option value="">All ${label}</option>`+values.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');el.value=current;};
    fill('activity-channel',countBy(state.rows,'channel').map(x=>x[0]),'channels');
    fill('activity-priority',countBy(state.rows,'priority').map(x=>x[0]),'priorities');
    const campaigns=new Set();
    state.rows.forEach(row=>{const label=campaignLabel(row);if(label)campaigns.add(label);});
    fill('activity-campaign',Array.from(campaigns).sort((a,b)=>a.localeCompare(b)),'campaigns / packs');
    // The absence is a selectable value, not a gap in the list. Without it the
    // packless records could be counted but never listed, and the Packs tile
    // pointing here would land on an unfiltered table.
    const campaignSelect=document.getElementById('activity-campaign');
    if(!campaignSelect.querySelector(`option[value="${NO_PACK}"]`)){
      const opt=document.createElement('option');
      opt.value=NO_PACK; opt.textContent='— Not in a pack';
      campaignSelect.insertBefore(opt, campaignSelect.children[1]||null);
    }
  }

  // Transient filter applied from the Overview attention queue ("Review list").
  function matchesQueueFilter(row) {
    if (!state.queueFilter) return true;
    if (state.queueFilter==='incomplete') return A.planningCompleteness(row).score<100;
    if (state.queueFilter==='short-notice') return A.isShortNotice(row);
    if (state.queueFilter==='invalid-date') return A.hasInvalidDates(row);
    return true;
  }

  const QUEUE_FILTER_LABELS = {incomplete:'Missing fields', 'short-notice':'Short notice', 'invalid-date':'Invalid dates'};

  // One severity per queue, shared by the overview attention card and the
  // workbench context bar -- they describe the same finding, so they must not
  // be able to disagree. Red is reserved for the one genuine error.
  const QUEUE_SEVERITY = {incomplete:'high', 'short-notice':'high', 'invalid-date':'critical', conflicts:'medium'};

  const ACTIVITY_FILTER_IDS=['activity-search','activity-source','activity-channel','activity-priority','activity-campaign','activity-readiness'];

  function applyActivityFilters() {
    const q=document.getElementById('activity-search').value.toLowerCase(),source=document.getElementById('activity-source').value,channel=document.getElementById('activity-channel').value,priority=document.getElementById('activity-priority').value,campaign=document.getElementById('activity-campaign').value,readiness=document.getElementById('activity-readiness').value;
    const rows=state.rows.filter(row=>{
      const complete=A.planningCompleteness(row).score===100;
      return matchesQueueFilter(row)&&(!q||Object.values(row).some(value=>String(value||'').toLowerCase().includes(q)))&&(!source||row.source_type===source)&&(!channel||split(row.channel).includes(channel))&&(!priority||split(row.priority).includes(priority))&&(!campaign||(campaign===NO_PACK?!nonempty(row.communication_pack_cpid):campaignLabel(row)===campaign))&&(!readiness||(readiness==='complete'&&complete)||(readiness==='incomplete'&&!complete));
    }).sort((a,b)=>(A.parseDate(b.start_date)||0)-(A.parseDate(a.start_date)||0));
    state.filteredRows=rows;
    document.getElementById('activity-result-count').textContent=`${fmtNum(rows.length)} of ${fmtNum(state.rows.length)}`;
    renderQueueBar(rows);
    document.getElementById('activity-table-body').innerHTML=rows.map(row=>{
      const issues=A.rowIssues(row);
      const issueCell=issues.length
        ? issueChips(row.id,issues)
        : '<span class="readiness-ok">—</span>';
      const duplicateBtn = canCreate() ? `<button type="button" class="icon-btn duplicate-btn" data-duplicate-id="${esc(row.id||'')}" aria-label="Duplicate ${esc(row.activity_name||'activity')}" title="Duplicate"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg></button>` : '';
      return `<tr data-open-id="${esc(row.id||'')}"><td><button type="button" class="name-btn" data-open-id="${esc(row.id||'')}" title="${esc(row.activity_name||'')}">${esc(row.activity_name||'Untitled')}</button></td><td>${trackingIdHtml(row.tracking_id,{copy:nonempty(row.tracking_id)})}</td><td>${channelTag(row.channel)}</td><td>${fmtDate(row.start_date)}</td><td>${esc(row.priority||'—')}</td><td>${esc(row.lead_team||row.lead||'—')}</td><td>${esc(campaignLabel(row)||'—')}</td><td class="issue-cell">${issueCell}</td><td class="action-cell"><div class="row-actions">${duplicateBtn}</div></td></tr>`;}).join('')||`<tr><td colspan="9">${emptyState(EMPTY_ICONS.search, 'No activities match the filters', 'Clear filters or adjust your search to see more results.')}</td></tr>`;
  }

  // Names the review list the user arrived from. Everything it reports is
  // computed over the rows actually on screen, so combining the queue with a
  // search term does not leave a stale headline behind.
  function renderQueueBar(rows) {
    const bar=document.getElementById('activity-queue-bar');
    if(!state.queueFilter){bar.hidden=true;return;}
    let detail='';
    if(state.queueFilter==='incomplete'){
      const counts=new Map();
      rows.forEach(row=>A.planningCompleteness(row).missing.forEach(field=>counts.set(field,(counts.get(field)||0)+1)));
      const top=Array.from(counts.entries()).sort((a,b)=>b[1]-a[1])[0];
      if(top)detail=`Largest gap: ${FIELD_LABELS[top[0]]||top[0]} (${fmtNum(top[1])})`;
    } else if(state.queueFilter==='short-notice'){
      detail='Under 7 days lead time';
    } else if(state.queueFilter==='invalid-date'){
      detail='End date before start date';
    }
    document.getElementById('queue-bar-severity').className=`severity-line ${QUEUE_SEVERITY[state.queueFilter]||''}`;
    document.getElementById('queue-bar-title').textContent=QUEUE_FILTER_LABELS[state.queueFilter]||state.queueFilter;
    document.getElementById('queue-bar-meta').textContent=`${fmtNum(rows.length)} in view${detail?` · ${detail}`:''}`;
    bar.hidden=false;
  }

  // Adjacent markers within this many percentage points of the scale are
  // considered coincident and share a single merged label.
  const LABEL_COLLISION_THRESHOLD_PCT = 6;

  function clusterLeadMarkers(markers) {
    const sorted=markers.slice().sort((a,b)=>a.x-b.x);
    const clusters=[];
    sorted.forEach(marker=>{
      const last=clusters[clusters.length-1];
      if(last&&marker.x-last[last.length-1].x<=LABEL_COLLISION_THRESHOLD_PCT)last.push(marker);
      else clusters.push([marker]);
    });
    return clusters;
  }

  function renderPlanningHealth() {
    renderTrend();
    const rows=state.rows,quality=A.dataQuality(rows),lead=A.leadTimeStats(rows,7),complete=rows.length-quality.incomplete;
    document.getElementById('health-kpis').innerHTML=[kpi('Complete',`${quality.completenessRate}%`,`${complete} of ${rows.length}`,quality.incomplete?'warning':'success'),kpi('Short notice',`${lead.shortNoticeRate}%`,`Threshold <7 days`,lead.shortNotice?'warning':'success'),kpi('Median lead',lead.median===null?'—':`${lead.median}d`,`P25 ${lead.p25??'—'} · P75 ${lead.p75??'—'}`,''),kpi('Excluded',lead.excluded,'Missing or negative lead time','')].join('');
    const max=Math.max(lead.p75||0,lead.median||0,lead.p25||0,1),xOf=v=>v/max*90+5;
    // Degenerate distribution: every valid lead time is zero — a broken-looking
    // chart hides the actual story, so state it as a diagnosis instead.
    if(lead.valid&&lead.p25===0&&lead.median===0&&lead.p75===0){
      document.getElementById('lead-distribution').innerHTML=`<div class="notice" style="margin:0"><strong>All lead times are 0 days.</strong> Start dates likely equal entry dates — check date practices before reading this distribution.</div>`;
      renderMissingFieldsAndTeams(rows);
      return;
    }
    const markers=[['P25',lead.p25],['Median',lead.median],['P75',lead.p75]].filter(([,v])=>v!==null&&v!==undefined).map(([label,value])=>({label,value,x:xOf(value)}));
    const pointsHtml=clusterLeadMarkers(markers).map(cluster=>{
      const dots=cluster.map(m=>`<span class="distribution-point" style="left:${m.x}%"></span>`).join('');
      const center=cluster.reduce((sum,m)=>sum+m.x,0)/cluster.length;
      const sameValue=cluster.every(m=>m.value===cluster[0].value);
      const text=sameValue?`${cluster.map(m=>m.label).join(' · ')} ${cluster[0].value}d`:cluster.map(m=>`${m.label} ${m.value}d`).join(' · ');
      return `${dots}<span class="distribution-label" style="left:${center}%">${text}</span>`;
    }).join('');
    document.getElementById('lead-distribution').innerHTML=`<div class="distribution"><div class="distribution-range" style="left:${(lead.p25||0)/max*90+5}%;width:${((lead.p75||0)-(lead.p25||0))/max*90}%"></div>${pointsHtml}</div>`;
    renderMissingFieldsAndTeams(rows);
  }

  function renderMissingFieldsAndTeams(rows) {
    // Every field the create form collects, not only the required ones that
    // happen to be missing. Listing just the required gaps made a systematically
    // empty optional field undiscoverable: a data steward could only ever find
    // the holes the product already knew about, and the totals never added up
    // (records-incomplete counted more than the listed fields explained).
    // Optional fields are marked, so a high blank count on one is a finding
    // rather than an alarm.
    const blanks=new Map();
    CREATE_FIELDS.forEach(field=>blanks.set(field,0));
    rows.forEach(row=>CREATE_FIELDS.forEach(field=>{ if(!nonempty(row[field])) blanks.set(field,blanks.get(field)+1); }));
    const requiredAnywhere=new Set([].concat(A.REQUIRED_INTERNAL||[],A.REQUIRED_EXTERNAL||[]));
    const entries=Array.from(blanks.entries())
      .filter(([,count])=>count>0)
      .map(([field,count])=>[`${FIELD_LABELS[field]||field}${requiredAnywhere.has(field)?'':' (optional)'}`,count])
      .sort((a,b)=>b[1]-a[1]);
    document.getElementById('missing-fields').innerHTML=barList(entries);
    const teamRows=new Map();rows.forEach(row=>{const key=row.lead_team||row.lead||'Unassigned';if(!teamRows.has(key))teamRows.set(key,[]);teamRows.get(key).push(row);});
    document.getElementById('team-health').innerHTML=`<table><thead><tr><th>Team</th><th class="num">Activities</th><th class="num">Complete</th><th class="num">Short notice</th><th class="num">Median lead</th></tr></thead><tbody>${Array.from(teamRows.entries()).map(([team,items])=>{const q=A.dataQuality(items),l=A.leadTimeStats(items,7);return `<tr><td>${esc(team)}</td><td class="num">${items.length}</td><td class="num">${q.completenessRate}%</td><td class="num">${l.shortNoticeRate}%</td><td class="num">${l.median===null?'—':l.median+'d'}</td></tr>`;}).join('')}</tbody></table>`;
  }

  // What is left of the strategic view after the Health rebuild: the
  // channel-mix cross-tab, and nothing else. Pillar and Division coverage went
  // to "Coverage by dimension", which says both and adds three more. The
  // unaligned worklist went with them -- an activity without a pillar is an
  // incomplete record, and incomplete records already have a home in the
  // attention queue and in the Issue column, each of which names the missing
  // field and opens the record on it. A second list of the same rows under a
  // different heading was a third place to find them, not a new finding.
  function renderStrategic() {
    renderChannelMix();
  }

  // Channel mix: which channel actually carries which audience or pillar.
  // Everything else in the studio slices one dimension at a time, so the
  // question "do we reach frontline staff by a channel they can even see"
  // could only be answered by exporting rows and building the table by hand.
  //
  // Deliberately counts only. Effectiveness needs an outcome signal — opens,
  // attendance, intranet views — and CPLAN records planning data, not results.
  // A "best mix" recommendation from this data would be a guess wearing the
  // clothes of an analysis. What the table does show is structural mismatch:
  // an audience served by a single channel, or a channel carrying everything
  // and therefore standing for nothing.
  function renderChannelMix() {
    const host=document.getElementById('channel-mix');
    if(!host) return;
    const dim=(document.querySelector('#mix-dimension .active')||{}).dataset?.dim||'target_audience';
    const rows=state.rows;
    const channels=countBy(rows,'channel').map(([label])=>label);
    const columns=countBy(rows,dim).map(([label])=>label);
    if(!channels.length||!columns.length){
      host.innerHTML=emptyState(EMPTY_ICONS.barChart,'Not enough data for a mix','Channels and the selected dimension both need values.');
      return;
    }
    const cell=new Map();
    rows.forEach(row=>split(row.channel).forEach(ch=>split(row[dim]).forEach(col=>{
      const key=ch+'\u0000'+col; cell.set(key,(cell.get(key)||0)+1);
    })));
    const colTotal=col=>channels.reduce((sum,ch)=>sum+(cell.get(ch+'\u0000'+col)||0),0);
    const head=`<tr><th>Channel</th>${columns.map(c=>`<th class="num">${esc(c)}</th>`).join('')}<th class="num">Total</th></tr>`;
    const body=channels.map(ch=>{
      const values=columns.map(col=>cell.get(ch+'\u0000'+col)||0);
      const total=values.reduce((a,b)=>a+b,0);
      return `<tr><td>${esc(ch)}</td>${values.map(v=>`<td class="num">${v?fmtNum(v):'<span class="mix-zero">0</span>'}</td>`).join('')}<td class="num">${fmtNum(total)}</td></tr>`;
    }).join('');
    const foot=`<tr><td>Total</td>${columns.map(c=>`<td class="num">${fmtNum(colTotal(c))}</td>`).join('')}<td class="num">${fmtNum(rows.length)}</td></tr>`;
    const single=columns.filter(c=>channels.filter(ch=>(cell.get(ch+'\u0000'+c)||0)>0).length===1);
    const note=single.length?`<p class="notice warn">Reached through a single channel only: ${single.map(esc).join(' · ')}</p>`:'';
    host.innerHTML=`${note}<div class="table-wrap"><table>${`<thead>${head}</thead>`}<tbody>${body}${foot}</tbody></table></div>`;
  }

  // Packs. The tab the prototype has and the studio did not: a pack is what a
  // planner actually ships -- one message across several channels -- and until
  // now it existed only as a string on each activity and a segment in the
  // tracking ID, described by a card buried two clicks deep under "Campaign
  // Quality". Grouping happens client-side rather than through v_pack_overview,
  // which is defined for PostgreSQL only (split_part) and absent on the SQLite
  // backend this deployment actually runs.
  function packUnits() {
    const inPack=state.rows.filter(row=>nonempty(row.communication_pack_cpid));
    const loose=state.rows.filter(row=>!nonempty(row.communication_pack_cpid));
    return {cards:A.campaignScorecards(inPack), loose};
  }

  function filteredPackCards(cards) {
    const term=(document.getElementById('pack-search').value||'').trim().toLowerCase();
    const campaign=document.getElementById('pack-campaign-filter').value;
    return cards.filter(card=>{
      if(campaign&&card.campaign!==campaign) return false;
      if(!term) return true;
      const hay=[card.id,card.campaign,...card.channelNames,...card.rows.map(r=>r.tracking_id||'')].join(' ').toLowerCase();
      return hay.includes(term);
    });
  }

  // Named openPackDetail on purpose. T6 retired a create-flow wrapper whose
  // name two guardian tests still pin as absent, because it was a SECOND way
  // into pack CREATION. This is a read view of a pack that already exists --
  // opposite concern -- and creation still runs only through openCreateDrawer
  // plus the scope toggle. Renaming was the right fix; loosening two tests
  // that guard a different rule was not. The retired name is deliberately not
  // spelled out anywhere in this file: the assertion is a substring match, so
  // even a comment mentioning it turns the guard red. It did, once.
  //
  // Pack detail, modelled on the prototype's drawer: a card per channel with that
  // channel's colour down its left edge, the tracking ID with a copy control,
  // and the three facts a planner checks per send -- when, to whom, by whom.
  // The prototype's per-channel status dropdown has no counterpart here: the
  // studio holds no status field, and inventing one in the UI would promise a
  // state nothing persists. Readiness stands in its place, computed from the
  // same completeness rule as everywhere else.
  function openPackDetail(packId, opener) {
    const {cards}=packUnits();
    const card=cards.find(item=>item.id===packId);
    if(!card) return;
    state.packDrawerOpener=opener||document.activeElement;
    const gaps=card.rows.filter(row=>A.planningCompleteness(row).score<100).length;

    document.getElementById('pack-drawer-eyebrow').textContent=`${card.id} · Communication pack`;
    document.getElementById('pack-drawer-title').textContent=card.campaign&&card.campaign!==card.id?card.campaign:card.id;
    document.getElementById('pack-drawer-meta').innerHTML=
      `<span class="badge ${gaps?'warning':'success'}">${gaps?plural(gaps,'activity','activities')+' incomplete':'Complete'}</span>`
      +`<span class="tracking-label">${plural(card.activities,'tracking ID')} · ${plural(card.channels,'channel')}</span>`;

    const detail=(label,value)=>`<div class="detail-row"><dt>${esc(label)}</dt><dd>${value}</dd></div>`;
    const audiences=Array.from(new Set(card.rows.flatMap(row=>split(row.target_audience))));
    const pillars=Array.from(new Set(card.rows.flatMap(row=>split(row.strategic_objectives))));
    const teams=Array.from(new Set(card.rows.map(row=>row.lead_team||row.lead).filter(nonempty)));
    document.getElementById('pack-drawer-details').innerHTML=
      `<div class="detail-section"><h4>Pack details</h4><dl>`
      + detail('Campaign', esc(card.campaign||'—'))
      + detail('Window', `${fmtDate(card.firstDate)} – ${fmtDate(card.lastDate)}`)
      + detail('Channels', card.channelNames.map(channelTag).join(' '))
      + detail('Audiences', esc(audiences.join(', ')||'—'))
      + detail('Communications pillars', esc(pillars.join(', ')||'—'))
      + detail('Lead teams', esc(teams.join(', ')||'—'))
      + `</dl></div>`;

    const ordered=card.rows.slice().sort((a,b)=>(A.parseDate(a.start_date)||0)-(A.parseDate(b.start_date)||0));
    document.getElementById('pack-drawer-channels').innerHTML=ordered.map(row=>{
      // The same issue chips the activity table carries, not a badge that only
      // states a number. A badge tells the planner something is missing and
      // then makes them find it; the chip names the field and opens the record
      // on it. Identical markup, so the delegated [data-fix-id] handler drives
      // it with no wiring of its own, and the finding cannot drift between the
      // two surfaces -- both read A.rowIssues.
      const issues=A.rowIssues(row);
      const meta=(label,value)=>`<div class="pack-channel-fact"><span class="pack-fact-label">${esc(label)}</span><span class="pack-fact-value">${value}</span></div>`;
      return `<article class="pack-channel-card" style="border-left-color:${channelColor(row.channel)}">
        <div class="pack-channel-head">
          <span class="pack-channel-name"><i class="channel-dot" style="background:${channelColor(row.channel)}" aria-hidden="true"></i>${esc(row.channel||'No channel')}</span>
          <span class="pack-channel-issues">${issues.length?issueChips(row.id,issues):'<span class="badge success">Complete</span>'}</span>
        </div>
        <div class="pack-channel-id">${trackingIdHtml(row.tracking_id,{copy:true})}</div>
        <div class="pack-channel-facts">
          ${meta('Send date & time', esc(fmtDateTime(row.start_date)))}
          ${meta('Distribution list', esc(row.target_audience||'—'))}
          ${meta('Responsible', esc(row.lead_team||row.lead||'Unassigned'))}
        </div>
        <button type="button" class="linklike" data-open-id="${esc(row.id||'')}">Open activity →</button>
      </article>`;
    }).join('');

    const drawer=document.getElementById('pack-drawer');
    drawer.classList.add('open');
    drawer.setAttribute('aria-hidden','false');
    document.getElementById('pack-drawer-close').focus();
    bindOpenRows();
  }

  function closePackDetail() {
    const drawer=document.getElementById('pack-drawer');
    drawer.classList.remove('open');
    drawer.setAttribute('aria-hidden','true');
    // Focus goes back to the row that opened it, or the reader is dropped at
    // the top of the document with no idea where they were.
    if(state.packDrawerOpener&&document.contains(state.packDrawerOpener))state.packDrawerOpener.focus();
    state.packDrawerOpener=null;
  }

  function renderPacks() {
    const {cards,loose}=packUnits();
    const shown=filteredPackCards(cards);
    document.getElementById('packs-count').textContent=fmtNum(cards.length);

    const campaigns=Array.from(new Set(cards.map(c=>c.campaign).filter(nonempty))).sort();
    const select=document.getElementById('pack-campaign-filter');
    const keep=select.value;
    select.innerHTML='<option value="">All campaigns</option>'+campaigns.map(c=>`<option value="${esc(c)}">${esc(c)}</option>`).join('');
    select.value=campaigns.includes(keep)?keep:'';

    // Single-channel is the measure worth surfacing: a "pack" that reaches one
    // channel is a pack in name only, and that is orchestration feedback the
    // planner can act on.
    const single=cards.filter(c=>c.channels===1).length;
    const incomplete=cards.filter(c=>c.rows.some(row=>A.planningCompleteness(row).score<100)).length;
    document.getElementById('packs-kpis').innerHTML=[
      kpi('Packs',fmtNum(cards.length),`${plural(cards.length?Math.round(cards.reduce((s,c)=>s+c.activities,0)/cards.length*10)/10:0,'activity','activities')} on average`,''),
      kpi('Single-channel',fmtNum(single),single?'A pack in name only':'Every pack spans channels',single?'warning':'success'),
      kpi('With gaps',fmtNum(incomplete),'At least one incomplete activity',incomplete?'warning':'success'),
      // The list this number used to sit above is gone: at 148 of 400 records
      // it filled more of the tab than the packs did, on a page that exists to
      // show packs. The count stays, and the tile becomes the way to the
      // records themselves -- removing the block without leaving a route would
      // have stranded 37% of the portfolio behind a figure.
      kpi('Not in a pack',fmtNum(loose.length),`${cards.length?Math.round(loose.length/state.rows.length*100):0}% of the portfolio`,loose.length?'warning':'','activities:no-pack')
    ].join('');

    document.getElementById('pack-result-count').textContent=
      shown.length===cards.length?plural(cards.length,'pack'):`${fmtNum(shown.length)} of ${plural(cards.length,'pack')}`;

    // A table with a column for channels, not a meta line with the channels
    // trailing off the end of it. Run together with the counts and the window,
    // four channel names read as clutter; in their own column they align down
    // the page and the channel spread of the whole portfolio becomes scannable
    // in one vertical pass. Pattern from the prototype's Packs table.
    //
    // One chip per CHANNEL, not per tracking ID. The prototype can print an ID
    // per chip because its packs hold one send per channel; ours average 7.9
    // activities over four or five channels, so per-ID chips would put eleven
    // of them in a cell and rebuild exactly the crowding this replaces. The
    // count rides along instead, and the IDs are one click away in the drawer.
    const packRow = card => {
      const gaps=card.rows.filter(row=>A.planningCompleteness(row).score<100).length;
      const perChannel=new Map();
      card.rows.forEach(row=>split(row.channel).forEach(ch=>perChannel.set(ch,(perChannel.get(ch)||0)+1)));
      const channelCell=perChannel.size
        ? Array.from(perChannel.entries()).sort((a,b)=>b[1]-a[1]).map(([ch,count])=>
            `<span class="channel-chip"><i class="channel-dot" style="background:${channelColor(ch)}" aria-hidden="true"></i>${esc(ch)}${count>1?`<span class="channel-chip-count">${fmtNum(count)}</span>`:''}</span>`).join('')
        : '<span class="muted">no channel</span>';
      // Sorted, then capped at two. Measured before: 27 of 32 packs carry a
      // distinct audience set, so the column does hold information -- but the
      // sets arrive in row order, so two packs reaching the same four groups
      // printed them in different orders and could not be compared at a
      // glance. Sorting makes identical sets look identical; the cap stops the
      // cell from becoming the wall of text it was. Full lists live in the
      // drawer, which is one click away and has the room.
      const brief=values=>{
        const sorted=Array.from(new Set(values)).filter(nonempty).sort();
        if(!sorted.length) return '—';
        const head=sorted.slice(0,2).map(esc).join(', ');
        return sorted.length>2?`${head} <span class="muted">+${fmtNum(sorted.length-2)}</span>`:head;
      };
      const audiences=brief(card.rows.flatMap(row=>split(row.target_audience)));
      const teams=brief(card.rows.map(row=>row.lead_team||row.lead));
      const title=card.campaign&&card.campaign!==card.id?card.campaign:card.id;
      // The name cell is a real button, the row is mouse convenience -- the
      // same split C4 established for the activity table. Making the whole <tr>
      // the only target left this table unreachable by keyboard entirely, and
      // focus could not return to it on close because a <tr> takes no focus.
      return `<tr data-pack-open="${esc(card.id)}">
        <td class="pack-name-cell"><button type="button" class="name-btn" data-pack-open="${esc(card.id)}">${esc(title)}</button><div class="list-meta">${esc(card.id)} · ${plural(card.activities,'activity','activities')}</div></td>
        <td class="pack-channel-cell">${channelCell}</td>
        <td class="pack-window-cell">${fmtDate(card.firstDate)} – ${fmtDate(card.lastDate)}</td>
        <td>${audiences}</td>
        <td>${teams}</td>
        <td><span class="badge ${gaps?'warning':'success'}">${gaps?fmtNum(gaps)+' incomplete':'Complete'}</span></td>
      </tr>`;
    };
    document.getElementById('packs-list').innerHTML=shown.length
      ? `<div class="table-wrap"><table class="pack-list-table"><thead><tr><th>Pack</th><th>Channels</th><th>Window</th><th>Audiences</th><th>Lead teams</th><th>Readiness</th></tr></thead><tbody>${shown.map(packRow).join('')}</tbody></table></div>`
      : emptyState(EMPTY_ICONS.layers,'No packs match that','Clear the search or pick another campaign.');

  }

  // Renders the sync-runs portion of the "Refresh & reconciliation" card from
  // state.syncRun: null (fetch failed or endpoint missing), {status:'never_synced'}
  // (endpoint reachable, no sync has ever run), or a full sync-run record.
  function syncRunSummaryHtml() {
    const sync = state.syncRun;
    if (!sync) {
      return `<div class="metric-line"><span>Source sync</span><strong>Status unavailable</strong></div>`;
    }
    if (sync.status === 'never_synced') {
      return `<div class="metric-line"><span>Source sync</span><strong>No source sync yet</strong></div>`;
    }
    const lines = [
      `<div class="metric-line"><span>Last source sync</span><strong>${esc(String(sync.ran_at))}</strong></div>`,
      `<div class="metric-line"><span>Sync summary</span><strong>+${fmtNum(sync.created)} new · ${fmtNum(sync.updated)} updated · ${fmtNum(sync.conflicts)} conflicts · ${fmtNum(sync.local_only)} local-only</strong></div>`,
    ];
    if (sync.conflicts > 0) {
      lines.push(`<div class="notice warn"><strong>${fmtNum(sync.conflicts)} source conflicts overrode local edits (source wins).</strong></div>`);
    }
    return lines.join('');
  }

  // Intake cohorts, moved here from the Overview. The stock figures in this page
  // cannot move without a nightly snapshot; the flow can, because
  // source_created_at says when each activity entered the plan. "Are the records
  // we take in getting better" is both answerable and the more useful question
  // -- a backlog shrinks only once intake stops adding to it. It belongs beside
  // the other trust measures, not on the planner's screen: a planner acts on the
  // records in front of them, a data steward asks whether the inflow is healthy.
  //
  // Intake follows the range filter, but a cohort cannot be created in the
  // future -- with no range that means the last 30 days, not the next 30.
  function renderIntakeQuality() {
    const host = document.getElementById('intake-quality');
    if (!host) return;
    const now = new Date();
    const win = A.comparisonWindow(state.dateFrom, state.dateTo, now, 30);
    const cur = win.active
      ? win.current
      : {from: new Date(new Date(now).setDate(now.getDate()-30)), to: now};
    const span = Math.max(1, cur.to - cur.from);
    const prev = {from: new Date(cur.from.getTime()-span), to: cur.from};
    const nowSet = A.createdBetween(state.snapshotRows, cur.from, cur.to);
    const prevSet = A.createdBetween(state.snapshotRows, prev.from, prev.to);
    const pct = (part, whole) => whole ? Math.round(part/whole*100) : null;
    const completeShare = set => pct(set.filter(row=>A.planningCompleteness(row).score===100).length, set.length);
    // Stated so that up is always good. A reader shown "−14 worse" next to
    // "−10 better" has to work out the polarity of each measure before the
    // numbers mean anything. Packless share becomes packed share, not the
    // other way round.
    const packedShare = set => pct(set.filter(row=>nonempty(row.campaign)||nonempty(row.communication_pack_cpid)||nonempty(row.communication_pack)).length, set.length);
    const delta = (current, prior) => {
      if (!prevSet.length || current===null || prior===null || current===prior) return '';
      const diff = current - prior;
      return `<span class="kpi-trend ${diff>0?'up':'down'}">${diff>0?'+':'−'}${fmtNum(Math.abs(diff))} ${diff>0?'better':'worse'}</span>`;
    };
    if (!nowSet.length) {
      host.innerHTML = emptyState(EMPTY_ICONS.barChart,'No activities arrived in this window','Intake quality compares the records created in the selected period against the period before it.');
      return;
    }
    const cs = completeShare(nowSet), ps = packedShare(nowSet);
    host.innerHTML = `<div class="kpi-grid">`
      + kpi('Complete on intake', cs===null?'—':`${cs}%`, `${fmtNum(nowSet.length)} new records`, cs!==null&&cs<100?'warning':'success', '', delta(cs, completeShare(prevSet)))
      + kpi('New with a pack', ps===null?'—':`${ps}%`, `${fmtNum(nowSet.length)} new records`, ps!==null&&ps<100?'warning':'success', '', delta(ps, packedShare(prevSet)))
      + `</div><p class="kpi-footnote">Compared against the ${plural(win.spanDays,'day')} before this window${prevSet.length?'':' — which hold no records, so no comparison is shown'}.</p>`;
  }

  function renderDataQuality() {
    renderIntakeQuality();
    const q=A.dataQuality(state.rows),generated=state.meta&&(state.meta.generated_at_iso||state.meta.generated_at)||'Unknown';
    document.getElementById('quality-kpis').innerHTML=[kpi('Complete records',`${q.completenessRate}%`,`${q.incomplete} incomplete`,q.incomplete?'warning':'success'),kpi('Duplicate IDs',q.duplicateTrackingIds,'Unique duplicated identifiers',q.duplicateTrackingIds?'danger':'success'),kpi('Missing IDs',q.missingTrackingIds,'Cannot safely edit',q.missingTrackingIds?'danger':'success'),kpi('Invalid dates',q.invalidDateRanges,'End before start',q.invalidDateRanges?'danger':'success')].join('');
    document.getElementById('quality-diagnostics').innerHTML=[['Missing campaign / pack',q.missingPackIds],['Incomplete planning records',q.incomplete],['Duplicate tracking IDs',q.duplicateTrackingIds],['Missing tracking IDs',q.missingTrackingIds],['Invalid date ranges',q.invalidDateRanges]].map(([label,value])=>`<div class="metric-line"><span>${esc(label)}</span><strong>${fmtNum(value)}</strong></div>`).join('');
    document.getElementById('reconciliation').innerHTML=`<div class="metric-line"><span>API refresh</span><strong>${esc(String(generated))}</strong></div><div class="metric-line"><span>${esc(backendLabel())} rows</span><strong>${fmtNum(state.snapshotRows.length)}</strong></div><div class="metric-line"><span>Write adapter</span><strong>${esc(backendLabel())} REST API</strong></div>${syncRunSummaryHtml()}<div class="notice"><strong>Versioned writes:</strong> stale updates are rejected with HTTP 409 and must be reviewed against the current database record.</div>`;
  }

  function updateActivitiesCount() {
    document.getElementById('activities-count').textContent = fmtNum(state.rows.length);
  }

  // Every queue lands on Activities. Scheduling conflicts are no longer among
  // them -- see renderOverview for why they are on ice.
  function setQueueFilter(queue) {
    state.queueFilter=queue;
    document.getElementById('activity-readiness').value='';
    showPage('activities');
    applyActivityFilters();bindOpenRows();bindDuplicateButtons();
  }

  function renderAll() {
    refreshRows(); refreshChannelOrder(); renderOverview(); renderBoard(); renderCalendar(); renderCapacity(); populateActivityFilters(); applyActivityFilters(); renderPacks(); renderPlanningHealth(); renderStrategic(); renderDataQuality(); updateActivitiesCount(); bindOpenRows(); bindDuplicateButtons();
  }

  function bindOpenRows() {
    document.querySelectorAll('[data-open-id]').forEach(el=>{
      // Table rows keep data-open-id as a mouse-click convenience only: the
      // row itself is no longer a keyboard/AT stop (C4) — the in-row
      // name-btn is the real accessible control. Every other data-open-id
      // element (overview/board/calendar/conflict rows) has no inner
      // control yet, so it keeps the tabindex/role treatment.
      if (el.tagName !== 'TR') {
        el.setAttribute('tabindex','0');
        el.setAttribute('role','button');
      }
      const activate=()=>{const key=String(el.dataset.openId);const row=state.rows.find(item=>String(item.id)===key);if(row)openDrawer(row,el);};
      // A click on the name-btn bubbles up to its parent <tr>, which is also
      // bound here — stopPropagation avoids opening the same drawer twice
      // (same guard bindDuplicateButtons uses for its icon button).
      el.onclick=event=>{if(el.tagName==='BUTTON')event.stopPropagation();activate();};
      el.onkeydown=event=>{if(event.key==='Enter'||event.key===' '||event.key==='Spacebar'){event.preventDefault();activate();}};
    });
  }

  function bindDuplicateButtons() {
    document.querySelectorAll('[data-duplicate-id]').forEach(btn=>{
      btn.onclick=event=>{
        event.stopPropagation();
        const row=state.rows.find(item=>String(item.id)===String(btn.dataset.duplicateId));
        if(row)openDuplicateDrawer(row,btn);
      };
      // Enter/Space on the button must not bubble into the row's open handler.
      btn.onkeydown=event=>event.stopPropagation();
    });
  }

  function form() { return document.getElementById('activity-form'); }

  function multiselectContainers() { return Array.from(document.querySelectorAll('[data-multiselect]')); }
  function msContainer(name) { return document.querySelector(`[data-multiselect="${name}"]`); }
  function msHidden(container) { return container.querySelector('input[type=hidden]'); }
  function msValues(container) { return split(msHidden(container).value); }

  function msUpdateTrigger(container) {
    const label=FIELD_LABELS[container.dataset.multiselect]||'options';
    const emptyLabel=`Select ${label}…`;
    const values=msValues(container),valueEl=container.querySelector('.ms-value'),trigger=container.querySelector('.ms-trigger');
    if(!values.length){valueEl.textContent=emptyLabel;valueEl.classList.add('placeholder');trigger.setAttribute('aria-label',emptyLabel);return;}
    valueEl.classList.remove('placeholder');
    const joined=values.join(', ');
    const summary=(values.length<=3&&joined.length<=32)?joined:`${values.length} selected`;
    valueEl.textContent=summary;
    trigger.setAttribute('aria-label',`${label}: ${summary}`);
  }

  function msRender(container, options) {
    const selected=msValues(container),all=options.slice();
    selected.forEach(value=>{if(!all.includes(value))all.push(value);});
    container.querySelector('.ms-options').innerHTML=all.length?all.map(value=>`<label class="ms-option"><input type="checkbox" value="${esc(value)}"${selected.includes(value)?' checked':''}><span>${esc(value)}</span></label>`).join(''):'<div class="ms-empty">No options available</div>';
    const filter=container.querySelector('.ms-filter');
    filter.style.display=all.length>10?'block':'none';
    if(all.length<=10)filter.value='';
    msFilter(container,filter.value);
    msUpdateTrigger(container);
  }

  function msFilter(container, term) {
    const query=String(term||'').trim().toLowerCase();
    container.querySelectorAll('.ms-option').forEach(opt=>{opt.style.display=opt.textContent.toLowerCase().includes(query)?'flex':'none';});
  }

  function closeMsPopover(container) {
    container.querySelector('.ms-popover').hidden=true;
    container.querySelector('.ms-trigger').setAttribute('aria-expanded','false');
  }

  function openMsPopover(container) {
    multiselectContainers().forEach(other=>{if(other!==container)closeMsPopover(other);});
    container.querySelector('.ms-popover').hidden=false;
    container.querySelector('.ms-trigger').setAttribute('aria-expanded','true');
    const filter=container.querySelector('.ms-filter');
    if(filter.style.display!=='none')filter.focus();
  }

  function setMultiselectEnabled(container, enabled) {
    container.querySelector('.ms-trigger').disabled=!enabled;
    if(!enabled)closeMsPopover(container);
  }

  function wireMultiselects() {
    multiselectContainers().forEach(container=>{
      const trigger=container.querySelector('.ms-trigger');
      trigger.setAttribute('aria-haspopup','listbox');
      trigger.setAttribute('aria-expanded','false');
      trigger.onclick=()=>{if(trigger.disabled)return;const pop=container.querySelector('.ms-popover');if(pop.hidden)openMsPopover(container);else closeMsPopover(container);};
      container.querySelector('.ms-options').addEventListener('change',()=>{
        const checked=Array.from(container.querySelectorAll('.ms-option input:checked')).map(input=>input.value);
        msHidden(container).value=checked.join('; ');
        msUpdateTrigger(container);
        if(state.editing){state.dirty=true;updateReady();}
      });
      container.querySelector('.ms-filter').addEventListener('input',event=>msFilter(container,event.target.value));
    });
  }

  function renderMultiselectOptions() {
    MULTISELECT_FIELDS.forEach(name=>msRender(msContainer(name),distinctValues(name)));
  }

  function distinctValues(field) { return countBy(state.rows,field).map(pair=>pair[0]); }

  function distinctChannels(sourceType) {
    const counts=new Map();
    state.rows.filter(row=>row.source_type===sourceType).forEach(row=>split(row.channel).forEach(value=>counts.set(value,(counts.get(value)||0)+1)));
    return Array.from(counts.entries()).sort((a,b)=>b[1]-a[1]).map(pair=>pair[0]);
  }

  function fillSelectOptions(name, values, placeholder) {
    const el=form().elements[name],current=el.value;
    el.innerHTML=`<option value="">${esc(placeholder)}</option>`+values.map(value=>`<option value="${esc(value)}">${esc(value)}</option>`).join('');
    if(current&&values.includes(current))el.value=current;
  }

  function fillDatalist(id, values) {
    document.getElementById(id).innerHTML=values.map(value=>`<option value="${esc(value)}"></option>`).join('');
  }

  function populateSelectOptions(sourceType) {
    fillSelectOptions('channel',distinctChannels(sourceType),'Select channel…');
    fillSelectOptions('target_audience',distinctValues('target_audience'),'Select…');
    fillSelectOptions('audience',AUDIENCE_BANDS,'Select…');
    fillDatalist('dl-campaign',distinctValues('campaign'));
    fillDatalist('dl-business_area',distinctValues('business_area'));
    fillDatalist('dl-lead_team',distinctValues('lead_team'));
    fillDatalist('dl-partner_team',distinctValues('partner_team'));
  }

  // "Belongs to": one selector over existing packs and campaigns replaces the
  // circular campaign/pack free-text pair in single-activity mode. The API
  // fields (campaign, communication_pack_cpid) live on as hidden inputs the
  // selector writes into, so save/create payloads are unchanged.
  function renderBelongsToOptions() {
    const sel=document.getElementById('belongs-to');
    const packs=distinctValues('communication_pack_cpid').filter(value=>value!==STANDALONE_PACK_PREFIX);
    const campaigns=distinctValues('campaign');
    sel.innerHTML='<option value="">— None</option>'
      +(packs.length?`<optgroup label="Packs">${packs.map(value=>`<option value="pack::${esc(value)}">${esc(value)}</option>`).join('')}</optgroup>`:'')
      +(campaigns.length?`<optgroup label="Campaigns">${campaigns.map(value=>`<option value="camp::${esc(value)}">${esc(value)}</option>`).join('')}</optgroup>`:'')
      +'<option value="new">New campaign…</option>';
  }

  function syncBelongsToFromFields() {
    renderBelongsToOptions();
    const sel=document.getElementById('belongs-to');
    const cpid=String(form().elements.communication_pack_cpid.value||'').trim();
    const camp=String(form().elements.campaign.value||'').trim();
    const inject=value=>{
      if(!Array.from(sel.options).some(opt=>opt.value===value)){
        const opt=document.createElement('option');
        opt.value=value;opt.textContent=value.slice(6);
        sel.appendChild(opt);
      }
    };
    if(cpid&&cpid!==STANDALONE_PACK_PREFIX){inject(`pack::${cpid}`);sel.value=`pack::${cpid}`;}
    else if(camp){inject(`camp::${camp}`);sel.value=`camp::${camp}`;}
    else sel.value='';
    document.getElementById('belongs-new-label').hidden=true;
  }

  function applyVariant(sourceType) {
    // Invariant: currentSourceType() (the toggle) must always agree with the
    // variant actually applied to the form -- edit mode keeps the toggle
    // hidden, but missingRequiredFields()/attemptSave() still read it.
    setSourceToggle(sourceType);
    const internal=sourceType==='internal';
    document.querySelectorAll('#activity-form [data-variant="internal"]').forEach(el=>{el.hidden=!internal;});
    document.querySelectorAll('#activity-form [data-vreq]').forEach(el=>{el.hidden=!internal;});
    // P11: forward-framed per variant (kit rule -- describe what the current
    // choice does, not what the other one lacks). Text per prototype setSource.
    const variantHelp=document.querySelector('.variant-help');
    if(variantHelp)variantHelp.textContent=internal
      ?'Internal also captures audience size and news-digest consideration.'
      :'External runs without the audience-size and news-digest fields.';
  }

  function currentSourceType() {
    const active=document.querySelector('#source-toggle button.active');
    return active?active.dataset.source:'internal';
  }

  function setSourceToggle(source) {
    document.querySelectorAll('#source-toggle button').forEach(btn=>btn.classList.toggle('active',btn.dataset.source===source));
  }

  function currentScope() {
    const active=document.querySelector('#scope-toggle button.active');
    return active?active.dataset.scope:'single';
  }

  // Resolving the target and acting on it are separate so the highlight is
  // applied once, at the end, for every branch.
  function fieldElement(name) {
    // T5: pack gap tokens land inside the pack UI -- a row token targets that
    // channel row's input, the channel token the first checkbox.
    const token=PACK_ROW_TOKEN_RE.exec(name||'');
    if(token){
      const rowEl=document.querySelector(`#pack-rows .pack-row[data-channel="${CSS.escape(token[1])}"]`);
      const input=rowEl&&rowEl.querySelector(`[data-pack-${token[2]}]`);
      if(input)return input;
    }
    if(name==='pack_channels')return document.querySelector('#pack-channels input');
    const container=msContainer(name);
    if(container)return container.querySelector('.ms-trigger');
    return form().elements[name]||null;
  }

  // Focus alone is too quiet in a form this dense: the field is centred in the
  // drawer and pulsed once so the jump is visible even mid-form.
  function highlightField(el) {
    const box=el.closest('.f-label,.ms-field,.pack-row')||el;
    // .drawer-head-wrap is sticky and scrollIntoView knows nothing about it --
    // without this, block:'center' can land the field underneath it (a title
    // long enough to wrap grows the wrap tall enough to fully cover a
    // mid-form field). Measured fresh on every jump, from the DOM, never
    // hardcoded: the wrap's height depends on whether the title has
    // wrapped, which varies per record -- a fixed pixel offset was tried
    // and removed once already for exactly this reason (see git history).
    const headWrap=document.querySelector('.drawer-head-wrap');
    box.style.scrollMarginTop=headWrap?`${headWrap.getBoundingClientRect().height}px`:'';
    box.scrollIntoView({block:'center'});
    box.classList.remove('pulse');
    // Force a reflow, or re-jumping to the same field never restarts the
    // animation -- the class would be removed and re-added within one frame.
    void box.offsetWidth;
    box.classList.add('pulse');
    box.addEventListener('animationend',()=>box.classList.remove('pulse'),{once:true});
  }

  function focusField(name) {
    const el=fieldElement(name);
    if(!el)return;
    if(typeof el.focus==='function')el.focus();
    highlightField(el);
  }

  // --- I3/C2/C3: live readiness, draft save, single source of truth ------
  // Missing-field computation derives ONLY from REQUIRED_INTERNAL/EXTERNAL --
  // never a second list (ready-line, draft modal and the detail-head notice
  // all funnel through missingRequiredFields()/missingRequiredForRow() below).
  function formValue(name) {
    const el=form().elements[name];
    return el?String(el.value||'').trim():'';
  }

  // T5: pack-scope gap tokens. pack_name is a real form field; the other
  // two shapes (pack_channels, pack_row:<channel>:<col>) are synthetic --
  // missingFieldLabel() gives them user-facing labels for the draft modal
  // and focusField() knows how to land on them, so the ready-line, draft
  // modal and submit gate all speak pack through the one existing funnel.
  const PACK_ROW_TOKEN_RE = /^pack_row:(.+):(name|start|end)$/;
  const PACK_ROW_COL_LABELS = {name:'activity name', start:'start date', end:'end date'};

  function missingFieldLabel(name) {
    if (name==='pack_channels') return 'At least one channel';
    const token=PACK_ROW_TOKEN_RE.exec(name);
    if (token) return `${token[1]} — ${PACK_ROW_COL_LABELS[token[2]]}`;
    return FIELD_LABELS[name]||name;
  }

  // T5 seam: pack scope's own gaps -- pack name, channel selection, and the
  // per-channel row fields that replace the single-scope name/dates
  // (missingRequiredFields filters PACK_ROW_FIELDS while packing). Never a
  // second required-fields list: REQUIRED_INTERNAL/EXTERNAL stay the source
  // of truth for the shared fields, this only adds what packs it.
  function missingExtra() {
    if (!state.packing) return [];
    const extra=[];
    if (!formValue('pack_name')) extra.push('pack_name');
    const rows=packRowValues();
    if (!rows.length) extra.push('pack_channels');
    rows.forEach(row=>{
      if (!row.name.trim()) extra.push(`pack_row:${row.channel}:name`);
      if (!row.start) extra.push(`pack_row:${row.channel}:start`);
      if (!row.end) extra.push(`pack_row:${row.channel}:end`);
    });
    return extra;
  }

  function missingRequiredFields() {
    const sourceType=currentSourceType();
    const required=(sourceType==='internal'?REQUIRED_INTERNAL:REQUIRED_EXTERNAL)
      .filter(name=>!(state.packing&&PACK_ROW_FIELDS.includes(name)));
    return required.filter(name=>!nonempty(formValue(name))).concat(missingExtra());
  }

  // Same source of truth, applied to a persisted row instead of the live
  // form -- used for the post-save toast wording and the read-only detail
  // view's "Saved as draft" notice (P13). Delegates to the exact function the
  // table badge / KPI / filter use, so a row's draft status reads identically
  // in the list and in the drawer.
  function missingRequiredForRow(row) {
    return A.planningCompleteness(row).missing;
  }

  function paintMissing(missingNames) {
    document.querySelectorAll('.f-label[data-f],.ms-field[data-f]').forEach(el=>{
      el.classList.toggle('missing',missingNames.includes(el.dataset.f));
    });
    // Pack rows paint per cell -- the token carries channel + column, so a
    // failed pack submit marks exactly the empty inputs in the pack-table.
    document.querySelectorAll('#pack-rows .pack-row').forEach(rowEl=>{
      ['name','start','end'].forEach(col=>{
        const input=rowEl.querySelector(`[data-pack-${col}]`);
        if(input)input.classList.toggle('missing',missingNames.includes(`pack_row:${rowEl.dataset.channel}:${col}`));
      });
    });
  }

  function clearMissingPaint() {
    document.querySelectorAll('.f-label.missing,.ms-field.missing,#pack-rows .missing').forEach(el=>el.classList.remove('missing'));
  }

  // Runs on every input/change (including multiselects) while the form is
  // active (create or edit -- state.editing covers both, see openCreateDrawer).
  // Only paints .missing once an attempt has actually failed (state.showErrors),
  // so opening a blank create drawer is not greeted with a wall of red.
  function updateReady() {
    if (!state.editing) return [];
    const missing=missingRequiredFields();
    const line=document.getElementById('ready-line'),text=document.getElementById('ready-text');
    line.classList.toggle('ready',missing.length===0);
    // Shared gaps and per-row gaps are different work and are counted apart.
    // Merged, a four-channel pack with every shared field filled still read
    // "12 required fields left" -- true, and useless: it cannot tell the one
    // field the whole pack is waiting on from a date missing on a single row.
    // The shared half gates everything; the row half is per-line work the
    // table itself marks.
    const rowMissing=state.packing?missing.filter(name=>String(name).startsWith('pack_row:')):[];
    const sharedMissing=missing.length-rowMissing.length;
    const rowChannels=new Set(rowMissing.map(name=>String(name).split(':')[1])).size;
    text.textContent=missing.length
      ?(state.packing&&rowMissing.length
        ? `Shared: ${sharedMissing?plural(sharedMissing,'field')+' left':'complete'} · Rows: ${plural(rowMissing.length,'field')} across ${plural(rowChannels,'channel')}`
        : `${plural(missing.length,'required field')} left`)
      :(state.creating?'Ready to create':'Ready to save');
    if (state.showErrors) paintMissing(missing);
    // C1: pack scope's CTA count and pre-save summary ride the same funnel
    // as the ready-line, so every input/change keeps all three in step.
    if (state.packing){updatePackCta();renderPackSummary();}
    return missing;
  }

  function populateDrawerForm(row) {
    Array.from(form().elements).forEach(el=>{
      if(!el.name)return;
      if(el.type==='checkbox'){el.checked=!!row[el.name];return;}
      const value=(el.type==='datetime-local'?isoLocal(row[el.name]):row[el.name])||'';
      if(el.tagName==='SELECT'){
        Array.from(el.querySelectorAll('option[data-injected]')).forEach(opt=>opt.remove());
        if(value&&!Array.from(el.options).some(opt=>opt.value===value)){
          const extra=document.createElement('option');
          extra.value=value;extra.textContent=value;extra.dataset.injected='true';
          el.appendChild(extra);
        }
      }
      el.value=value;
    });
  }

  function resetCreateForm() {
    Array.from(form().elements).forEach(el=>{
      if(!el.name)return;
      if(el.tagName==='SELECT')Array.from(el.querySelectorAll('option[data-injected]')).forEach(opt=>opt.remove());
      if(el.type==='checkbox')el.checked=false;
      else if(el.name==='time_zone')el.value='Europe/Zurich';
      else el.value='';
    });
  }

  function drawerFocusables() {
    const panel=document.querySelector('.drawer-panel');
    return Array.from(panel.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')).filter(el=>el.offsetParent!==null);
  }

  const historyValue = value => (value===null||value===undefined) ? '—' : String(value);
  const actorLabel = actor => HISTORY_ACTOR_LABELS[actor] || actor;

  function historyDetailText(entry) {
    if (entry.change_type === 'created') return 'Created';
    const label = FIELD_LABELS[entry.field] || entry.field || 'Field';
    return `${label}: ${historyValue(entry.old_value)} → ${historyValue(entry.new_value)}`;
  }

  function renderHistoryEntries(items, total) {
    const body = document.getElementById('history-body');
    if (!items.length) {
      body.innerHTML = emptyState(EMPTY_ICONS.layers, 'No history yet', 'Changes to this activity will appear here.');
      return;
    }
    const shown = items.slice(0, HISTORY_LIMIT);
    const rows = shown.map(entry => `<div class="history-entry"><div class="history-meta"><span class="history-when">${esc(fmtDateTime(entry.changed_at))}</span><span class="history-actor">${esc(actorLabel(entry.actor))}</span></div><div class="history-detail">${esc(historyDetailText(entry))}</div></div>`).join('');
    const remaining = total - shown.length;
    const more = remaining > 0 ? `<div class="history-more">${fmtNum(remaining)} earlier changes not shown</div>` : '';
    body.innerHTML = rows + more;
  }

  // Fetched lazily every time the drawer opens on an existing activity (never
  // for the create-activity drawer, which has no id yet) -- this also covers
  // "re-fetched after save" for free, since commitEditPatch/commitCreate
  // (I5) reopen read-only via openDrawer -> loadHistory again rather than
  // closing the drawer.
  async function loadHistory(activityId) {
    const body = document.getElementById('history-body');
    body.innerHTML = '<div class="history-loading">Loading history…</div>';
    try {
      const result = await repository.getActivityChanges(activityId);
      renderHistoryEntries(result.items, result.total);
    } catch (error) {
      body.innerHTML = emptyState(EMPTY_ICONS.alertTriangle, 'History unavailable', error.message);
    }
  }

  function setDrawerTracking(row, editing) {
    const el=document.getElementById('drawer-tracking');
    // The edit rule the API guarantees: PATCH never regenerates tracking_id,
    // so the ID minted at creation survives every edit — downstream reports
    // keyed to it keep working. Stated here because this is the one question
    // that decides whether an edit is safe.
    const rule=editing?'<span class="tid-rule">Fixed at creation — changing channel or dates does not re-issue this ID; downstream reports keep working</span>':'';
    // State beside the identifier, the way the prototype puts its status badge
    // next to the tracking ID. The studio has no status field, so the honest
    // equivalent is readiness -- the same completeness rule the table's Issue
    // column and the Overview queue already use, never a second judgement. It
    // is dropped while creating, where "0 of N fields" is noise and the footer
    // ready-line already counts.
    const missing=row&&row.id?missingRequiredForRow(row):[];
    const badge=row&&row.id
      ?`<span class="badge ${missing.length?'warning':'success'}">${missing.length?plural(missing.length,'field')+' missing':'Complete'}</span>`
      :'';
    if (row&&nonempty(row.tracking_id)) {
      el.innerHTML=`<div class="tracking-row"><span class="tracking-label">Tracking ID</span>${trackingIdHtml(row.tracking_id,{copy:true})}<span class="tid-help" title="${esc(TRACKING_ID_TITLE)}">i</span>${badge}</div>${rule}`;
    } else {
      el.innerHTML=`<div class="tracking-row"><span class="tracking-label">Tracking ID</span><span class="tracking-id">${esc(row?'No tracking ID':'Generated on save')}</span></div>`;
    }
  }

  // Read-only mode renders a plain label–value detail view instead of a
  // disabled form; "— Add" jumps straight into edit mode at that field.
  const DETAIL_SECTIONS = [
    {title:'Identity', fields:[['campaign','Campaign'],['communication_pack','Communication pack'],['tracking_pack_id','Pack ID']]},
    {title:'Classification', fields:[['channel','Channel'],['priority','Priority'],['strategic_objectives','Communications pillars']]},
    {title:'Content', fields:[['activity_description','Description']]},
    {title:'Audience', fields:[['target_audience','Target audience'],['audience','Estimated audience size']]},
    {title:'Organisation', fields:[['business_division','Business division'],['business_area','Business area'],['region','Region']]},
    {title:'Schedule', fields:[['start_date','Start'],['end_date','End'],['time_zone','Time zone']]},
    {title:'Ownership', fields:[['lead','Lead'],['lead_team','Lead team'],['partner_team','Partner team']]}
  ];
  const EDITABLE_DETAIL_FIELDS = new Set(['campaign','channel','priority','strategic_objectives','activity_description','target_audience','audience','business_division','business_area','region','start_date','end_date','time_zone','lead','lead_team','partner_team']);

  function renderDetailView(row) {
    const external=row.source_type!=='internal';
    const sections=DETAIL_SECTIONS.map(section=>{
      const rowsHtml=section.fields.filter(([field])=>!(external&&(field==='audience'||field==='business_division'))).map(([field,label])=>{
        let value=row[field];
        if(field==='start_date'||field==='end_date')value=nonempty(value)?fmtDateTime(value):null;
        // A standalone prefix is not pack membership — showing "Pack ID:
        // STA-0000000" under "Communication pack: —" reads as contradiction.
        if(field==='tracking_pack_id'&&(!nonempty(value)||value===STANDALONE_PACK_PREFIX))return '';
        const has=nonempty(value);
        const editable=EDITABLE_DETAIL_FIELDS.has(field)&&row.id&&canEditActivity(row);
        // P13: filled + editable rows get a hover/focus-revealed Edit button;
        // empty + editable rows keep the "— Add" affordance; both share the
        // same data-edit-field mechanism (extends the former data-add-field-
        // only wiring) and gate on the same canEditActivity() check, so
        // viewers/foreign-row contributors get neither affordance.
        // The channel reads as a swatch here too. A value that is colour-coded
        // in the table and plain text in the drawer teaches the reader that the
        // colour means nothing.
        const shown=field==='channel'&&has?channelTag(value):esc(String(value));
        const display=has
          ?`${shown}${editable?`<button type="button" class="row-edit" data-edit-field="${esc(field)}">Edit</button>`:''}`
          :(editable?`<button type="button" class="detail-add" data-edit-field="${esc(field)}">— Add</button>`:'—');
        return `<div class="detail-row"><dt>${esc(label)}</dt><dd>${display}</dd></div>`;
      }).join('');
      return rowsHtml?`<div class="detail-section"><h4>${esc(section.title)}</h4><dl>${rowsHtml}</dl></div>`:'';
    }).join('');
    const digest=row.source_type==='internal'?`<div class="detail-section"><h4>Visibility</h4><dl><div class="detail-row"><dt>News digest</dt><dd>${row.news_digest?'Considered':'Not considered'}</dd></div></dl></div>`:'';
    // C2/I4: the read-only reopen after a draft save names the gap instead
    // of silently looking "done" -- same REQUIRED_INTERNAL/EXTERNAL source
    // of truth as updateReady(), never a second list.
    const missing=missingRequiredForRow(row);
    const head=missing.length?`<div class="notice warn"><strong>Saved as draft.</strong> ${missing.length} required field${missing.length===1?'':'s'} outstanding.</div>`:'';
    document.getElementById('detail-view').innerHTML=head+sections+digest;
    document.getElementById('detail-view').querySelectorAll('[data-edit-field]').forEach(btn=>{
      btn.onclick=()=>{setDrawerEditing(true);focusField(btn.dataset.editField);};
    });
  }

  function openDrawer(row, opener, options) {
    const opts=options||{};
    state.selected=row;state.editing=false;state.creating=false;state.packing=false;state.drawerOpener=opener||document.activeElement;
    const sourceType=row.source_type||'internal';
    document.getElementById('drawer-eyebrow').textContent='Activity detail';
    document.getElementById('drawer-title').textContent=row.activity_name||'Untitled activity';
    setDrawerTracking(row);
    document.getElementById('drawer-note').hidden=true;
    document.getElementById('prefill-note').hidden=true;
    document.getElementById('drawer-mode').hidden=false;
    hideConflictBanner();
    document.getElementById('form-variant').hidden=true;
    setPackMode(false);
    applyVariant(sourceType);
    populateSelectOptions(sourceType);
    populateDrawerForm(row);
    syncBelongsToFromFields();
    renderMultiselectOptions();
    renderDetailView(row);
    setDrawerEditing(false);
    document.getElementById('activity-drawer').classList.add('open');
    document.getElementById('activity-drawer').setAttribute('aria-hidden','false');
    if (opts.edit&&row.id) {
      setDrawerEditing(true);
      if (opts.focus) focusField(opts.focus); else document.getElementById('drawer-close').focus();
    } else {
      document.getElementById('drawer-close').focus();
    }
    if (row.id) loadHistory(row.id);
  }

  function prepareCreateChrome(title, note) {
    // I3/C3: a fresh create/duplicate session starts with no failed-submit
    // state -- any .missing paint left over from a previous session in this
    // same (reused) drawer DOM must not bleed into this one.
    state.showErrors=false;
    clearMissingPaint();
    clearCreateAnotherButton();
    renderIssueJump(false);
    // Width belongs to pack scope. Duplicate is always single-scope and never
    // touches setScope, so clear the pack-width class here (shared by both
    // create callers) or a prior pack session leaks its 920px into the
    // single-activity duplicate drawer; openCreateDrawer's setScope re-widens.
    document.getElementById('activity-drawer').classList.remove('wide');
    document.getElementById('drawer-eyebrow').textContent='Create';
    document.getElementById('drawer-title').textContent=title;
    setDrawerTracking(null);
    const noteEl=document.getElementById('drawer-note');
    noteEl.textContent=note||'';
    noteEl.hidden=!note;
    document.getElementById('drawer-mode').hidden=true;
    hideConflictBanner();
    document.getElementById('detail-view').hidden=true;
    form().hidden=false;
    document.querySelector('.drawer-actions').style.display='grid';
    document.getElementById('form-validation').textContent='';
    document.getElementById('form-variant').hidden=false;
    // I1/T3-review: scope choice only makes sense while creating a
    // genuinely NEW activity -- an existing activity has already committed
    // to single or pack at creation time, and openDuplicateDrawer has no
    // reset path for the pack DOM (#pack-channels/#pack-rows survive
    // closeDrawer). So #scope-row stays HIDDEN here by default -- shared by
    // both create callers -- and only openCreateDrawer opts back in, right
    // next to its own setScope('single'). Duplicate therefore can never
    // reach pack mode and revive a stale pack session (old channels, old
    // row names/dates) under its rewritten "Duplicate of ..." title. Still
    // reset the toggle's visual state to single here (before any caller's
    // own setScope() call, if any) so a stale 'pack' active class from an
    // earlier session cannot leak into whichever caller does end up
    // revealing the row.
    document.querySelectorAll('#scope-toggle button').forEach(btn=>btn.classList.toggle('active',btn.dataset.scope==='single'));
    document.getElementById('scope-row').hidden=true;
    // C2/I3: no version to conflict-check yet; the footer's ready-line
    // (T4-wired) is the relevant signal while creating, not the save-hint.
    document.getElementById('save-hint').hidden=true;
    document.getElementById('ready-line').classList.remove('ready');
    document.getElementById('ready-text').textContent='';
    // C1: the pack CTA disables itself at zero channels -- a fresh create/
    // duplicate session must never inherit that disabled state.
    document.getElementById('drawer-save').disabled=false;
    document.getElementById('drawer-history').hidden=true;
    document.getElementById('pack-summary').hidden=true;
  }

  function openCreateDrawer(opener) {
    state.selected=null;state.creating=true;state.packing=false;state.editing=true;state.dirty=false;state.drawerOpener=opener||document.activeElement;
    state.customChannels=[];
    // I1: single entry point -- title/note are scope-driven now, set by
    // setScope('single') below rather than passed in here.
    prepareCreateChrome('New activity','');
    setSourceToggle('internal');
    resetCreateForm();
    applyVariant('internal');
    populateSelectOptions('internal');
    syncBelongsToFromFields();
    renderMultiselectOptions();
    setFormEnabled(true);
    // Fresh slate for a genuinely new drawer session -- the pack checkbox/row
    // DOM survives closeDrawer, so a previous pack session's selection and
    // row values must not leak into this one. setScope('pack') re-renders
    // non-destructively from here on (mid-session scope toggling keeps ticks).
    document.getElementById('pack-channels').innerHTML='';
    document.getElementById('pack-rows').innerHTML='';
    document.getElementById('pack-channel-new').value='';
    document.getElementById('pack-add-channel-row').hidden=true;
    document.getElementById('fill-start').value='';
    document.getElementById('fill-end').value='';
    // T3-review: only this entry point reveals #scope-row -- it just reset
    // the pack DOM above, so flipping to pack scope from here is safe.
    // prepareCreateChrome (shared with openDuplicateDrawer) leaves it
    // hidden by default; openDuplicateDrawer never opts back in.
    document.getElementById('scope-row').hidden=false;
    setScope('single');
    // I2: prefill from the user's own newest row -- after the blank reset
    // above, so there is nothing stale left in the form for it to clash with.
    applyPrefill();
    document.getElementById('activity-drawer').classList.add('open');
    document.getElementById('activity-drawer').setAttribute('aria-hidden','false');
    form().elements.activity_name.focus();
  }

  const PACK_ROW_FIELDS=['activity_name','channel','start_date','end_date'];

  function setPackMode(on) {
    document.getElementById('pack-section').hidden=!on;
    form().classList.toggle('pack-mode',on);
    document.querySelectorAll('#activity-form [data-single-only]').forEach(el=>{el.hidden=on;});
    document.querySelectorAll('#activity-form [data-pack-only]').forEach(el=>{el.hidden=!on;});
    document.querySelector('.pack-shared-heading').hidden=!on;
    if(!on)document.getElementById('pack-summary').hidden=true;
  }

  // I1: the in-drawer scope toggle is the single switch between the two
  // create shapes -- it drives the existing state.packing machinery
  // (setPackMode's data-single-only/data-pack-only visibility), widens the
  // drawer, and swaps title/note per scope. Non-destructive: re-entering an
  // already-rendered pack scope re-renders from the current DOM/state
  // (packSelectedChannels/packRowValues), it does not clear channel ticks or
  // row edits -- only openCreateDrawer clears pack-channels/pack-rows, once,
  // for a genuinely fresh drawer session.
  function setScope(scope) {
    state.packing=scope==='pack';
    document.querySelectorAll('#scope-toggle button').forEach(btn=>btn.classList.toggle('active',btn.dataset.scope===scope));
    document.getElementById('activity-drawer').classList.toggle('wide',state.packing);
    document.getElementById('drawer-title').textContent=state.packing?'New communication pack':'New activity';
    const noteEl=document.getElementById('drawer-note');
    noteEl.textContent=state.packing
      ?'Pick channels first — each channel becomes one activity with its own tracking ID.'
      :'Single channel, single date — the tracking ID is minted on save from channel and start date.';
    noteEl.hidden=false;
    setPackMode(state.packing);
    if(state.packing){
      renderPackChannels(currentSourceType());
      renderPackRows();
    } else {
      const save=document.getElementById('drawer-save');
      save.textContent='Create activity';
      // A zero-channel pack disables the CTA -- flipping back to single
      // scope must re-arm it.
      save.disabled=false;
    }
    updateReady();
  }

  function packSelectedChannels() {
    return Array.from(document.querySelectorAll('#pack-channels input:checked')).map(input=>input.value);
  }

  function renderPackChannels(sourceType) {
    const all=distinctChannels(sourceType).slice();
    state.customChannels.forEach(channel=>{if(!all.includes(channel))all.push(channel);});
    const selected=packSelectedChannels();
    // Cards, not a checkbox list. Picking channels is the act that builds the
    // pack -- it decides how many activities exist -- and it was carrying the
    // smallest targets in the drawer: a 13px box in a two-column list, the same
    // weight as a "consider for news digest" tick. The card states its status
    // in words as well as in fill, because the house rule is that colour never
    // carries meaning alone, and it shows the tracking-ID segment the channel
    // will contribute, which is the thing the planner is really choosing.
    document.getElementById('pack-channels').innerHTML=all.length
      ?all.map(channel=>{
        const on=selected.includes(channel);
        // cc-state is hidden from assistive tech: the checkbox already
        // announces checked/unchecked, and repeating it in the label would read
        // as "Digital Signage DIG Selected, checked". It exists for the eye,
        // so that selection is not carried by fill alone.
        return `<label class="channel-card${on?' on':''}"><input type="checkbox" value="${esc(channel)}"${on?' checked':''}><span class="cc-name">${esc(channel)}</span><span class="cc-seg" aria-hidden="true">${esc(channelAbbr(channel))}</span><span class="cc-state" aria-hidden="true">${on?'Selected':'Add'}</span></label>`;
      }).join('')
      :'<div class="ms-empty">No channels in the data yet — add one below</div>';
  }

  function packRowValues() {
    return Array.from(document.querySelectorAll('#pack-rows .pack-row')).map(rowEl=>({
      channel:rowEl.dataset.channel,
      name:rowEl.querySelector('[data-pack-name]').value,
      start:rowEl.querySelector('[data-pack-start]').value,
      end:rowEl.querySelector('[data-pack-end]').value,
    }));
  }

  // I6: per-channel rows render as a compact pack-table -- Channel ·
  // Activity name · Start · End · live tracking-ID stub. Values survive
  // re-renders (channel ticks) via packRowValues(); ticking a channel seeds
  // the row name "<pack name> — <channel>" when a pack name exists,
  // otherwise the name stays open and the ready-line/draft rule chase it.
  // The pack-level date a newly ticked channel starts from. Empty is a valid
  // answer -- the planner may not have decided yet -- and then the row is blank
  // exactly as before.
  function packDefault(id) {
    const el=document.getElementById(id);
    return el&&el.value?el.value:'';
  }

  function renderPackRows() {
    const previous=new Map(packRowValues().map(row=>[row.channel,row]));
    const packName=formValue('pack_name');
    const selected=packSelectedChannels();
    const required='<em>(required)</em>';
    document.getElementById('pack-rows').innerHTML=selected.length
      ?`<table class="pack-table"><thead><tr><th>Channel</th><th>Activity name ${required}</th><th>Start ${required}</th><th>End ${required}</th><th title="Sequence number assigned on save">Tracking ID</th></tr></thead><tbody>${selected.map(channel=>{
          const prev=previous.get(channel);
          const name=prev?prev.name:(packName?`${packName} — ${channel}`:'');
          // A channel ticked after the pack dates were set inherits them. Most
          // packs go out on one date and the exceptions are the minority, so
          // the dates are the default and per-row editing is the correction --
          // not the other way round. Without this, "Use for all channels" only
          // ever applied to the rows that happened to exist when it was
          // pressed, and a channel added afterwards came up blank with no hint
          // that it had missed the fill.
          const start=prev?prev.start:packDefault('fill-start');
          const end=prev?prev.end:packDefault('fill-end');
          return `<tr class="pack-row" data-channel="${esc(channel)}"><td class="ch-name">${esc(channel)}</td><td><input data-pack-name value="${esc(name)}" aria-label="Activity name for ${esc(channel)}"></td><td><input type="datetime-local" data-pack-start value="${esc(start)}" aria-label="Start for ${esc(channel)}"></td><td><input type="datetime-local" data-pack-end value="${esc(end)}" aria-label="End for ${esc(channel)}"></td><td class="stub" data-pack-stub></td></tr>`;
        }).join('')}</tbody></table>`
      :'<div class="ms-empty">Tick a channel above and its row appears here.</div>';
    // Visible from the start, not only once rows exist. The dates belong to the
    // pack, not to the rows, and setting them before ticking channels is the
    // faster order: every channel then arrives already dated. Hiding them until
    // a row existed forced the slow order and made "use for all" look like a
    // correction tool rather than the default.
    document.getElementById('pack-fill-down').hidden=false;
    updatePackStubs();
  }

  // The informed commit: live tracking-ID stubs per channel row -- this is
  // where channel + date + pack → ID is learned. The sequence stays "…"
  // until the server assigns it on save (see the pack-table column title).
  function updatePackStubs() {
    if(!state.packing)return;
    const prefix=packIdPrefix();
    document.querySelectorAll('#pack-rows .pack-row').forEach(rowEl=>{
      const channel=rowEl.dataset.channel;
      const start=rowEl.querySelector('[data-pack-start]').value;
      rowEl.querySelector('[data-pack-stub]').innerHTML=`<span class="tracking-id"><span class="tid-prefix">${esc(prefix)}-</span><span class="tid-date">${esc(stubDate(start))}</span>-<span class="tid-seq">…</span>-<span class="tid-channel">${esc(channelAbbr(channel))}</span></span>`;
    });
  }

  // C1: the pre-save summary is a permanent fixture of pack scope -- it
  // narrates exactly what the primary button will do, including the empty
  // state, and always ends on the atomicity promise.
  function renderPackSummary() {
    if(!state.packing)return;
    const summary=document.getElementById('pack-summary');
    summary.hidden=false;
    const rows=packRowValues();
    if(!rows.length){
      summary.innerHTML='<strong>Nothing will be created yet</strong><div class="pack-summary-row"><span>Tick at least one channel to build the pack.</span></div>';
      return;
    }
    const prefix=packIdPrefix(),packName=formValue('pack_name');
    summary.innerHTML=`<strong>${rows.length} ${rows.length===1?'activity':'activities'} will be created${packName?` in "${esc(packName)}"`:''}</strong>`
      +rows.map(row=>`<div class="pack-summary-row"><span>${esc(row.channel)} · ${esc(row.name.trim()||'unnamed')}</span><span class="tracking-id"><span class="tid-prefix">${esc(prefix)}-</span><span class="tid-date">${esc(stubDate(row.start))}</span>-<span class="tid-seq">…</span>-<span class="tid-channel">${esc(channelAbbr(row.channel))}</span></span></div>`).join('')
      +`<span class="atomic">All ${rows.length} are created together, or none of them are.</span>`;
  }

  // C1: count-labelled primary CTA -- "Create N activities", disabled with
  // an instruction label at zero channels. Driven from updateReady() so
  // every input/change keeps the count live.
  function updatePackCta() {
    if(!state.packing)return;
    const save=document.getElementById('drawer-save');
    const count=packSelectedChannels().length;
    save.disabled=count===0;
    save.textContent=count===0?'Select a channel to continue':`Create ${count} ${count===1?'activity':'activities'}`;
  }

  function openDuplicateDrawer(row, opener) {
    const sourceType=row.source_type||'internal';
    state.selected=null;state.creating=true;state.packing=false;state.editing=true;state.dirty=false;state.drawerOpener=opener||document.activeElement;
    prepareCreateChrome(`Duplicate of ${row.activity_name||'Untitled activity'}`,'Dates are cleared on purpose — pick new ones so the fresh tracking ID carries the real start date.');
    document.getElementById('drawer-save').textContent='Create activity';
    setPackMode(false);
    setSourceToggle(sourceType);
    resetCreateForm();
    applyVariant(sourceType);
    populateSelectOptions(sourceType);
    populateDrawerForm(row);
    syncBelongsToFromFields();
    renderMultiselectOptions();
    // A duplicate must not inherit dates verbatim: copied dates are born as
    // "0 days lead time" findings and mint a stale date into the tracking ID.
    form().elements.start_date.value='';
    form().elements.end_date.value='';
    const nameEl=form().elements.activity_name;
    if(nonempty(nameEl.value))nameEl.value=`${nameEl.value} (copy)`;
    setFormEnabled(true);
    // I2: duplicate keeps its own note in the same #prefill-note slot --
    // applyPrefill() is never called here, so it cannot be overwritten.
    // textContent (not innerHTML), so no esc() -- the browser already treats
    // this as plain text, and esc() would show literal escaped entities.
    document.getElementById('prefill-text').textContent=`Copied from "${row.activity_name||'the original activity'}" — dates cleared so nothing ships on a stale date.`;
    document.getElementById('prefill-note').hidden=false;
    document.getElementById('activity-drawer').classList.add('open');
    document.getElementById('activity-drawer').setAttribute('aria-hidden','false');
    updateReady();
    nameEl.focus();nameEl.select();
  }

  function packErrorMessage(message, rows) {
    // Translate pydantic loc paths ("items.1.end_date: ...") into the
    // channel-row language the user sees ("Intranet End date: ...").
    return String(message).replace(/items\.(\d+)\.?([a-z_]*)/g,(match,index,field)=>{
      const row=rows[Number(index)];
      if(!row)return match;
      const label=field?(FIELD_LABELS[field]||field):'';
      return label?`${row.channel} ${label}`:row.channel;
    });
  }

  // I3/I6: the form-submit gate for pack scope -- mirrors attemptSave for
  // the pack shape: block on ANY missing required field (shared fields plus
  // the pack gaps missingExtra() adds), paint, focus the first, hint the
  // draft path. The count-labelled CTA is already disabled at zero
  // channels, but Enter in a field still submits, so the gate re-checks.
  async function submitPack(event) {
    event.preventDefault();
    state.showErrors=true;
    const missing=updateReady();
    if(missing.length){
      focusField(missing[0]);
      document.getElementById('ready-text').textContent=`${missing.length} required field${missing.length===1?'':'s'} left — or use "Save as draft"`;
      return;
    }
    await commitCreatePack(false);
  }

  // Batch commit for both pack paths -- full create (submitPack, nothing
  // missing) and draft (openDraftModal; pack name, channels and row names
  // guaranteed, dates may stay open). Posts whatever is filled per row:
  // only present dates are sent, so the API's nullable date fields stay
  // null for a draft pack. C1's atomicity promise is the API's own -- one
  // POST /api/activities/batch, all rows or none.
  async function commitCreatePack(draft) {
    const sourceType=currentSourceType(),validation=document.getElementById('form-validation');
    const rows=packRowValues();
    for(const row of rows){
      // Validity, not completeness: a present-but-reversed date pair must
      // never reach the API from either path.
      const start=A.parseDate(row.start),end=A.parseDate(row.end);
      if(start&&end&&end<start){validation.textContent=`${row.channel}: end date cannot be before start date.`;return;}
    }
    const shared={source_type:sourceType};
    CREATE_FIELDS.forEach(name=>{
      if(PACK_ROW_FIELDS.includes(name))return;
      if(name==='audience'&&sourceType!=='internal')return;
      const raw=formValue(name);
      if(raw)shared[name]=raw;
    });
    // Pack mode replaces the circular campaign/pack pair with one pack name
    // (stored as the communication pack) plus an optional campaign umbrella.
    shared.communication_pack=formValue('pack_name');
    const packCampaign=formValue('pack_campaign');
    if(packCampaign)shared.campaign=packCampaign;
    if(sourceType==='internal')shared.news_digest=form().elements.news_digest.checked;
    const items=rows.map(row=>{
      const item=Object.assign({},shared,{activity_name:row.name.trim(),channel:row.channel});
      if(row.start)item.start_date=new Date(row.start).toISOString();
      if(row.end)item.end_date=new Date(row.end).toISOString();
      return item;
    });
    validation.textContent='';
    try {
      const created=await repository.createActivitiesBatch(items);
      created.items.forEach(item=>state.snapshotRows.push(item));
      state.packing=false;state.dirty=false;
      if(draft){
        // Plain toast on purpose: a batch has no single ID to copy.
        toast(`${created.items.length} draft activities created — chased on the Overview`);
      } else {
        const ids=created.items.map(item=>item.tracking_id).filter(Boolean);
        toast(`${created.items.length} activities created — ${ids.join(', ')}`);
      }
      closeDrawer();
      // Post-save orientation: land on the Activities table pre-filtered to the
      // new pack so the created records and their IDs are immediately visible.
      const packFilterLabel=campaignLabel(created.items[0]||{});
      renderAll();
      if(packFilterLabel){
        const select=document.getElementById('activity-campaign');
        if(Array.from(select.options).some(opt=>opt.value===packFilterLabel)){
          select.value=packFilterLabel;
          applyActivityFilters();bindOpenRows();bindDuplicateButtons();
        }
      }
      showPage('activities');
    } catch(error) {
      validation.textContent=packErrorMessage(error.message,rows);
    }
  }

  function closeDrawer() {
    multiselectContainers().forEach(closeMsPopover);
    hideConflictBanner();
    document.getElementById('activity-drawer').classList.remove('open');document.getElementById('activity-drawer').setAttribute('aria-hidden','true');state.selected=null;state.editing=false;state.creating=false;state.packing=false;state.dirty=false;
    setPackMode(false);
    const opener=state.drawerOpener;state.drawerOpener=null;
    if(opener&&typeof opener.focus==='function')opener.focus();
  }

  // Discard confirmation modal — replaces the former blocking browser
  // "Discard unsaved changes?" prompt with a corporate-styled, focus-trapped
  // dialog. discardModalOpen guards against a second modal opening from
  // rapid repeated Escape presses or overlapping close paths.
  function openDiscardModal() {
    return new Promise(resolve => {
      if (state.discardModalOpen) { resolve(false); return; }
      state.discardModalOpen = true;
      const modal = document.getElementById('discard-modal');
      const keepBtn = document.getElementById('discard-keep');
      const discardBtn = document.getElementById('discard-confirm');
      const returnFocus = document.activeElement;
      const settle = result => {
        modal.classList.remove('open');
        modal.setAttribute('aria-hidden', 'true');
        modal.removeEventListener('keydown', onKeydown);
        keepBtn.onclick = null;
        discardBtn.onclick = null;
        state.discardModalOpen = false;
        if (returnFocus && typeof returnFocus.focus === 'function') returnFocus.focus();
        resolve(result);
      };
      const onKeydown = event => {
        if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); settle(false); return; }
        if (event.key === 'Enter') { event.stopPropagation(); return; }
        if (event.key === 'Tab') {
          event.preventDefault(); event.stopPropagation();
          (document.activeElement === keepBtn ? discardBtn : keepBtn).focus();
        }
      };
      keepBtn.onclick = () => settle(false);
      discardBtn.onclick = () => settle(true);
      modal.addEventListener('keydown', onKeydown);
      modal.classList.add('open');
      modal.setAttribute('aria-hidden', 'false');
      keepBtn.focus();
    });
  }

  // Admin-only delete confirmation — same focus-trapped modal shape as
  // openDiscardModal above, no window.confirm.
  function openDeleteModal() {
    return new Promise(resolve => {
      if (state.deleteModalOpen) { resolve(false); return; }
      state.deleteModalOpen = true;
      const modal = document.getElementById('delete-modal');
      const cancelBtn = document.getElementById('delete-cancel');
      const confirmBtn = document.getElementById('delete-confirm');
      const returnFocus = document.activeElement;
      const settle = result => {
        modal.classList.remove('open');
        modal.setAttribute('aria-hidden', 'true');
        modal.removeEventListener('keydown', onKeydown);
        cancelBtn.onclick = null;
        confirmBtn.onclick = null;
        state.deleteModalOpen = false;
        if (returnFocus && typeof returnFocus.focus === 'function') returnFocus.focus();
        resolve(result);
      };
      const onKeydown = event => {
        if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); settle(false); return; }
        if (event.key === 'Enter') { event.stopPropagation(); return; }
        if (event.key === 'Tab') {
          event.preventDefault(); event.stopPropagation();
          (document.activeElement === cancelBtn ? confirmBtn : cancelBtn).focus();
        }
      };
      cancelBtn.onclick = () => settle(false);
      confirmBtn.onclick = () => settle(true);
      modal.addEventListener('keydown', onKeydown);
      modal.classList.add('open');
      modal.setAttribute('aria-hidden', 'false');
      cancelBtn.focus();
    });
  }

  async function confirmDiscardIfDirty() {
    if (!(state.editing && state.dirty)) return true;
    return openDiscardModal();
  }

  // C2/I4: the draft modal. Resolves true = save
  // as draft with whatever is filled, false = go back (first missing field
  // focused) -- or, when a "Fill it in" link is clicked, that specific field.
  // A draft still needs a name: if activity_name is among the missing
  // fields, "Save as draft" never posts -- it behaves like "go back", just
  // focused on the name, so the API's own hard requirement is never the
  // thing that silently rejects a click. T5 extends the same rule to pack
  // scope: a draft pack still needs its pack name, at least one channel and
  // a name on every channel row -- dates may stay open.
  const isDraftBlocker = name => {
    if (name==='activity_name'||name==='pack_name'||name==='pack_channels') return true;
    const token=PACK_ROW_TOKEN_RE.exec(name);
    return Boolean(token&&token[2]==='name');
  };

  function confirmDraftSave(missing) {
    return new Promise(resolve => {
      if (state.draftModalOpen) { resolve(false); return; }
      state.draftModalOpen = true;
      const modal = document.getElementById('draft-modal');
      const saveBtn = document.getElementById('draft-save');
      const backBtn = document.getElementById('draft-back');
      const list = document.getElementById('draft-modal-list');
      document.getElementById('draft-modal-body').textContent = state.packing
        ? "The pack's activities are saved with what is filled in. The rest is chased on the Overview until they are complete:"
        : 'This activity is saved with what is filled in. The rest is chased on the Overview until it is complete:';
      list.innerHTML = missing.map(name=>`<li><span>${esc(missingFieldLabel(name))}</span><button type="button" class="link-inline" data-jump="${esc(name)}">Fill it in</button></li>`).join('');
      const settle = (result, jumpTo) => {
        modal.classList.remove('open');
        modal.setAttribute('aria-hidden','true');
        modal.removeEventListener('keydown', onKeydown);
        list.removeEventListener('click', onListClick);
        saveBtn.onclick = null; backBtn.onclick = null;
        state.draftModalOpen = false;
        if (!result) focusField(jumpTo || missing[0]);
        resolve(result);
      };
      const onListClick = event => {
        const jump = event.target.closest('[data-jump]');
        if (jump) settle(false, jump.dataset.jump);
      };
      const onKeydown = event => {
        if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); settle(false); return; }
        if (event.key === 'Tab') {
          // The "Fill it in" jump links are part of the cycle, not just the
          // two footer buttons -- keyboard users must reach them.
          event.preventDefault(); event.stopPropagation();
          const focusable = Array.from(modal.querySelectorAll('button'));
          const idx = focusable.indexOf(document.activeElement);
          const next = event.shiftKey
            ? focusable[(idx <= 0 ? focusable.length : idx) - 1]
            : focusable[(idx + 1) % focusable.length];
          next.focus();
        }
      };
      saveBtn.onclick = () => {
        const blocker = missing.find(isDraftBlocker);
        if (blocker) {
          document.getElementById('form-validation').textContent = blocker==='pack_channels'
            ? 'A draft pack still needs at least one channel.'
            : 'A draft still needs a name.';
          settle(false, blocker);
          return;
        }
        settle(true);
      };
      backBtn.onclick = () => settle(false);
      list.addEventListener('click', onListClick);
      modal.addEventListener('keydown', onKeydown);
      modal.classList.add('open');
      modal.setAttribute('aria-hidden','false');
      saveBtn.focus();
    });
  }

  function setFormEnabled(enabled) {
    Array.from(form().elements).forEach(el=>{if(el.name)el.disabled=!enabled;});
    ['belongs-to','belongs-new'].forEach(id=>{document.getElementById(id).disabled=!enabled;});
    multiselectContainers().forEach(container=>setMultiselectEnabled(container,enabled));
  }

  // Every open finding on the record, as jump targets. Rendered from the
  // edit transition rather than from openDrawer, so a row opened read-only
  // and then switched to edit gets the bar too.
  function renderIssueJump(editing) {
    const bar=document.getElementById('drawer-issue-jump');
    const issues=editing&&state.selected ? A.rowIssues(state.selected) : [];
    if(!issues.length){bar.hidden=true;bar.innerHTML='';return;}
    bar.innerHTML=`<span class="issue-jump-label">To fix:</span>`
      +issues.map(issue=>`<button type="button" class="link-inline" data-jump="${esc(issue.field)}">${esc(issueLabel(issue))}</button>`).join('');
    bar.hidden=false;
  }

  function setDrawerEditing(editing) {
    const wasEditing=state.editing;
    state.editing=editing;state.creating=false;state.dirty=false;
    // I3/C3/I5: any view<->edit transition on an existing record starts a
    // clean slate -- no stale .missing paint from a previous edit attempt,
    // and the "Save and create another" affordance only belongs on the
    // record it was just created for (openDrawer always routes through here).
    state.showErrors=false;
    clearMissingPaint();
    clearCreateAnotherButton();
    renderIssueJump(editing);
    if(!editing)hideConflictBanner();
    setFormEnabled(editing);
    // Read-only shows the plain detail view; the form only exists while editing.
    document.getElementById('detail-view').hidden=editing;
    form().hidden=!editing;
    if(state.selected)setDrawerTracking(state.selected,editing);
    // P1/P2: the eyebrow names the mode; the mode bar (badge/edit/duplicate/
    // delete) is only useful read-only -- while editing it is hidden and its
    // version-check hint lives in the footer's #save-hint instead.
    document.getElementById('drawer-eyebrow').textContent=editing?'Editing':'Activity detail';
    document.getElementById('drawer-mode').hidden=editing;
    // Scope only means anything while creating -- an existing activity
    // already committed to single or pack at creation time (setDrawerEditing
    // is never reached from the create/pack flows, only from an existing
    // record's view<->edit toggle, so this is unconditional here).
    document.getElementById('scope-row').hidden=true;
    document.getElementById('activity-drawer').classList.remove('wide');
    document.getElementById('drawer-mode-label').textContent=editing?'Editing':'Read only';
    document.getElementById('drawer-mode-label').className=`badge ${editing?'info':'neutral'}`;
    // Edit gates on this specific activity (editor/admin always; contributor
    // only on their own rows). Duplicate creates a NEW activity owned by the
    // duplicator, so it gates on canCreate() — any contributor may duplicate
    // any visible row, mirroring "contributor may create". Comfort gating —
    // the server is still the authority.
    const editAllowed=!editing&&state.selected&&canEditActivity(state.selected);
    const duplicateAllowed=!editing&&state.selected&&canCreate();
    document.getElementById('drawer-edit').style.display=editAllowed?'block':'none';
    document.getElementById('drawer-duplicate').style.display=duplicateAllowed?'inline-block':'none';
    document.getElementById('drawer-delete').textContent='Delete activity';
    document.getElementById('drawer-delete').hidden=!(!editing&&state.selected&&canDelete());
    document.querySelector('.drawer-actions').style.display=editing?'grid':'none';
    document.getElementById('save-hint').hidden=!editing;
    document.getElementById('drawer-save').textContent='Save activity';
    // Never inherit a disabled zero-channel pack CTA from an abandoned
    // pack session in the same (reused) drawer DOM.
    document.getElementById('drawer-save').disabled=false;
    document.getElementById('form-validation').textContent='';
    // History is a read-only panel: never shown while editing.
    document.getElementById('drawer-history').hidden=editing;
    // Refetch when returning to read-only from an actual edit attempt (e.g.
    // Cancel after a 409 conflict) so the panel can't go stale showing a
    // pre-edit snapshot that silently omits the very change that caused the
    // conflict. Guarded on `wasEditing` so openDrawer's own initial
    // setDrawerEditing(false) call -- where state.editing is already false by
    // this point, since openDrawer sets it before calling here -- does not
    // double-fetch alongside its own loadHistory(row.id) call.
    if (!editing && wasEditing && state.selected && state.selected.id) loadHistory(state.selected.id);
    updateReady();
  }

  // --- 409 conflict resolution -------------------------------------------
  // On a version conflict the drawer shows what the database changed, marks
  // true collisions (fields both sides touched), and offers two exits:
  // "Reload record" discards my edits; "Keep my edits" rebases the form onto
  // the fresh record and re-applies exactly the fields I touched — so a
  // follow-up save can never patch untouched fields back to stale values.

  const CONFLICT_COMPARE_FIELDS = CREATE_FIELDS.concat(['news_digest']);

  const conflictDisplayValue = (field, value) => {
    if (value === null || value === undefined || String(value).trim() === '') return '—';
    if (field === 'start_date' || field === 'end_date') return fmtDateTime(value);
    if (field === 'news_digest') return value ? 'Yes' : 'No';
    return String(value);
  };

  function applyPatchToForm(patchObj) {
    Object.entries(patchObj).forEach(([key, value]) => {
      const el = form().elements[key];
      if (!el) return;
      if (el.type === 'checkbox') { el.checked = Boolean(value); return; }
      el.value = value === null ? '' : (el.type === 'datetime-local' ? isoLocal(value) : String(value));
    });
  }

  function hideConflictBanner() {
    const banner = document.getElementById('conflict-banner');
    banner.hidden = true;
    banner.innerHTML = '';
  }

  function showConflictBanner(original, fresh, myPatch) {
    const banner = document.getElementById('conflict-banner');
    const theirs = CONFLICT_COMPARE_FIELDS.filter(field => A.fieldValueChanged(field, original[field], fresh[field]));
    const rows = theirs.map(field => {
      const label = FIELD_LABELS[field] || field;
      const collision = Object.prototype.hasOwnProperty.call(myPatch, field);
      return `<div class="conflict-field${collision ? ' collision' : ''}"><span class="conflict-field-label">${esc(label)}</span><span class="conflict-field-diff">${esc(conflictDisplayValue(field, original[field]))} → ${esc(conflictDisplayValue(field, fresh[field]))}</span>${collision ? '<span class="badge warning">also edited by you</span>' : ''}</div>`;
    }).join('');
    banner.innerHTML = `<strong>This record changed while you were editing</strong><p>${theirs.length ? 'The database now differs in:' : 'Another save bumped the version; no visible field differs.'}</p>${rows}<div class="conflict-actions"><button type="button" class="btn secondary" id="conflict-reload">Reload record — discard my edits</button><button type="button" class="btn primary" id="conflict-keep">Keep my edits</button></div>`;
    banner.hidden = false;
    document.getElementById('conflict-reload').onclick = () => {
      hideConflictBanner();
      populateDrawerForm(state.selected);
      syncBelongsToFromFields();
      renderMultiselectOptions();
      renderDetailView(state.selected);
      setDrawerEditing(false);
      toast('Reloaded from the database');
    };
    document.getElementById('conflict-keep').onclick = () => {
      hideConflictBanner();
      populateDrawerForm(state.selected);
      applyPatchToForm(myPatch);
      syncBelongsToFromFields();
      renderMultiselectOptions();
      state.dirty = true;
      updateReady();
      document.getElementById('form-validation').textContent = 'Rebased on the current record — Save activity will apply only the fields you changed.';
    };
    banner.scrollIntoView({block: 'nearest'});
  }

  // Builds the PATCH from a diff of the live form against state.selected and
  // sends it. No completeness gating of its own -- attemptSave() (full save)
  // and openDraftModal() (explicit draft save) are the two gates, and both
  // call this only once they have decided the save may proceed. Same
  // function either way: "draft save = the same PATCH as today with
  // whatever is filled" (see commitCreate() for the create-side twin).
  async function commitEditPatch() {
    if(!state.selected||!state.selected.id||!state.selected.version)return;
    const data=new FormData(form()),patch={};
    data.forEach((value,key)=>{if(key==='news_digest')return;let normalized=String(value);if((key==='start_date'||key==='end_date')&&normalized)normalized=new Date(normalized).toISOString();if(A.fieldValueChanged(key,state.selected[key],normalized))patch[key]=normalized===''?null:normalized;});
    if(state.selected.source_type==='internal'){const checked=form().elements.news_digest.checked;if(Boolean(state.selected.news_digest)!==checked)patch.news_digest=checked;}
    const validation=document.getElementById('form-validation');
    // Defence in depth only -- attemptSave()/openDraftModal() already block
    // an empty name before either ever calls this function.
    if(patch.activity_name===null){validation.textContent='A draft still needs a name.';focusField('activity_name');return;}
    const start=A.parseDate(patch.start_date||state.selected.start_date),end=A.parseDate(patch.end_date||state.selected.end_date);
    if(start&&end&&end<start){validation.textContent='End date cannot be before start date.';focusField('end_date');return;}
    if(!Object.keys(patch).length){toast('No changes to save');setDrawerEditing(false);return;}
    try {
      const updated=await repository.updateActivity(state.selected.id,state.selected.version,patch);
      state.snapshotRows=state.snapshotRows.map(row=>row.id===updated.id?updated:row);
      state.dirty=false;
      renderAll();
      const missing=missingRequiredForRow(updated);
      // I5/C2: stay open, read-only, on the saved record -- never close the
      // drawer after a save (create's "stay open" principle applied
      // symmetrically to edit, so draft vs full save never look different).
      toast(missing.length?`Draft saved · ${updated.tracking_id}`:`Saved · ${updated.tracking_id}`,updated.tracking_id);
      openDrawer(updated,state.drawerOpener);
    } catch(error) {
      if(error.status===409){
        const original=state.selected;
        const loaded=await loadData();
        state.snapshotRows=loaded.rows;state.meta=loaded.meta;refreshRows();
        const fresh=state.snapshotRows.find(row=>String(row.id)===String(original.id));
        if(!fresh){validation.textContent='This activity no longer exists in the database.';return;}
        state.selected=fresh;
        validation.textContent='';
        showConflictBanner(original,fresh,patch);
      } else {
        validation.textContent=error.message;
      }
    }
  }

  // Create-side twin of commitEditPatch(): posts whatever is currently
  // filled in, no completeness gating of its own. Only date-order is
  // enforced here (a validity error, not a completeness gap).
  async function commitCreate() {
    const sourceType=currentSourceType(),validation=document.getElementById('form-validation');
    const value=name=>{const el=form().elements[name];return el?String(el.value||'').trim():'';};
    const start=A.parseDate(value('start_date')),end=A.parseDate(value('end_date'));
    if(start&&end&&end<start){validation.textContent='End date cannot be before start date.';focusField('end_date');return;}
    const payload={source_type:sourceType};
    CREATE_FIELDS.forEach(name=>{
      if(name==='audience'&&sourceType!=='internal')return;
      const raw=value(name);
      if(!raw)return;
      payload[name]=(name==='start_date'||name==='end_date')?new Date(raw).toISOString():raw;
    });
    if(sourceType==='internal')payload.news_digest=form().elements.news_digest.checked;
    validation.textContent='';
    try {
      const created=await repository.createActivity(payload);
      state.snapshotRows.push(created);
      state.creating=false;state.dirty=false;
      renderAll();
      const missing=missingRequiredForRow(created);
      // I5: stay open, read-only, on the new record; toast carries the
      // minted tracking ID with a Copy-ID action (see toast()).
      toast(missing.length?`Draft saved · ${created.tracking_id}`:`Activity created — ${created.tracking_id}`,created.tracking_id);
      openDrawer(created,state.drawerOpener);
      showCreateAnotherButton();
    } catch(error) {
      validation.textContent=error.message;
    }
  }

  // I3: the form-submit gate for create/edit (pack has its own submitPack).
  // Blocks on ANY missing required field -- paints .missing, focuses the
  // first gap, and points at "Save as draft" as the alternative -- rather
  // than silently accepting a partial save the way the old soft-confirm
  // modal used to. Only once nothing required is missing does it actually
  // persist.
  function attemptSave(event) {
    if(event)event.preventDefault();
    state.showErrors=true;
    const missing=updateReady();
    if(missing.length){
      focusField(missing[0]);
      document.getElementById('ready-text').textContent=`${missing.length} required field${missing.length===1?'':'s'} left — or use "Save as draft"`;
      return;
    }
    if(state.creating)commitCreate();else commitEditPatch();
  }

  // C2/I4: #btn-draft's handler. If the form is already complete this is
  // just a normal save (pack scope included -- requestSubmit routes to
  // submitPack). Otherwise confirm via the shared draft modal, then persist
  // with whatever is filled: pack scope through the batch commit (T5) --
  // confirmDraftSave has already enforced the pack draft rule (pack name,
  // at least one channel, every row named; dates optional) -- single
  // create/edit through their normal POST/PATCH twins.
  async function openDraftModal() {
    const missing=missingRequiredFields();
    if(!missing.length){form().requestSubmit();return;}
    if(!await confirmDraftSave(missing))return;
    if(state.packing){await commitCreatePack(true);return;}
    if(state.creating)await commitCreate();else await commitEditPatch();
  }

  // C3: every dismissal route (backdrop, x, Cancel, Escape) funnels through
  // here so exactly one place decides dirty-vs-clean. `after` lets Cancel
  // supply "revert to read-only" instead of the default full close.
  async function requestClose(after) {
    if(!await confirmDiscardIfDirty())return;
    (after||closeDrawer)();
  }

  // Cancel's behaviour for an existing activity: revert the form back to
  // the saved record and return to the read-only detail view (the drawer
  // itself stays open). Creating/duplicating/packing has no saved record to
  // revert to, so drawer-cancel's own handler closes the whole drawer
  // instead of calling this.
  function revertToViewFromEdit() {
    if(state.selected){
      const sourceType=state.selected.source_type||'internal';
      applyVariant(sourceType);
      populateSelectOptions(sourceType);
      populateDrawerForm(state.selected);
      syncBelongsToFromFields();
      renderMultiselectOptions();
      renderDetailView(state.selected);
    }
    setDrawerEditing(false);
  }

  // I5: "Save and create another" -- a secondary mode-bar button that only
  // exists right after a create succeeds (added by commitCreate(), removed
  // by the next setDrawerEditing() transition -- see there for why that is
  // the correct single cleanup point).
  function clearCreateAnotherButton() {
    const old=document.getElementById('btn-create-another');
    if(old)old.remove();
  }

  function showCreateAnotherButton() {
    clearCreateAnotherButton();
    const bar=document.querySelector('.drawer-mode-actions');
    if(!bar)return;
    const btn=document.createElement('button');
    btn.type='button';
    btn.className='btn secondary';
    btn.id='btn-create-another';
    btn.textContent='Save and create another';
    btn.onclick=()=>openCreateDrawer(state.drawerOpener);
    bar.insertBefore(btn,bar.firstChild);
  }

  // I2: prefill a blank create from the user's own newest activity.
  const PREFILL_KEYS=['lead','lead_team','time_zone','region','business_division'];

  function newestOwnRow() {
    const username=(state.currentUser&&state.currentUser.username)||'studio';
    return state.snapshotRows
      .filter(row=>row.created_by===username)
      .reduce((latest,row)=>{
        if(!latest)return row;
        const a=A.parseDate(row.created_at),b=A.parseDate(latest.created_at);
        return (a&&(!b||a>b))?row:latest;
      },null);
  }

  function applyPrefill() {
    const last=newestOwnRow(),note=document.getElementById('prefill-note');
    if(!last){note.hidden=true;return;}
    PREFILL_KEYS.forEach(key=>{
      // Empty source values are skipped so resetCreateForm's defaults
      // (e.g. time_zone) survive a prefill from a sparse row.
      if(!nonempty(last[key]))return;
      if(MULTISELECT_FIELDS.includes(key)){
        const container=msContainer(key);
        if(container)msHidden(container).value=String(last[key]);
      } else {
        const el=form().elements[key];
        if(el)el.value=String(last[key]);
      }
    });
    renderMultiselectOptions();
    document.getElementById('prefill-text').textContent='Prefilled from your last activity.';
    note.hidden=false;
    updateReady();
  }

  // Read at call time, not at load time. xlsx.js is the only file the studio
  // gained rather than changed, so it is the one a hand-copied deployment
  // silently misses -- and a missing script left the export button doing
  // absolutely nothing: no file, no message, only a console line nobody has
  // open. A dependency that is not there has to say so.
  function workbookWriter() {
    const writer = window.CplanXlsx;
    if (!writer) {
      toast('Export unavailable — xlsx.js did not load. Copy it alongside app.js and reload.');
      return null;
    }
    return writer;
  }

  // Both exports are read in Excel, so both are written as .xlsx rather than
  // handed over as CSV for Excel to guess at -- separators, decimal marks and
  // date order all depend on the reader's locale, and a tracking ID like
  // "IC-2026-0137-IN" has been turned into a formula by a leading character
  // before now. A real workbook also carries what the reader actually wants:
  // column widths, a frozen header, a filter row, and dates that sort.
  const EXPORT_COLUMNS = [
    ['tracking_id', 'Tracking ID', 22],
    ['activity_name', 'Activity', 42],
    ['channel', 'Channel', 20],
    ['start_date', 'Start', 18],
    ['end_date', 'End', 18],
    ['priority', 'Priority', 26],
    ['lead', 'Lead', 18],
    ['lead_team', 'Lead team', 16],
    ['target_audience', 'Target audience', 24],
    ['business_division', 'Division', 14],
    ['region', 'Region', 14],
    ['campaign', 'Campaign', 24],
    ['communication_pack_cpid', 'Pack ID', 16],
    ['strategic_objectives', 'Communications pillars', 28],
    ['source_type', 'Type', 12]
  ];

  const DATE_FIELDS = new Set(['start_date', 'end_date']);
  const exportCell = (row, field) =>
    DATE_FIELDS.has(field) ? (nonempty(row[field]) ? {date: row[field]} : '') : (row[field] || '');
  const stamp = () => new Date().toISOString().slice(0, 10);

  function exportActivities() {
    const X = workbookWriter();
    if (!X) return;
    const rows = state.filteredRows;
    if (!rows.length) { toast('Nothing to export with the current filters'); return; }
    download(`CPLAN_activities_${stamp()}.xlsx`, X.build({
      sheetName: 'Activities',
      columns: EXPORT_COLUMNS.map(([, header, width]) => ({header, width})),
      rows: rows.map(row => ({cells: EXPORT_COLUMNS.map(([field]) => exportCell(row, field))}))
    }));
    toast(`${plural(rows.length, 'activity', 'activities')} exported`);
  }

  // One row per pack, its activities beneath it one outline level deeper, so
  // the sheet opens as a list of packs and each opens on click. That grouping
  // is the reason this is a workbook and not a flat table: the question the
  // export answers is "what belongs together", and a flat table answers it
  // only if you sort it yourself and trust that nothing else moved.
  function exportPacks() {
    const X = workbookWriter();
    if (!X) return;
    const {cards, loose} = packUnits();
    const shown = filteredPackCards(cards);
    if (!shown.length && !loose.length) { toast('Nothing to export'); return; }

    const fields = EXPORT_COLUMNS.filter(([field]) => field !== 'activity_name');
    const columns = [{header: 'Pack / activity', width: 52}]
      .concat(fields.map(([, header, width]) => ({header, width})));

    // Summary cells are placed by column name, never by counting positions.
    // The first attempt filled them in order and put "11 activities" under
    // Start, the pack's first date under End and its last under Priority --
    // silently, because every value was individually plausible.
    const at = {};
    columns.forEach((column, index) => { at[column.header] = index; });
    const summaryRow = values => {
      const cells = new Array(columns.length).fill('');
      Object.entries(values).forEach(([header, value]) => {
        if (header in at) cells[at[header]] = value;
      });
      return cells;
    };

    const rows = [];
    const childRow = row => ({
      level: 1,
      // Two leading spaces so the nesting survives a copy-paste out of the
      // outline, where the group controls do not travel.
      cells: [`  ${row.activity_name || 'Untitled'}`]
        .concat(fields.map(([field]) => exportCell(row, field)))
    });

    shown.forEach(card => {
      const gaps = card.rows.filter(row => A.planningCompleteness(row).score < 100).length;
      // The count and the readiness ride in the label rather than claiming a
      // column of their own: they describe the group, and every column here
      // belongs to an activity.
      const title = `${card.id}${card.campaign && card.campaign !== card.id ? ` · ${card.campaign}` : ''}`
        + ` — ${plural(card.activities, 'activity', 'activities')}`
        + (gaps ? `, ${fmtNum(gaps)} incomplete` : ', complete');
      rows.push({level: 0, bold: true, cells: summaryRow({
        'Pack / activity': title,
        'Channel': plural(card.channels, 'channel'),
        'Start': card.firstDate ? {date: card.firstDate} : '',
        'End': card.lastDate ? {date: card.lastDate} : '',
        'Campaign': card.campaign || '',
        'Pack ID': card.id
      })});
      card.rows.slice()
        .sort((a, b) => (A.parseDate(a.start_date) || 0) - (A.parseDate(b.start_date) || 0))
        .forEach(row => rows.push(childRow(row)));
    });

    if (loose.length) {
      rows.push({level: 0, bold: true, cells: summaryRow({
        'Pack / activity': `Not in a pack — ${plural(loose.length, 'activity', 'activities')}`
      })});
      loose.slice()
        .sort((a, b) => (A.parseDate(a.start_date) || 0) - (A.parseDate(b.start_date) || 0))
        .forEach(row => rows.push(childRow(row)));
    }

    download(`CPLAN_packs_${stamp()}.xlsx`, X.build({
      sheetName: 'Packs', columns, rows, collapsed: true
    }));
    toast(`${plural(shown.length, 'pack')} exported`);
  }



  function showPage(name) {
    document.querySelectorAll('.nav-item').forEach(x=>x.classList.toggle('active',x.dataset.page===name));
    document.querySelectorAll('.page').forEach(x=>x.classList.remove('active'));
    document.getElementById(`page-${name}`).classList.add('active');
  }

  const RANGE_LABELS = {'30d':'last 30 days', quarter:'this quarter', ytd:'year to date', '12m':'last 12 months'};
  function updateRangeUI() {
    const filtering=Boolean(state.dateFrom||state.dateTo);
    document.getElementById('time-filter').classList.toggle('filtering',filtering);
    const banner=document.getElementById('range-banner');
    banner.hidden=!filtering;
    if(!filtering)return;
    const active=document.querySelector('#time-presets button.active');
    const label=(active&&RANGE_LABELS[active.dataset.range])||`${state.dateFrom?fmtDate(state.dateFrom):'…'} – ${state.dateTo?fmtDate(state.dateTo):'…'}`;
    document.getElementById('range-banner-text').textContent=`Filtered: ${label} — applies to every tab; page horizons count within this range`;
  }

  function rerenderAfterTimeChange() {
    updateRangeUI();
    refreshRows();
    renderAll();
  }

  function wireEvents() {
    document.querySelectorAll('.nav-item').forEach(btn=>btn.onclick=()=>showPage(btn.dataset.page));
    document.querySelectorAll('#time-presets button').forEach(btn=>btn.onclick=()=>{
      document.querySelectorAll('#time-presets button').forEach(x=>x.classList.remove('active'));
      btn.classList.add('active');
      applyDatePreset(btn.dataset.range);
      rerenderAfterTimeChange();
    });
    ['date-from','date-to'].forEach(id=>document.getElementById(id).addEventListener('change',()=>{
      const from=document.getElementById('date-from').value,to=document.getElementById('date-to').value;
      state.dateFrom=from?new Date(`${from}T00:00:00`):null;
      state.dateTo=to?endOfDay(new Date(`${to}T00:00:00`)):null;
      document.querySelectorAll('#time-presets button').forEach(x=>x.classList.remove('active'));
      rerenderAfterTimeChange();
    }));
    document.getElementById('range-banner-clear').onclick=()=>{
      document.querySelectorAll('#time-presets button').forEach(x=>x.classList.toggle('active',x.dataset.range==='all'));
      applyDatePreset('all');
      rerenderAfterTimeChange();
    };
    document.getElementById('mix-dimension').onclick=event=>{
      const btn=event.target.closest('button');if(!btn)return;
      document.querySelectorAll('#mix-dimension button').forEach(x=>x.classList.remove('active'));
      btn.classList.add('active');
      renderChannelMix();
    };
    document.getElementById('trend-toggle').onclick=event=>{
      const btn=event.target.closest('button');if(!btn)return;
      document.querySelectorAll('#trend-toggle button').forEach(x=>x.classList.remove('active'));
      btn.classList.add('active');
      state.trendMode=btn.dataset.mode;
      renderTrend();
    };
    document.getElementById('board-group-toggle').onclick=event=>{
      const btn=event.target.closest('button');if(!btn)return;
      document.querySelectorAll('#board-group-toggle button').forEach(x=>x.classList.remove('active'));
      btn.classList.add('active');
      state.boardGroup=btn.dataset.group;
      renderBoard();bindOpenRows();
    };
    // Attention queue: group links jump to the pre-filtered workbench; fix
    // links (queue + readiness chips) open the drawer in edit mode focused on
    // the first missing field.
    document.addEventListener('click',event=>{
      const queueBtn=event.target.closest('[data-queue]');
      if(queueBtn){setQueueFilter(queueBtn.dataset.queue);return;}
      const fixBtn=event.target.closest('[data-fix-id]');
      if(fixBtn){
        event.stopPropagation();
        const row=state.rows.find(item=>String(item.id)===String(fixBtn.dataset.fixId));
        if(row)openDrawer(row,fixBtn,{edit:true,focus:fixBtn.dataset.fixField||null});
      }
      const copyBtn=event.target.closest('[data-copy-id]');
      if(copyBtn){
        event.stopPropagation();
        // Confirmation where the hand already is, not only in the corner. The
        // toast still fires -- it is the accessible announcement and the undo
        // surface -- but a button that changes nothing when pressed reads as
        // broken, and in the pack drawer there are eleven of them.
        navigator.clipboard.writeText(copyBtn.dataset.copyId).then(()=>{
          toast('Tracking ID copied');
          copyBtn.classList.add('copied');
          setTimeout(()=>copyBtn.classList.remove('copied'),1200);
        }).catch(()=>toast('Copy failed'));
      }
    },true);
    // Overview cards name the thing the reader is after ("Largest gap:
    // Description", "Channel load") but the detail behind them lives on a
    // subpage nobody can see from here. A fresh-eyes test had six of nine
    // readers guessing at "Analytics" for answers that were already built.
    // Delegated, not per-element: some jump links are rendered on every data
    // refresh (the collision notice), so binding once at start-up would leave
    // them dead.
    document.addEventListener('click', event=>{
      const btn=event.target.closest('[data-goto]');
      if(!btn) return;
      const [page,sub]=btn.dataset.goto.split(':');
      const nav=document.querySelector(`.nav-item[data-page="${page}"]`);
      if(nav) nav.click();
      window.scrollTo({top:0});
      if(!sub) return;
      // Three shapes of destination now that the subnavs are gone: a view of
      // the Overview (list/timeline/calendar), a queue filter on Activities,
      // and a section of the Health page. The jump-link contract stays
      // "page:target" at every call site -- what changed is where a target can
      // land, not how a caller writes it.
      const view=document.querySelector(`#overview-view button[data-view="${sub}"]`);
      if(page==='overview'&&view){view.click();return;}
      if(page==='activities'){
        // Two shapes of Activities target: an issue queue, and the packless
        // filter, which is an ordinary filter value rather than a queue --
        // routing it through setQueueFilter would set a queue name that
        // matchesQueueFilter does not know and quietly filter nothing.
        if(sub==='no-pack'){
          state.queueFilter=null;
          showPage('activities');
          document.getElementById('activity-campaign').value=NO_PACK;
          runActivityFilters();
          return;
        }
        setQueueFilter(sub);return;
      }
      const section=document.getElementById(`sec-${sub}`);
      if(section)section.scrollIntoView({block:'start'});
    });
    // Backdrop, the × and Escape all close it -- three routes, same as the
    // activity drawer, because a panel that only closes by one is a trap.
    document.addEventListener('click',event=>{
      if(event.target.closest('[data-close-pack]'))closePackDetail();
    });
    document.addEventListener('keydown',event=>{
      if(event.key!=='Escape')return;
      // Only the topmost layer answers Escape. A fix chip inside a channel card
      // opens the activity drawer ON TOP of this one, and without the guard the
      // key would close the pack underneath and leave the activity floating on
      // a page the reader never chose.
      if(document.getElementById('activity-drawer').classList.contains('open'))return;
      if(document.getElementById('pack-drawer').classList.contains('open'))closePackDetail();
    });
    // View switcher: the list, the timeline and the calendar are three
    // layouts of one forward window, so switching is a local act -- no data
    // reload, no scroll reset, no page change.
    document.getElementById('overview-view').onclick=event=>{
      const btn=event.target.closest('button');if(!btn)return;
      document.querySelectorAll('#overview-view button').forEach(x=>x.classList.toggle('active',x===btn));
      document.querySelectorAll('#page-overview .overview-view').forEach(x=>x.classList.toggle('active',x.id===`view-${btn.dataset.view}`));
      if(btn.dataset.view==='timeline'){renderBoard();bindOpenRows();}
      if(btn.dataset.view==='calendar'){renderCalendar();bindOpenRows();}
    };
    const runPackFilters=()=>{renderPacks();bindOpenRows();};
    document.getElementById('pack-search').addEventListener('input',debounce(runPackFilters,200));
    document.getElementById('pack-campaign-filter').onchange=runPackFilters;
    document.getElementById('pack-clear').onclick=()=>{
      document.getElementById('pack-search').value='';
      document.getElementById('pack-campaign-filter').value='';
      runPackFilters();
    };
    document.getElementById('packs-new').onclick=event=>{openCreateDrawer(event.currentTarget);setScope('pack');};
    // Opening a pack means seeing its activities: the pack is a grouping, not a
    // record of its own, so it hands over to the list filtered to that pack
    // rather than pretending to be an object with a detail view.
    document.addEventListener('click',event=>{
      const packBtn=event.target.closest('[data-pack-open]');
      if(!packBtn)return;
      // A click on the name button bubbles to its own <tr>, which carries the
      // same attribute -- take the innermost and stop there, mirroring the
      // activity table's guard against opening the same record twice.
      if(packBtn.tagName==='BUTTON')event.stopPropagation();
      openPackDetail(packBtn.dataset.packOpen, packBtn);
    });
    document.getElementById('horizon-toggle').onclick=event=>{const btn=event.target.closest('button');if(!btn)return;document.querySelectorAll('#horizon-toggle button').forEach(x=>x.classList.remove('active'));btn.classList.add('active');state.horizonWeeks=Number(btn.dataset.weeks);renderBoard();bindOpenRows();};
    document.getElementById('cal-prev').onclick=()=>{state.calendarDate=new Date(state.calendarDate.getFullYear(),state.calendarDate.getMonth()-1,1);renderCalendar();bindOpenRows();};
    document.getElementById('cal-next').onclick=()=>{state.calendarDate=new Date(state.calendarDate.getFullYear(),state.calendarDate.getMonth()+1,1);renderCalendar();bindOpenRows();};
    document.getElementById('cal-today').onclick=()=>{state.calendarDate=new Date();renderCalendar();bindOpenRows();};
    const runActivityFilters=()=>{applyActivityFilters();bindOpenRows();bindDuplicateButtons();};
    const debouncedActivityFilters=debounce(runActivityFilters,200);
    document.getElementById('activity-search').addEventListener('input',debouncedActivityFilters);
    ACTIVITY_FILTER_IDS.filter(id=>id!=='activity-search').forEach(id=>document.getElementById(id).addEventListener('change',runActivityFilters));
    function clearActivityFilters(){
      state.queueFilter=null;
      ACTIVITY_FILTER_IDS.forEach(id=>document.getElementById(id).value='');
      runActivityFilters();
    }
    document.getElementById('activity-clear').onclick=clearActivityFilters;
    // The bar's own Clear drops just the queue -- a user who narrowed the
    // review list with a search should not lose that search too.
    document.getElementById('queue-bar-clear').onclick=()=>{state.queueFilter=null;runActivityFilters();};
    document.getElementById('activity-export').onclick=exportActivities;
    document.getElementById('packs-export').onclick=exportPacks;
    document.getElementById('activity-new').onclick=event=>openCreateDrawer(event.currentTarget);
    document.getElementById('overview-new').onclick=event=>openCreateDrawer(event.currentTarget);
    // The card's selected styling and its "Selected"/"Add" word are driven from
    // the checkbox that is still the real control, so a keyboard toggle updates
    // the card exactly like a click does.
    document.getElementById('pack-channels').addEventListener('change',event=>{
      const box=event.target.closest('input[type=checkbox]');
      if(box){
        const card=box.closest('.channel-card');
        if(card){
          card.classList.toggle('on',box.checked);
          const state2=card.querySelector('.cc-state');
          if(state2)state2.textContent=box.checked?'Selected':'Add';
        }
      }
      renderPackRows();state.dirty=true;
    });
    ['focusin','focusout'].forEach(type=>{
      document.getElementById('pack-channels').addEventListener(type,event=>{
        const card=event.target.closest&&event.target.closest('.channel-card');
        if(card)card.classList.toggle('focus',type==='focusin');
      });
    });
    // I6: stubs live-update as row dates are typed; the ready-line, CTA
    // count and summary refresh via the form-level input listener below
    // (updateReady is the single funnel for those).
    document.getElementById('pack-rows').addEventListener('input',updatePackStubs);
    // I6: fill down -- one start/end applied to every channel row; each row
    // stays individually editable afterwards.
    document.getElementById('fill-apply').onclick=()=>{
      const start=document.getElementById('fill-start').value,end=document.getElementById('fill-end').value;
      if(!start&&!end){toast('Set a pack start or end date first');return;}
      const rows=document.querySelectorAll('#pack-rows .pack-row');
      if(!rows.length){toast('Tick a channel first — the dates carry over to it');return;}
      rows.forEach(rowEl=>{
        if(start)rowEl.querySelector('[data-pack-start]').value=start;
        if(end)rowEl.querySelector('[data-pack-end]').value=end;
      });
      state.dirty=true;
      updatePackStubs();
      updateReady();
      // Says what it did AND that it is reversible per row, because the button
      // overwrites dates the planner may have set by hand.
      toast(`Pack dates applied to ${plural(rows.length,'channel')} — each row stays editable`);
    };
    document.getElementById('belongs-to').addEventListener('change',()=>{
      const value=document.getElementById('belongs-to').value;
      const newLabel=document.getElementById('belongs-new-label');
      newLabel.hidden=value!=='new';
      if(value==='new'){form().elements.campaign.value='';form().elements.communication_pack_cpid.value='';document.getElementById('belongs-new').value='';document.getElementById('belongs-new').focus();}
      else if(value.startsWith('pack::')){form().elements.communication_pack_cpid.value=value.slice(6);}
      else if(value.startsWith('camp::')){form().elements.campaign.value=value.slice(6);form().elements.communication_pack_cpid.value='';}
      else {form().elements.campaign.value='';form().elements.communication_pack_cpid.value='';}
      if(state.editing)state.dirty=true;
    });
    document.getElementById('belongs-new').addEventListener('input',()=>{
      form().elements.campaign.value=document.getElementById('belongs-new').value;
      if(state.editing)state.dirty=true;
    });
    // P12: the free-text add-channel input stays behind a link-inline toggle
    // (it is the escape hatch for a genuinely missing channel, not the
    // default path -- ticking an existing channel above is).
    document.getElementById('pack-channel-toggle').onclick=()=>{
      const row=document.getElementById('pack-add-channel-row');
      row.hidden=!row.hidden;
      if(!row.hidden)document.getElementById('pack-channel-new').focus();
    };
    document.getElementById('pack-channel-add').onclick=()=>{
      const input=document.getElementById('pack-channel-new');
      const channel=String(input.value||'').trim();
      if(!channel)return;
      if(!state.customChannels.includes(channel))state.customChannels.push(channel);
      renderPackChannels(currentSourceType());
      const box=Array.from(document.querySelectorAll('#pack-channels input')).find(item=>item.value===channel);
      if(box)box.checked=true;
      input.value='';
      document.getElementById('pack-add-channel-row').hidden=true;
      renderPackRows();
      state.dirty=true;
      // A programmatic tick fires no change event, so the ready-line/CTA/
      // summary funnel must be pushed by hand here.
      updateReady();
    };
    wireMultiselects();
    document.getElementById('source-toggle').onclick=event=>{
      const btn=event.target.closest('button');if(!btn)return;
      const source=btn.dataset.source;if(source===currentSourceType())return;
      setSourceToggle(source);applyVariant(source);populateSelectOptions(source);renderMultiselectOptions();
      if(state.packing){renderPackChannels(source);renderPackRows();}
      if(state.editing){state.dirty=true;updateReady();}
    };
    // I1: setScope('pack') drives the existing state.packing machinery --
    // data-single-only/data-pack-only visibility, .drawer.wide and
    // pack-channel rendering -- so pack scope is reachable mid-session
    // from the one create drawer (no separate pack entry point).
    document.getElementById('scope-toggle').onclick=event=>{
      const btn=event.target.closest('button');if(!btn)return;
      const scope=btn.dataset.scope;if(scope===currentScope())return;
      state.dirty=true;
      setScope(scope);
    };
    document.getElementById('prefill-clear').onclick=()=>{
      resetCreateForm();
      MULTISELECT_FIELDS.forEach(key=>{const container=msContainer(key);if(container)msHidden(container).value='';});
      renderMultiselectOptions();
      document.getElementById('prefill-note').hidden=true;
      if(state.packing){renderPackChannels(currentSourceType());renderPackRows();}
      updateReady();
      focusField(state.packing?'pack_name':'activity_name');
    };
    // C3: every dismissal route funnels through requestClose() -- backdrop
    // and the x default to a full close; Cancel supplies its own "revert to
    // read-only" action when there is a saved record to revert to.
    document.querySelectorAll('[data-close-drawer]').forEach(el=>el.onclick=()=>requestClose());
    document.getElementById('drawer-edit').onclick=()=>{if(!state.selected||!state.selected.id){toast('Database ID required for safe editing');return;}setDrawerEditing(true);};
    document.getElementById('drawer-issue-jump').addEventListener('click',event=>{
      const btn=event.target.closest('[data-jump]');
      if(!btn)return;
      document.querySelectorAll('#drawer-issue-jump [data-jump]').forEach(el=>el.classList.remove('active'));
      btn.classList.add('active');
      focusField(btn.dataset.jump);
    });
    document.getElementById('drawer-duplicate').onclick=()=>{if(state.selected)openDuplicateDrawer(state.selected,state.drawerOpener);};
    document.getElementById('drawer-delete').onclick=async()=>{
      if(!state.selected||!state.selected.id||!canDelete())return;
      const activityId=state.selected.id;
      if(!await openDeleteModal())return;
      await deleteActivity(activityId);
    };
    document.getElementById('user-chip-logout').onclick=()=>logout();
    document.getElementById('drawer-cancel').onclick=()=>requestClose(()=>{
      if(state.creating||state.packing){closeDrawer();return;}
      revertToViewFromEdit();
    });
    document.getElementById('btn-draft').onclick=()=>openDraftModal();
    const activityForm=document.getElementById('activity-form');
    activityForm.onsubmit=event=>{if(state.packing){submitPack(event);return;}attemptSave(event);};
    activityForm.addEventListener('input',()=>{if(state.editing){state.dirty=true;updateReady();}});
    activityForm.addEventListener('change',()=>{if(state.editing){state.dirty=true;updateReady();}});
    document.addEventListener('click',event=>{if(!event.target.closest('[data-multiselect]'))multiselectContainers().forEach(closeMsPopover);});
    document.addEventListener('keydown',async event=>{
      const isOpen=document.getElementById('activity-drawer').classList.contains('open');
      if(event.key==='Escape'){
        const openPop=document.querySelector('.ms-popover:not([hidden])');
        if(openPop){const container=openPop.closest('[data-multiselect]');closeMsPopover(container);container.querySelector('.ms-trigger').focus();return;}
        // C3: an open modal (discard/draft/delete) owns this Escape. Its own
        // keydown handler covers focus inside the modal; when focus sits
        // outside (e.g. after a backdrop click), forward the key to the modal
        // so Escape still dismisses it -- never the drawer underneath.
        const openModal=document.querySelector('.modal-overlay.open');
        if(openModal){openModal.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));return;}
        if(isOpen)requestClose();
        return;
      }
      if(isOpen&&event.key==='Tab'){
        const focusable=drawerFocusables();
        if(!focusable.length)return;
        const first=focusable[0],last=focusable[focusable.length-1];
        if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
        else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
      }
    });
    document.getElementById('login-form').addEventListener('submit', async event => {
      event.preventDefault();
      const username=document.getElementById('login-username').value.trim();
      const password=document.getElementById('login-password').value;
      const response=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password})});
      if(!response.ok){document.getElementById('login-error').classList.remove('hidden');return;}
      hideLoginOverlay();
      await initSession();
      await loadAndRenderAll();
    });
  }

  // Data load + first render, split out from init() so a successful login
  // (which happens after the DOM and event listeners already exist) can
  // re-run just this part without wireEvents() double-binding every listener.
  async function loadAndRenderAll() {
    try {
      const [loaded,syncRun]=await Promise.all([loadData(),loadSyncRun()]);
      state.snapshotRows=loaded.rows;state.meta=loaded.meta;state.syncRun=syncRun;refreshRows();
      const generated=loaded.meta&&(loaded.meta.generated_at_iso||loaded.meta.generated_at);
      const generatedDate=A.parseDate(generated);
      document.getElementById('status-dot').className='status-dot ready';
      document.getElementById('status-label').textContent=`${fmtNum(loaded.rows.length)} activities`;
      document.getElementById('snapshot-time').textContent=generatedDate?`updated ${generatedDate.toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'})}`:'updated just now';
      document.getElementById('freshness').title=`${backendLabel()} API: ${generated||'unknown'}`;
      renderAll();
    } catch(error) {
      console.error('CPLAN initialization failed',error);
      document.getElementById('status-dot').className='status-dot error';document.getElementById('status-label').textContent='Data load failed';document.getElementById('snapshot-time').textContent=error.message;
      document.querySelector('.content').innerHTML=`<div class="card">${emptyState(EMPTY_ICONS.alertTriangle, 'CPLAN could not initialize', `${error.message} Start the configured local database API and reload this page.`)}</div>`;
    }
  }

  async function init() {
    wireEvents();
    const user = await initSession();
    if (!user) return;
    await loadAndRenderAll();
  }

  init();
})();
