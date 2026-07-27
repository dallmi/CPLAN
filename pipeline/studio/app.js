(() => {
  'use strict';

  const A = window.CplanAnalytics;
  const COLORS = {grey:'#404040', bronze:'#B98E2C'};
  const state = {snapshotRows:[], rows:[], meta:null, syncRun:null, horizonWeeks:8, boardGroup:'channel', channelHorizonWeeks:4, trendMode:'', calendarDate:new Date(), selected:null, editing:false, creating:false, packing:false, customChannels:[], dirty:false, filteredRows:[], collisionsCache:new Map(), drawerOpener:null, discardModalOpen:false, incompleteModalOpen:false, deleteModalOpen:false, queueFilter:null, dateFrom:null, dateTo:null};

  const esc = A.escapeHtml;
  const fmtNum = value => Number(value || 0).toLocaleString('en-GB');
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

  function trackingIdHtml(id, options) {
    const opts = options || {};
    if (!nonempty(id)) return '<span class="tracking-id">—</span>';
    const match = TRACKING_ID_RE.exec(String(id));
    const inner = match
      ? `<span class="tid-prefix">${esc(match[1])}-</span><span class="tid-date">${esc(match[2])}</span>-<span class="tid-seq">${esc(match[3])}</span>-<span class="tid-channel">${esc(match[4])}</span>`
      : esc(String(id));
    const copy = opts.copy ? `<button type="button" class="copy-btn" data-copy-id="${esc(String(id))}" title="Copy tracking ID">Copy</button>` : '';
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

  // --- SVG donut (thin ring, white dividers, large white centre) ---
  const DONUT_SEQUENCE = ['#404040', '#B98E2C', '#8E8D83', '#CCCABC', '#5A5D5C', '#946F29', '#B8B3A2', '#6C5312'];
  // Priority is a neutral portfolio mix, not a status judgement: Bordeaux
  // anchors Critical, then bronze + spaced warm greys carry the rest so four
  // adjacent levels stay distinct on the thin ring instead of blurring into one
  // beige. RAG stays reserved for data-driven exceptions (short notice,
  // conflicts, incomplete). Unknown vocabularies fall back to distinct colours
  // by position rather than one flat bronze.
  const PRIORITY_RANKS = {critical: 4, high: 3, medium: 2, normal: 1, low: 0};
  const PRIORITY_DONUT_COLORS = {critical: '#620004', high: '#B98E2C', medium: '#5A5D5C', normal: '#B8B3A2', low: '#8E8D83'};
  const PRIORITY_FALLBACK = ['#404040', '#B98E2C', '#8E8D83', '#CCCABC', '#946F29', '#5A5D5C'];
  const priorityColor = (label, i) => PRIORITY_DONUT_COLORS[String(label).toLowerCase()] || PRIORITY_FALLBACK[i % PRIORITY_FALLBACK.length];

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
    const cols = keys.map(key => {
      const bucket = buckets.get(key), total = totalOf(key);
      const stack = ['external', 'internal'].map(type => bucket[type]
        ? `<div class="trend-seg ${type}" style="height:${bucket[type] / total * 100}%" title="${fmtNum(bucket[type])} ${type}"></div>`
        : '').join('');
      return `<div class="trend-col"><span class="trend-value">${fmtNum(total)}</span><div class="trend-stack" style="height:${total / max * 100}%">${stack}</div></div>`;
    }).join('');
    const legend = `<div class="trend-legend"><i class="internal"></i>Internal<i class="external"></i>External</div>`;
    return `<div class="trend">${cols}</div><div class="trend-labels">${keys.map(key => `<span class="trend-label">${label(key)}</span>`).join('')}</div>${legend}`;
  }

  const AUDIENCE_BANDS = ['< 1000', '1–10k', '10–50k', '50–100k', '> 100k'];
  const MULTISELECT_FIELDS = ['strategic_objectives', 'business_division', 'region'];
  const REQUIRED_COMMON = ['activity_name', 'channel', 'priority', 'strategic_objectives', 'activity_description', 'region', 'start_date', 'end_date', 'time_zone', 'lead', 'lead_team'];
  const REQUIRED_INTERNAL = REQUIRED_COMMON.concat(['target_audience', 'audience', 'business_division']);
  const REQUIRED_EXTERNAL = REQUIRED_COMMON.slice();
  const FIELD_LABELS = {activity_name:'Activity name', channel:'Channel', priority:'Priority', strategic_objectives:'Communications pillars', activity_description:'Description', target_audience:'Target audience', audience:'Estimated audience size', business_division:'Business division', region:'Region', start_date:'Start date', end_date:'End date', time_zone:'Time zone', lead:'Lead', lead_team:'Lead team', campaign:'Campaign', communication_pack_cpid:'Communication pack', business_area:'Business area', partner_team:'Partner team', news_digest:'News digest'};
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
    document.getElementById('activity-new').hidden = !canCreate();
    document.getElementById('pack-new').hidden = !canCreate();
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

  function toast(message) {
    const el = document.getElementById('toast');
    el.textContent = message;
    el.classList.add('show');
    window.setTimeout(() => el.classList.remove('show'), 2400);
  }

  function download(name, content, type) {
    const blob = new Blob([content], {type:type || 'application/octet-stream'});
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
    state.collisionsCache = new Map();
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

  function collisionsFor(proximityDays) {
    if (!state.collisionsCache.has(proximityDays)) {
      state.collisionsCache.set(proximityDays, A.detectCollisions(state.rows, {proximityDays}));
    }
    return state.collisionsCache.get(proximityDays);
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

  function kpi(label, value, sub, tone) {
    return `<div class="kpi ${tone||''}"><span class="kpi-label">${esc(label)}</span><strong class="kpi-value">${esc(value)}</strong><span class="kpi-sub">${esc(sub||'')}</span></div>`;
  }

  function countBy(rows, field) {
    const counts = new Map();
    rows.forEach(row => split(row[field]).forEach(value => counts.set(value,(counts.get(value)||0)+1)));
    return Array.from(counts.entries()).sort((a,b)=>b[1]-a[1]);
  }

  function barList(entries, bronze) {
    if (!entries.length) return emptyState(EMPTY_ICONS.barChart, 'No data available', 'Nothing to show for the current selection.');
    const max = Math.max(...entries.map(item=>item[1]),1);
    return `<div class="bar-list">${entries.slice(0,12).map(([label,value])=>`<div class="bar-row"><div class="bar-label" title="${esc(label)}">${esc(label)}</div><div class="bar-track"><div class="bar-fill ${bronze?'bronze':''}" style="width:${value/max*100}%"></div></div><div class="bar-value">${fmtNum(value)}</div></div>`).join('')}</div>`;
  }

  const missingLabels = missing => missing.map(field => FIELD_LABELS[field] || field);

  function renderOverview() {
    const rows = state.rows;
    const now = new Date();
    const future30 = new Date(now); future30.setDate(now.getDate()+30);
    const active = rows.filter(row => {const s=A.parseDate(row.start_date),e=A.parseDate(row.end_date)||s;return s&&s<=now&&e>=now;});
    const upcoming = rows.filter(row => {const d=A.parseDate(row.start_date);return d&&d>=now&&d<=future30;}).sort((a,b)=>A.parseDate(a.start_date)-A.parseDate(b.start_date));
    const internal = rows.filter(row=>row.source_type==='internal').length;
    const external = rows.filter(row=>row.source_type==='external').length;
    const collisions = collisionsFor(1).filter(item=>item.kind==='conflict');
    const conflictIds = new Set(); collisions.forEach(item=>{conflictIds.add(String(item.left.id));conflictIds.add(String(item.right.id));});
    const quality = A.dataQuality(rows);
    const lead = A.leadTimeStats(rows,7);

    // KPI row: portfolio counts plus one problem signal — the first scan line
    // must carry the portfolio's biggest issue, not two near-identical twins.
    document.getElementById('overview-kpis').innerHTML = [
      kpi('Total activities',fmtNum(rows.length),`${fmtNum(internal)} internal + ${fmtNum(external)} external`,''),
      kpi('Active now',fmtNum(active.length),'Currently running',''),
      kpi('Incomplete',fmtNum(quality.incomplete),`${quality.completenessRate}% fully complete`,quality.incomplete?'warning':'success'),
      kpi('Next 30 days',fmtNum(upcoming.length),'Upcoming activities','')
    ].join('');

    // Attention queue: aggregated by issue type instead of one row per finding.
    const incompleteRows = rows.filter(row=>A.planningCompleteness(row).score<100);
    const shortNoticeRows = rows.filter(row=>{const l=Number(row.planning_lead_days);return Number.isFinite(l)&&l>=0&&l<7;});
    const invalidRows = rows.filter(row=>{const s=A.parseDate(row.start_date),e=A.parseDate(row.end_date);return s&&e&&e<s;});
    const totalIssues = incompleteRows.length+shortNoticeRows.length+invalidRows.length+collisions.length;
    document.getElementById('attention-count').textContent = totalIssues;
    document.getElementById('attention-subtitle').textContent = `${fmtNum(totalIssues)} findings grouped by issue type`;
    // P10: the card's top border is a status signal, not decoration — red
    // only while findings are outstanding, neutral the moment the queue
    // clears (class consumed by styles.css: .priority-card.danger).
    const priorityCard = document.querySelector('.priority-card');
    if (priorityCard) priorityCard.classList.toggle('danger', totalIssues > 0);
    const missingCounts = new Map();
    incompleteRows.forEach(row=>A.planningCompleteness(row).missing.forEach(field=>missingCounts.set(field,(missingCounts.get(field)||0)+1)));
    const topMissing = Array.from(missingCounts.entries()).sort((a,b)=>b[1]-a[1])[0];
    const groups = [];
    if (incompleteRows.length) groups.push({severity:'high',title:`${fmtNum(incompleteRows.length)} activities with missing fields`,meta:topMissing?`Largest gap: ${esc(FIELD_LABELS[topMissing[0]]||topMissing[0])} (${fmtNum(topMissing[1])})`:'',action:'Review list',queue:'incomplete'});
    if (shortNoticeRows.length) groups.push({severity:'critical',title:`${fmtNum(shortNoticeRows.length)} activities on short notice`,meta:`Under 7 days lead time · median ${lead.median===null?'—':lead.median+'d'}`,action:'Review list',queue:'short-notice'});
    if (invalidRows.length) groups.push({severity:'critical',title:`${fmtNum(invalidRows.length)} invalid date ranges`,meta:'End date before start date',action:'Review list',queue:'invalid-date'});
    if (collisions.length) groups.push({severity:'medium',title:`${fmtNum(collisions.length)} scheduling ${collisions.length===1?'conflict':'conflicts'}`,meta:'Shared audience and channel',action:'Open conflicts',queue:'conflicts'});
    const deadlineRows = upcoming.filter(row=>A.planningCompleteness(row).score<100||shortNoticeRows.includes(row)).slice(0,5);
    const deadlines = deadlineRows.map(row=>{
      const completeness=A.planningCompleteness(row);
      const reason=completeness.score<100?`Missing: ${missingLabels(completeness.missing).slice(0,2).join(', ')}`:`Short notice: ${row.planning_lead_days}d lead`;
      const focus=completeness.missing[0]||'';
      return `<div class="list-row"><span class="severity-line ${completeness.score<100?'high':'critical'}"></span><div><div class="list-title">${esc(row.activity_name||'Untitled')}</div><div class="list-meta">Starts ${fmtDate(row.start_date)} · ${esc(reason)}</div></div><button type="button" class="fix-link" data-fix-id="${esc(row.id||'')}" data-fix-field="${esc(focus)}">Fix now</button></div>`;
    }).join('');
    document.getElementById('attention-list').innerHTML = groups.length
      ? groups.map(group=>`<div class="queue-group"><span class="severity-line ${group.severity}"></span><div><div class="list-title">${group.title}</div><div class="list-meta">${group.meta}</div></div><button type="button" class="link-btn" data-queue="${group.queue}">${group.action}</button></div>`).join('')+(deadlines?`<div class="queue-heading">Nearest deadlines</div>${deadlines}`:'')
      : emptyState(EMPTY_ICONS.checkCircle, 'No planning issues detected', 'Nothing needs review right now.');

    document.getElementById('readiness-summary').innerHTML = `<div class="metric-line"><span>Fully complete</span><strong>${fmtNum(rows.length-quality.incomplete)}</strong></div><div class="progress"><span style="width:${quality.completenessRate}%"></span></div><div class="metric-line"><span>Missing pack/campaign</span><strong>${fmtNum(quality.missingPackIds)}</strong></div><div class="metric-line"><span>Invalid date range</span><strong>${fmtNum(quality.invalidDateRanges)}</strong></div><div class="metric-line"><span>Total activities</span><strong>${fmtNum(rows.length)}</strong></div>`;

    // Upcoming: grouped by week, channel chip per row, conflict marker.
    const weekKey = date => {const d=new Date(date);const day=(d.getDay()+6)%7;d.setDate(d.getDate()-day);d.setHours(0,0,0,0);return d;};
    const weekGroups = new Map();
    upcoming.slice(0,16).forEach(row=>{const key=weekKey(A.parseDate(row.start_date)).getTime();if(!weekGroups.has(key))weekGroups.set(key,[]);weekGroups.get(key).push(row);});
    document.getElementById('upcoming-list').innerHTML = upcoming.length
      ? Array.from(weekGroups.entries()).map(([key,items])=>`<div class="week-heading">Week of ${fmtDate(new Date(Number(key)))}</div>`+items.map(row=>`<div class="list-row" data-open-id="${esc(row.id||'')}"><span class="severity-line medium"></span><div><div class="list-title">${esc(row.activity_name||'Untitled')}</div><div class="list-meta">${fmtDate(row.start_date)} · ${esc(row.lead_team||row.lead||'Unassigned')}</div></div><span>${row.channel?`<span class="chip">${esc(row.channel)}</span>`:''}${conflictIds.has(String(row.id))?'<span class="chip conflict">Conflict</span>':''}</span></div>`).join('')).join('')
      : emptyState(EMPTY_ICONS.calendar, 'No activities in the next 30 days', 'Check back later or widen the planning horizon.');

    renderChannelLoad();
    // Both donuts carry a centre number with a small unit label so the two
    // cannot be misread against each other: divisions count MENTIONS
    // (multi-division activities count once per division), priorities count
    // activities.
    document.getElementById('division-donut').innerHTML = donutHtml(countBy(rows,'business_division'),(label,i)=>DONUT_SEQUENCE[i%DONUT_SEQUENCE.length],null,'mentions');
    const priorityEntries = countBy(rows,'priority').sort((a,b)=>(PRIORITY_RANKS[String(b[0]).toLowerCase()]??1)-(PRIORITY_RANKS[String(a[0]).toLowerCase()]??1));
    document.getElementById('priority-donut').innerHTML = donutHtml(priorityEntries,priorityColor,null,'activities');
    renderTrend();
  }

  function renderChannelLoad() {
    const weeks = state.channelHorizonWeeks;
    let scoped = state.rows;
    if (weeks > 0) {
      const now = new Date(); const end = new Date(now); end.setDate(end.getDate()+weeks*7);
      scoped = state.rows.filter(row=>{const d=A.parseDate(row.start_date);return d&&d>=now&&d<=end;});
    }
    // Zeros are the answer, not noise: every known channel renders even when
    // nothing starts in the horizon — an idle channel is the "underused
    // channel" leadership is looking for.
    const scopedCounts = new Map(countBy(scoped,'channel'));
    const entries = countBy(state.rows,'channel').map(([label])=>[label,scopedCounts.get(label)||0]).sort((a,b)=>b[1]-a[1]);
    const allTime = countBy(state.rows,'channel').slice(0,3).map(([label,count])=>`${label} ${fmtNum(count)}`).join(' · ');
    const footer = weeks>0&&allTime?`<div class="list-meta" style="margin-top:10px">All-time volume: ${esc(allTime)}</div>`:'';
    document.getElementById('channel-load').innerHTML = (entries.length?barList(entries):emptyState(EMPTY_ICONS.barChart,'No channels in the data yet','Create activities to see channel load.'))+footer;
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
    const conflictIds = new Set();
    collisionsFor(1).filter(item=>item.kind==='conflict').forEach(item=>{conflictIds.add(String(item.left.id));conflictIds.add(String(item.right.id));});

    const lanes = new Map();
    rows.forEach(row=>{const key=grouping.of(row);if(!lanes.has(key))lanes.set(key,[]);lanes.get(key).push(row);});
    const weeks = coverage;
    let html=`<div class="timeline"><div class="timeline-grid" style="grid-template-columns:190px repeat(${weeks.length},minmax(58px,1fr))"><div class="timeline-head">Activity</div>${weeks.map(w=>`<div class="timeline-head">${fmtDate(w.from).replace(/\s\d{4}$/,'')}</div>`).join('')}`;
    Array.from(lanes.entries()).sort((a,b)=>b[1].length-a[1].length).forEach(([lane,laneRows])=>{
      html+=`<div class="timeline-group">${esc(lane)} (${laneRows.length})</div>`;
      laneRows.slice(0,BOARD_LANE_LIMIT).forEach(row=>{
        const start=A.parseDate(row.start_date),end=A.parseDate(row.end_date)||start;
        const conflict=conflictIds.has(String(row.id));
        html+=`<div class="timeline-label" data-open-id="${esc(row.id||'')}" title="${esc(row.activity_name||'')}">${esc(row.activity_name||'Untitled')}</div>`;
        weeks.forEach((w,i)=>{
          const overlaps=start&&start<w.to&&end>=w.from;
          const isFirst=overlaps&&!(start<w.from);
          const isLast=overlaps&&!(end>=w.to);
          const cls=`timeline-bar${row.source_type==='external'?' external':''}${conflict?' conflict':''}${isFirst?' start':''}${isLast?' end':''}`;
          html+=`<div class="timeline-cell">${overlaps?`<span class="${cls}" title="${esc(row.channel||'')}${conflict?' · overlaps with another activity':''}"></span>`:''}</div>`;
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

  function filteredConflicts() {
    const proximity=Number(document.getElementById('conflict-proximity').value),type=document.getElementById('conflict-type').value,severity=document.getElementById('conflict-severity').value;
    return collisionsFor(proximity).filter(item=>(!type||item.kind===type)&&(!severity||item.severity===severity));
  }

  function renderConflicts() {
    const all=collisionsFor(Number(document.getElementById('conflict-proximity').value)),items=filteredConflicts();
    const conflicts=all.filter(i=>i.kind==='conflict'),orchestration=all.filter(i=>i.kind==='orchestration');
    document.getElementById('conflict-kpis').innerHTML=[kpi('Matching pairs',items.length,'Current filters',''),kpi('Critical',conflicts.filter(i=>i.severity==='critical').length,'Requires review',conflicts.some(i=>i.severity==='critical')?'danger':''),kpi('Other conflicts',conflicts.filter(i=>i.severity!=='critical').length,'Potential competition',conflicts.some(i=>i.severity!=='critical')?'warning':''),kpi('Orchestration',orchestration.length,'Same-pack coordination','')].join('');
    document.getElementById('conflict-list').innerHTML=items.length?items.slice(0,60).map(item=>{const reason=`${item.gapDays===0?'Same day':item.gapDays+' day gap'} · ${esc(item.left.channel||'No channel')} · ${esc(split(item.left.target_audience)[0]||'Shared audience')}`;return `<div class="conflict-row"><div class="conflict-top"><div><span class="badge ${esc(item.severity)}">${esc(item.severity)}</span> <span class="badge ${item.kind==='orchestration'?'info':'neutral'}">${esc(item.kind)}</span></div><span class="list-meta">${reason}</span></div><div class="conflict-pair"><div class="conflict-item" data-open-id="${esc(item.left.id||'')}"><strong>${esc(item.left.activity_name||'Untitled')}</strong><br>${esc(campaignLabel(item.left)||'No campaign')}</div><div class="conflict-vs">overlaps with</div><div class="conflict-item" data-open-id="${esc(item.right.id||'')}"><strong>${esc(item.right.activity_name||'Untitled')}</strong><br>${esc(campaignLabel(item.right)||'No campaign')}</div></div></div>`;}).join(''):emptyState(EMPTY_ICONS.checkCircle, 'No matching conflicts', 'Try widening the proximity window or clearing filters.');
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
    const ownershipRows=future.map(row=>Object.assign({},row,{lead_team:row.lead_team||row.lead||'Unassigned'}));
    document.getElementById('coverage-dimensions').innerHTML=`<div class="grid two"><div><h3>Lead teams</h3>${barList(countBy(ownershipRows,'lead_team'))}</div><div><h3>Communications pillars</h3>${barList(countBy(future,'strategic_objectives'))}</div></div>`;
  }

  function populateActivityFilters() {
    const fill=(id,values,label)=>{const el=document.getElementById(id),current=el.value;el.innerHTML=`<option value="">All ${label}</option>`+values.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');el.value=current;};
    fill('activity-channel',countBy(state.rows,'channel').map(x=>x[0]),'channels');
    fill('activity-priority',countBy(state.rows,'priority').map(x=>x[0]),'priorities');
    const campaigns=new Set();
    state.rows.forEach(row=>{const label=campaignLabel(row);if(label)campaigns.add(label);});
    fill('activity-campaign',Array.from(campaigns).sort((a,b)=>a.localeCompare(b)),'campaigns / packs');
  }

  // Transient filter applied from the Overview attention queue ("Review list").
  function matchesQueueFilter(row) {
    if (!state.queueFilter) return true;
    if (state.queueFilter==='incomplete') return A.planningCompleteness(row).score<100;
    if (state.queueFilter==='short-notice') {const l=Number(row.planning_lead_days);return Number.isFinite(l)&&l>=0&&l<7;}
    if (state.queueFilter==='invalid-date') {const s=A.parseDate(row.start_date),e=A.parseDate(row.end_date);return Boolean(s&&e&&e<s);}
    return true;
  }

  const QUEUE_FILTER_LABELS = {incomplete:'Missing fields', 'short-notice':'Short notice', 'invalid-date':'Invalid dates'};

  function applyActivityFilters() {
    const q=document.getElementById('activity-search').value.toLowerCase(),source=document.getElementById('activity-source').value,channel=document.getElementById('activity-channel').value,priority=document.getElementById('activity-priority').value,campaign=document.getElementById('activity-campaign').value,readiness=document.getElementById('activity-readiness').value;
    const rows=state.rows.filter(row=>{
      const complete=A.planningCompleteness(row).score===100;
      return matchesQueueFilter(row)&&(!q||Object.values(row).some(value=>String(value||'').toLowerCase().includes(q)))&&(!source||row.source_type===source)&&(!channel||split(row.channel).includes(channel))&&(!priority||split(row.priority).includes(priority))&&(!campaign||campaignLabel(row)===campaign)&&(!readiness||(readiness==='complete'&&complete)||(readiness==='incomplete'&&!complete));
    }).sort((a,b)=>(A.parseDate(b.start_date)||0)-(A.parseDate(a.start_date)||0));
    state.filteredRows=rows;
    const queueNote=state.queueFilter?` · ${QUEUE_FILTER_LABELS[state.queueFilter]||state.queueFilter} — Clear to remove`:'';
    document.getElementById('activity-result-count').textContent=`${fmtNum(rows.length)} of ${fmtNum(state.rows.length)}${queueNote}`;
    document.getElementById('activity-table-body').innerHTML=rows.map(row=>{
      const ready=A.planningCompleteness(row);
      const readiness=ready.score===100
        ?'<span class="readiness-ok">—</span>'
        :`<button type="button" class="badge warn" data-fix-id="${esc(row.id||'')}" data-fix-field="${esc(ready.missing[0]||'')}" title="${esc(missingLabels(ready.missing).join(', '))}"><span class="dot"></span>${ready.missing.length} missing</button>`;
      const duplicateBtn = canCreate() ? `<button type="button" class="icon-btn duplicate-btn" data-duplicate-id="${esc(row.id||'')}" aria-label="Duplicate ${esc(row.activity_name||'activity')}" title="Duplicate"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg></button>` : '';
      return `<tr data-open-id="${esc(row.id||'')}"><td><button type="button" class="name-btn" data-open-id="${esc(row.id||'')}" title="${esc(row.activity_name||'')}">${esc(row.activity_name||'Untitled')}</button></td><td>${trackingIdHtml(row.tracking_id,{copy:nonempty(row.tracking_id)})}</td><td>${esc(row.channel||'—')}</td><td>${fmtDate(row.start_date)}</td><td>${esc(row.priority||'—')}</td><td>${esc(row.lead_team||row.lead||'—')}</td><td>${esc(campaignLabel(row)||'—')}</td><td>${readiness}</td><td class="action-cell"><div class="row-actions">${duplicateBtn}</div></td></tr>`;}).join('')||`<tr><td colspan="9">${emptyState(EMPTY_ICONS.search, 'No activities match the filters', 'Clear filters or adjust your search to see more results.')}</td></tr>`;
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
    const fields=new Map();rows.forEach(row=>A.planningCompleteness(row).missing.forEach(field=>fields.set(field,(fields.get(field)||0)+1)));
    document.getElementById('missing-fields').innerHTML=barList(Array.from(fields.entries()).map(([field,count])=>[FIELD_LABELS[field]||field,count]).sort((a,b)=>b[1]-a[1]));
    const teamRows=new Map();rows.forEach(row=>{const key=row.lead_team||row.lead||'Unassigned';if(!teamRows.has(key))teamRows.set(key,[]);teamRows.get(key).push(row);});
    document.getElementById('team-health').innerHTML=`<table><thead><tr><th>Team</th><th class="num">Activities</th><th class="num">Complete</th><th class="num">Short notice</th><th class="num">Median lead</th></tr></thead><tbody>${Array.from(teamRows.entries()).map(([team,items])=>{const q=A.dataQuality(items),l=A.leadTimeStats(items,7);return `<tr><td>${esc(team)}</td><td class="num">${items.length}</td><td class="num">${q.completenessRate}%</td><td class="num">${l.shortNoticeRate}%</td><td class="num">${l.median===null?'—':l.median+'d'}</td></tr>`;}).join('')}</tbody></table>`;
  }

  function renderStrategic() {
    const rows=state.rows,aligned=rows.filter(r=>nonempty(r.strategic_objectives)),objectives=countBy(rows,'strategic_objectives'),divisions=countBy(rows,'business_division'),unaligned=rows.filter(r=>!nonempty(r.strategic_objectives));
    document.getElementById('strategic-kpis').innerHTML=[kpi('Aligned',`${rows.length?Math.round(aligned.length/rows.length*100):0}%`,`${aligned.length} activities`,''),kpi('Unaligned',unaligned.length,'No pillar assigned',unaligned.length?'danger':'success'),kpi('Pillars',objectives.length,'Unique values',''),kpi('Divisions',divisions.length,'Represented','')].join('');
    document.getElementById('objective-coverage').innerHTML=barList(objectives);
    document.getElementById('division-coverage').innerHTML=barList(divisions);
    document.getElementById('unaligned-list').innerHTML=unaligned.length?unaligned.slice(0,30).map(row=>`<div class="list-row" data-open-id="${esc(row.id||'')}"><span class="severity-line high"></span><div><div class="list-title">${esc(row.activity_name||'Untitled')}</div><div class="list-meta">${fmtDate(row.start_date)} · ${esc(row.lead_team||row.lead||'Unassigned')}</div></div><span class="badge warning">Unaligned</span></div>`).join(''):emptyState(EMPTY_ICONS.checkCircle, 'All activities have a communications pillar', 'Nothing left to align.');
  }

  function renderCampaignQuality() {
    const cards=A.campaignScorecards(state.rows),multi=cards.filter(c=>c.channels>1),single=cards.filter(c=>c.channels===1),avg=cards.length?Math.round(cards.reduce((s,c)=>s+c.activities,0)/cards.length*10)/10:0;
    document.getElementById('campaign-kpis').innerHTML=[kpi('Packs / campaigns',cards.length,'Identified planning units',''),kpi('Multi-channel',multi.length,`${cards.length?Math.round(multi.length/cards.length*100):0}% of units`,''),kpi('Single-channel',single.length,'Review orchestration',single.length?'warning':''),kpi('Avg activities',avg,'Per planning unit','')].join('');
    document.getElementById('campaign-scorecard').innerHTML=cards.length?`<table><thead><tr><th>Campaign / pack</th><th class="num">Activities</th><th class="num">Channels</th><th>Channel mix</th><th class="num">Objectives</th><th class="num">Audiences</th><th>Activity window</th><th class="num"><span class="th-help" title="Longest quiet period between the first and last activity of this pack or campaign">Quiet period ⓘ</span></th></tr></thead><tbody>${cards.slice(0,50).map(card=>`<tr><td>${esc(card.campaign)}</td><td class="num">${card.activities}</td><td class="num"><span class="badge ${card.channels>1?'success':'warning'}">${card.channels}</span></td><td title="${esc(card.channelNames.join(', '))}">${esc(card.channelNames.join(', ')||'—')}</td><td class="num">${card.objectives}</td><td class="num">${card.audiences}</td><td>${fmtDate(card.firstDate)} – ${fmtDate(card.lastDate)}</td><td class="num">${card.channelGapDays===null?'—':card.channelGapDays+'d'}</td></tr>`).join('')}</tbody></table>`:emptyState(EMPTY_ICONS.layers, 'No campaign or pack identifiers available', 'Add a campaign, pack ID, or tracking pack to group activities.');
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

  function renderDataQuality() {
    const q=A.dataQuality(state.rows),generated=state.meta&&(state.meta.generated_at_iso||state.meta.generated_at)||'Unknown';
    document.getElementById('quality-kpis').innerHTML=[kpi('Complete records',`${q.completenessRate}%`,`${q.incomplete} incomplete`,q.incomplete?'warning':'success'),kpi('Duplicate IDs',q.duplicateTrackingIds,'Unique duplicated identifiers',q.duplicateTrackingIds?'danger':'success'),kpi('Missing IDs',q.missingTrackingIds,'Cannot safely edit',q.missingTrackingIds?'danger':'success'),kpi('Invalid dates',q.invalidDateRanges,'End before start',q.invalidDateRanges?'danger':'success')].join('');
    document.getElementById('quality-diagnostics').innerHTML=[['Missing campaign / pack',q.missingPackIds],['Incomplete planning records',q.incomplete],['Duplicate tracking IDs',q.duplicateTrackingIds],['Missing tracking IDs',q.missingTrackingIds],['Invalid date ranges',q.invalidDateRanges]].map(([label,value])=>`<div class="metric-line"><span>${esc(label)}</span><strong>${fmtNum(value)}</strong></div>`).join('');
    document.getElementById('reconciliation').innerHTML=`<div class="metric-line"><span>API refresh</span><strong>${esc(String(generated))}</strong></div><div class="metric-line"><span>${esc(backendLabel())} rows</span><strong>${fmtNum(state.snapshotRows.length)}</strong></div><div class="metric-line"><span>Write adapter</span><strong>${esc(backendLabel())} REST API</strong></div>${syncRunSummaryHtml()}<div class="notice"><strong>Versioned writes:</strong> stale updates are rejected with HTTP 409 and must be reviewed against the current database record.</div>`;
  }

  function updateActivitiesCount() {
    document.getElementById('activities-count').textContent = fmtNum(state.rows.length);
  }

  function renderAll() {
    refreshRows(); renderOverview(); renderBoard(); renderCalendar(); renderConflicts(); renderCapacity(); populateActivityFilters(); applyActivityFilters(); renderPlanningHealth(); renderStrategic(); renderCampaignQuality(); renderDataQuality(); updateActivitiesCount(); bindOpenRows(); bindDuplicateButtons();
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
        if(state.editing)state.dirty=true;
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
    const internal=sourceType==='internal';
    document.querySelectorAll('#activity-form [data-variant="internal"]').forEach(el=>{el.hidden=!internal;});
    document.querySelectorAll('#activity-form .req[data-vreq]').forEach(el=>{el.hidden=!internal;});
  }

  function currentSourceType() {
    const active=document.querySelector('#source-toggle button.active');
    return active?active.dataset.source:'internal';
  }

  function setSourceToggle(source) {
    document.querySelectorAll('#source-toggle button').forEach(btn=>btn.classList.toggle('active',btn.dataset.source===source));
  }

  function focusField(name) {
    const container=msContainer(name);
    if(container){container.querySelector('.ms-trigger').focus();return;}
    const el=form().elements[name];
    if(el&&typeof el.focus==='function')el.focus();
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
  // "re-fetched on reopen after save" for free, since saveDraft closes the
  // drawer and any later re-open goes through openDrawer -> loadHistory again.
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
    if (row&&nonempty(row.tracking_id)) {
      el.innerHTML=`<div class="tracking-row"><span class="tracking-label">Tracking ID</span>${trackingIdHtml(row.tracking_id,{copy:true})}<span class="tid-help" title="${esc(TRACKING_ID_TITLE)}">i</span></div>${rule}`;
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
        const display=has?esc(String(value)):(editable?`<button type="button" class="detail-add" data-add-field="${esc(field)}">— Add</button>`:'—');
        return `<div class="detail-row"><dt>${esc(label)}</dt><dd>${display}</dd></div>`;
      }).join('');
      return rowsHtml?`<div class="detail-section"><h4>${esc(section.title)}</h4><dl>${rowsHtml}</dl></div>`:'';
    }).join('');
    const digest=row.source_type==='internal'?`<div class="detail-section"><h4>Visibility</h4><dl><div class="detail-row"><dt>News digest</dt><dd>${row.news_digest?'Considered':'Not considered'}</dd></div></dl></div>`:'';
    document.getElementById('detail-view').innerHTML=sections+digest;
    document.getElementById('detail-view').querySelectorAll('[data-add-field]').forEach(btn=>{
      btn.onclick=()=>{setDrawerEditing(true);focusField(btn.dataset.addField);};
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
    document.querySelector('.drawer-actions').style.display='flex';
    document.getElementById('form-validation').textContent='';
    document.getElementById('form-variant').hidden=false;
    document.getElementById('drawer-history').hidden=true;
    document.getElementById('pack-summary').hidden=true;
  }

  function openCreateDrawer(opener) {
    state.selected=null;state.creating=true;state.packing=false;state.editing=true;state.dirty=false;state.drawerOpener=opener||document.activeElement;
    prepareCreateChrome('New activity','Single channel, single date — the tracking ID is minted on save from channel and start date.');
    document.getElementById('drawer-save').textContent='Create activity';
    setSourceToggle('internal');
    resetCreateForm();
    setPackMode(false);
    applyVariant('internal');
    populateSelectOptions('internal');
    syncBelongsToFromFields();
    renderMultiselectOptions();
    setFormEnabled(true);
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

  function packSelectedChannels() {
    return Array.from(document.querySelectorAll('#pack-channels input:checked')).map(input=>input.value);
  }

  function renderPackChannels(sourceType) {
    const all=distinctChannels(sourceType).slice();
    state.customChannels.forEach(channel=>{if(!all.includes(channel))all.push(channel);});
    const selected=packSelectedChannels();
    document.getElementById('pack-channels').innerHTML=all.length
      ?all.map(channel=>`<label class="ms-option"><input type="checkbox" value="${esc(channel)}"${selected.includes(channel)?' checked':''}><span>${esc(channel)}</span></label>`).join('')
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

  function renderPackRows() {
    const previousRows=packRowValues();
    const previous=new Map(previousRows.map(row=>[row.channel,row]));
    const first=previousRows[0];
    const packName=String(form().elements.pack_name.value||'').trim();
    document.getElementById('pack-rows').innerHTML=packSelectedChannels().map(channel=>{
      const prev=previous.get(channel);
      const name=prev?prev.name:(packName?`${packName} — ${channel}`:channel);
      const start=prev?prev.start:(first?first.start:'');
      const end=prev?prev.end:(first?first.end:'');
      return `<div class="pack-row" data-channel="${esc(channel)}"><div class="pack-row-channel">${esc(channel)}</div><label>Activity name <span class="req">*</span><input data-pack-name value="${esc(name)}"></label><div class="form-grid"><label>Start date (local time) <span class="req">*</span><input type="datetime-local" data-pack-start value="${esc(start)}"></label><label>End date (local time) <span class="req">*</span><input type="datetime-local" data-pack-end value="${esc(end)}"></label></div><div class="pack-stub" data-pack-stub></div></div>`;
    }).join('')||'<div class="ms-empty">Select at least one channel above</div>';
    updatePackSubmitLabel();
  }

  // The informed commit: live tracking-ID stubs per channel row plus a sticky
  // pre-save summary — this is where channel + date + pack → ID is learned.
  function updatePackStubs() {
    if(!state.packing)return;
    const prefix=packIdPrefix();
    document.querySelectorAll('#pack-rows .pack-row').forEach(rowEl=>{
      const channel=rowEl.dataset.channel;
      const start=rowEl.querySelector('[data-pack-start]').value;
      rowEl.querySelector('[data-pack-stub]').innerHTML=`Tracking ID <span class="tracking-id"><span class="tid-prefix">${esc(prefix)}-</span><span class="tid-date">${esc(stubDate(start))}</span>-<span class="tid-seq">…</span>-<span class="tid-channel">${esc(channelAbbr(channel))}</span></span> · sequence assigned on save`;
    });
    const rows=packRowValues();
    const summary=document.getElementById('pack-summary');
    if(!rows.length){summary.hidden=true;return;}
    summary.hidden=false;
    summary.innerHTML=`<strong>Creates ${rows.length} ${rows.length===1?'activity':'activities'}</strong>`+rows.map(row=>`<div class="pack-summary-row"><span>${esc(row.name||row.channel)}</span><span>${row.start?fmtDate(row.start):'no date'} · <span class="tracking-id"><span class="tid-prefix">${esc(packIdPrefix())}-</span>${esc(stubDate(row.start))}-…-${esc(channelAbbr(row.channel))}</span></span></div>`).join('');
  }

  function updatePackSubmitLabel() {
    if(!state.packing)return;
    const count=packSelectedChannels().length;
    document.getElementById('drawer-save').textContent=count?`Create ${count} ${count===1?'activity':'activities'}`:'Create activities';
    updatePackStubs();
  }

  function openPackDrawer(opener) {
    state.selected=null;state.creating=false;state.packing=true;state.editing=true;state.dirty=false;state.customChannels=[];state.drawerOpener=opener||document.activeElement;
    prepareCreateChrome('New communication pack','Pick channels first — each channel becomes one activity with its own tracking ID.');
    setSourceToggle('internal');
    resetCreateForm();
    applyVariant('internal');
    populateSelectOptions('internal');
    renderMultiselectOptions();
    setFormEnabled(true);
    setPackMode(true);
    // Start from a clean slate: the checkbox/row DOM survives closeDrawer, so
    // a previous pack session's selection and row values must not leak into a
    // new pack (renderPackChannels/renderPackRows preserve current DOM state).
    document.getElementById('pack-channels').innerHTML='';
    document.getElementById('pack-rows').innerHTML='';
    document.getElementById('pack-channel-new').value='';
    renderPackChannels('internal');
    renderPackRows();
    document.getElementById('activity-drawer').classList.add('open');
    document.getElementById('activity-drawer').setAttribute('aria-hidden','false');
    form().elements.pack_name.focus();
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
    document.getElementById('activity-drawer').classList.add('open');
    document.getElementById('activity-drawer').setAttribute('aria-hidden','false');
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

  async function submitPack(event) {
    event.preventDefault();
    const sourceType=currentSourceType(),validation=document.getElementById('form-validation');
    const value=name=>{const el=form().elements[name];return el?String(el.value||'').trim():'';};
    if(!value('pack_name')){
      validation.textContent='Pack name is required.';
      focusField('pack_name');
      return;
    }
    const required=(sourceType==='internal'?REQUIRED_INTERNAL:REQUIRED_EXTERNAL).filter(name=>!PACK_ROW_FIELDS.includes(name)&&name!=='activity_name');
    const missing=required.filter(name=>!value(name));
    if(missing.length&&!await confirmSaveIncomplete(missing))return;
    const rows=packRowValues();
    if(!rows.length){validation.textContent='Select at least one channel.';return;}
    for(const row of rows){
      if(!row.name.trim()){validation.textContent=`${row.channel}: activity name is required.`;return;}
      if(!row.start||!row.end){validation.textContent=`${row.channel}: start and end date are required.`;return;}
      const start=A.parseDate(row.start),end=A.parseDate(row.end);
      if(start&&end&&end<start){validation.textContent=`${row.channel}: end date cannot be before start date.`;return;}
    }
    const shared={source_type:sourceType};
    CREATE_FIELDS.forEach(name=>{
      if(PACK_ROW_FIELDS.includes(name))return;
      if(name==='audience'&&sourceType!=='internal')return;
      const raw=value(name);
      if(raw)shared[name]=raw;
    });
    // Pack mode replaces the circular campaign/pack pair with one pack name
    // (stored as the communication pack) plus an optional campaign umbrella.
    shared.communication_pack=value('pack_name');
    const packCampaign=value('pack_campaign');
    if(packCampaign)shared.campaign=packCampaign;
    if(sourceType==='internal')shared.news_digest=form().elements.news_digest.checked;
    const items=rows.map(row=>Object.assign({},shared,{
      activity_name:row.name.trim(),
      channel:row.channel,
      start_date:new Date(row.start).toISOString(),
      end_date:new Date(row.end).toISOString(),
    }));
    validation.textContent='';
    try {
      const created=await repository.createActivitiesBatch(items);
      created.items.forEach(item=>state.snapshotRows.push(item));
      state.packing=false;state.dirty=false;
      const ids=created.items.map(item=>item.tracking_id).filter(Boolean);
      toast(`${created.items.length} activities created — ${ids.join(', ')}`);
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

  // Completeness check at save time instead of shame afterwards: missing
  // recommended fields raise an informed choice, not a hard block. Resolves
  // true = save as incomplete, false = go back (first missing field focused).
  function confirmSaveIncomplete(missing) {
    return new Promise(resolve => {
      if (state.incompleteModalOpen) { resolve(false); return; }
      state.incompleteModalOpen = true;
      const modal = document.getElementById('incomplete-modal');
      const saveBtn = document.getElementById('incomplete-save');
      const backBtn = document.getElementById('incomplete-back');
      const count = missing.length;
      document.getElementById('incomplete-modal-title').textContent = `Save with ${count} ${count===1?'field':'fields'} missing?`;
      document.getElementById('incomplete-modal-list').innerHTML = missing.map(name=>`<li><strong>${esc(FIELD_LABELS[name]||name)}</strong><span>required</span></li>`).join('');
      const settle = result => {
        modal.classList.remove('open');
        modal.setAttribute('aria-hidden','true');
        modal.removeEventListener('keydown', onKeydown);
        saveBtn.onclick = null; backBtn.onclick = null;
        state.incompleteModalOpen = false;
        if (!result) focusField(missing[0]);
        resolve(result);
      };
      const onKeydown = event => {
        if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); settle(false); return; }
        if (event.key === 'Tab') {
          event.preventDefault(); event.stopPropagation();
          (document.activeElement === saveBtn ? backBtn : saveBtn).focus();
        }
      };
      saveBtn.onclick = () => settle(true);
      backBtn.onclick = () => settle(false);
      modal.addEventListener('keydown', onKeydown);
      modal.classList.add('open');
      modal.setAttribute('aria-hidden','false');
      backBtn.focus();
    });
  }

  function setFormEnabled(enabled) {
    Array.from(form().elements).forEach(el=>{if(el.name)el.disabled=!enabled;});
    ['belongs-to','belongs-new'].forEach(id=>{document.getElementById(id).disabled=!enabled;});
    multiselectContainers().forEach(container=>setMultiselectEnabled(container,enabled));
  }

  function setDrawerEditing(editing) {
    const wasEditing=state.editing;
    state.editing=editing;state.creating=false;state.dirty=false;
    if(!editing)hideConflictBanner();
    setFormEnabled(editing);
    // Read-only shows the plain detail view; the form only exists while editing.
    document.getElementById('detail-view').hidden=editing;
    form().hidden=!editing;
    if(state.selected)setDrawerTracking(state.selected,editing);
    document.getElementById('drawer-mode-label').textContent=editing?'Editing':'Read only';
    document.getElementById('drawer-mode-label').className=`badge ${editing?'info':'neutral'}`;
    document.getElementById('drawer-mode-hint').hidden=!editing;
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
    document.querySelector('.drawer-actions').style.display=editing?'flex':'none';
    document.getElementById('drawer-save').textContent='Save activity';
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
      document.getElementById('form-validation').textContent = 'Rebased on the current record — Save activity will apply only the fields you changed.';
    };
    banner.scrollIntoView({block: 'nearest'});
  }

  async function saveDraft(event) {
    event.preventDefault();if(!state.selected||!state.selected.id||!state.selected.version)return;
    const data=new FormData(event.currentTarget),patch={};
    data.forEach((value,key)=>{if(key==='news_digest')return;let normalized=String(value);if((key==='start_date'||key==='end_date')&&normalized)normalized=new Date(normalized).toISOString();if(A.fieldValueChanged(key,state.selected[key],normalized))patch[key]=normalized===''?null:normalized;});
    if(state.selected.source_type==='internal'){const checked=form().elements.news_digest.checked;if(Boolean(state.selected.news_digest)!==checked)patch.news_digest=checked;}
    if(!patch.activity_name&&data.get('activity_name').trim()===''){document.getElementById('form-validation').textContent='Activity name is required.';return;}
    const start=A.parseDate(patch.start_date||state.selected.start_date),end=A.parseDate(patch.end_date||state.selected.end_date);if(start&&end&&end<start){document.getElementById('form-validation').textContent='End date cannot be before start date.';return;}
    if(!Object.keys(patch).length){toast('No changes to save');setDrawerEditing(false);return;}
    const merged=Object.assign({},state.selected,patch);
    const stillMissing=A.planningCompleteness(merged).missing;
    if(stillMissing.length&&!await confirmSaveIncomplete(stillMissing))return;
    const validation=document.getElementById('form-validation');
    try {
      const updated=await repository.updateActivity(state.selected.id,state.selected.version,patch);
      state.snapshotRows=state.snapshotRows.map(row=>row.id===updated.id?updated:row);
      toast(`Activity saved to ${backendLabel()}`);closeDrawer();renderAll();
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

  async function submitCreate(event) {
    event.preventDefault();
    const sourceType=currentSourceType(),validation=document.getElementById('form-validation');
    const value=name=>{const el=form().elements[name];return el?String(el.value||'').trim():'';};
    // Hard requirements feed the tracking ID (name, channel, dates); everything
    // else is a completeness recommendation the planner may defer past the
    // save-time intercept.
    const HARD_REQUIRED=['activity_name','channel','start_date','end_date'];
    const required=sourceType==='internal'?REQUIRED_INTERNAL:REQUIRED_EXTERNAL;
    const hardMissing=HARD_REQUIRED.filter(name=>!value(name));
    if(hardMissing.length){
      validation.textContent=`Complete the required fields: ${hardMissing.map(name=>FIELD_LABELS[name]||name).join(', ')}.`;
      focusField(hardMissing[0]);
      return;
    }
    const softMissing=required.filter(name=>!HARD_REQUIRED.includes(name)&&!value(name));
    if(softMissing.length&&!await confirmSaveIncomplete(softMissing))return;
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
      toast(`Activity created — ${created.tracking_id}`);
      renderAll();
      openDrawer(created,state.drawerOpener);
    } catch(error) {
      validation.textContent=error.message;
    }
  }

  function exportFilteredCsv() {
    const columns=['tracking_id','activity_name','channel','start_date','end_date','priority','lead','lead_team','target_audience','business_division','region','campaign','strategic_objectives','source_type'];
    const cell=value=>`"${A.safeCsvValue(value).replace(/"/g,'""')}"`;
    download(`CPLAN_activities_${new Date().toISOString().slice(0,10)}.csv`,[columns.join(','),...state.filteredRows.map(row=>columns.map(c=>cell(row[c])).join(','))].join('\n'),'text/csv');
  }

  function showPage(name) {
    document.querySelectorAll('.nav-item').forEach(x=>x.classList.toggle('active',x.dataset.page===name));
    document.querySelectorAll('.page').forEach(x=>x.classList.remove('active'));
    document.getElementById(`page-${name}`).classList.add('active');
  }

  function showSubpage(navName, subName) {
    const nav=document.querySelector(`[data-subnav="${navName}"]`);
    nav.querySelectorAll('.subnav-item').forEach(x=>x.classList.toggle('active',x.dataset.sub===subName));
    nav.parentElement.querySelectorAll(':scope > .subpage').forEach(x=>x.classList.remove('active'));
    document.getElementById(`sub-${subName}`).classList.add('active');
  }

  const RANGE_LABELS = {'30d':'last 30 days', quarter:'this quarter', ytd:'year to date', '12m':'last 12 months'};

  // The range banner is the per-page answer to "which data am I looking at":
  // visible on every tab whenever the range is narrower than All, naming the
  // range and the nesting rule (page horizons count within it).
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
    document.getElementById('channel-horizon').onclick=event=>{
      const btn=event.target.closest('button');if(!btn)return;
      document.querySelectorAll('#channel-horizon button').forEach(x=>x.classList.remove('active'));
      btn.classList.add('active');
      state.channelHorizonWeeks=Number(btn.dataset.weeks);
      renderChannelLoad();
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
      if(queueBtn){
        const queue=queueBtn.dataset.queue;
        if(queue==='conflicts'){showPage('planning');showSubpage('planning','conflicts');renderConflicts();bindOpenRows();return;}
        state.queueFilter=queue;
        document.getElementById('activity-readiness').value='';
        showPage('activities');
        applyActivityFilters();bindOpenRows();bindDuplicateButtons();
        return;
      }
      const fixBtn=event.target.closest('[data-fix-id]');
      if(fixBtn){
        event.stopPropagation();
        const row=state.rows.find(item=>String(item.id)===String(fixBtn.dataset.fixId));
        if(row)openDrawer(row,fixBtn,{edit:true,focus:fixBtn.dataset.fixField||null});
      }
      const copyBtn=event.target.closest('[data-copy-id]');
      if(copyBtn){
        event.stopPropagation();
        navigator.clipboard.writeText(copyBtn.dataset.copyId).then(()=>toast('Tracking ID copied')).catch(()=>toast('Copy failed'));
      }
    },true);
    document.querySelectorAll('[data-subnav]').forEach(nav=>nav.querySelectorAll('.subnav-item').forEach(btn=>btn.onclick=()=>{nav.querySelectorAll('.subnav-item').forEach(x=>x.classList.remove('active'));const page=nav.parentElement;page.querySelectorAll(':scope > .subpage').forEach(x=>x.classList.remove('active'));btn.classList.add('active');document.getElementById(`sub-${btn.dataset.sub}`).classList.add('active');}));
    document.getElementById('horizon-toggle').onclick=event=>{const btn=event.target.closest('button');if(!btn)return;document.querySelectorAll('#horizon-toggle button').forEach(x=>x.classList.remove('active'));btn.classList.add('active');state.horizonWeeks=Number(btn.dataset.weeks);renderBoard();bindOpenRows();};
    ['conflict-proximity','conflict-type','conflict-severity'].forEach(id=>document.getElementById(id).onchange=()=>{renderConflicts();bindOpenRows();});
    document.getElementById('cal-prev').onclick=()=>{state.calendarDate=new Date(state.calendarDate.getFullYear(),state.calendarDate.getMonth()-1,1);renderCalendar();bindOpenRows();};
    document.getElementById('cal-next').onclick=()=>{state.calendarDate=new Date(state.calendarDate.getFullYear(),state.calendarDate.getMonth()+1,1);renderCalendar();bindOpenRows();};
    document.getElementById('cal-today').onclick=()=>{state.calendarDate=new Date();renderCalendar();bindOpenRows();};
    const runActivityFilters=()=>{applyActivityFilters();bindOpenRows();bindDuplicateButtons();};
    const debouncedActivityFilters=debounce(runActivityFilters,200);
    document.getElementById('activity-search').addEventListener('input',debouncedActivityFilters);
    ['activity-source','activity-channel','activity-priority','activity-campaign','activity-readiness'].forEach(id=>document.getElementById(id).addEventListener('change',runActivityFilters));
    document.getElementById('activity-clear').onclick=()=>{state.queueFilter=null;['activity-search','activity-source','activity-channel','activity-priority','activity-campaign','activity-readiness'].forEach(id=>document.getElementById(id).value='');runActivityFilters();};
    document.getElementById('activity-export').onclick=exportFilteredCsv;
    document.getElementById('activity-new').onclick=event=>openCreateDrawer(event.currentTarget);
    document.getElementById('pack-new').onclick=event=>openPackDrawer(event.currentTarget);
    document.getElementById('pack-channels').addEventListener('change',()=>{renderPackRows();state.dirty=true;});
    document.getElementById('pack-rows').addEventListener('input',updatePackSubmitLabel);
    form().elements.pack_name.addEventListener('input',()=>{if(state.packing)updatePackStubs();});
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
    document.getElementById('pack-channel-add').onclick=()=>{
      const input=document.getElementById('pack-channel-new');
      const channel=String(input.value||'').trim();
      if(!channel)return;
      if(!state.customChannels.includes(channel))state.customChannels.push(channel);
      renderPackChannels(currentSourceType());
      const box=Array.from(document.querySelectorAll('#pack-channels input')).find(item=>item.value===channel);
      if(box)box.checked=true;
      input.value='';
      renderPackRows();
      state.dirty=true;
    };
    wireMultiselects();
    document.getElementById('source-toggle').onclick=event=>{
      const btn=event.target.closest('button');if(!btn)return;
      const source=btn.dataset.source;if(source===currentSourceType())return;
      setSourceToggle(source);applyVariant(source);populateSelectOptions(source);renderMultiselectOptions();
      if(state.packing){renderPackChannels(source);renderPackRows();}
      if(state.editing)state.dirty=true;
    };
    document.querySelectorAll('[data-close-drawer]').forEach(el=>el.onclick=async()=>{if(await confirmDiscardIfDirty())closeDrawer();});
    document.getElementById('drawer-edit').onclick=()=>{if(!state.selected||!state.selected.id){toast('Database ID required for safe editing');return;}setDrawerEditing(true);};
    document.getElementById('drawer-duplicate').onclick=()=>{if(state.selected)openDuplicateDrawer(state.selected,state.drawerOpener);};
    document.getElementById('drawer-delete').onclick=async()=>{
      if(!state.selected||!state.selected.id||!canDelete())return;
      const activityId=state.selected.id;
      if(!await openDeleteModal())return;
      await deleteActivity(activityId);
    };
    document.getElementById('user-chip-logout').onclick=()=>logout();
    document.getElementById('drawer-cancel').onclick=async()=>{
      if(!await confirmDiscardIfDirty())return;
      if(state.creating||state.packing){closeDrawer();return;}
      if(state.selected){const sourceType=state.selected.source_type||'internal';applyVariant(sourceType);populateSelectOptions(sourceType);populateDrawerForm(state.selected);syncBelongsToFromFields();renderMultiselectOptions();renderDetailView(state.selected);}
      setDrawerEditing(false);
    };
    const activityForm=document.getElementById('activity-form');
    activityForm.onsubmit=event=>state.packing?submitPack(event):state.creating?submitCreate(event):saveDraft(event);
    activityForm.addEventListener('input',()=>{if(state.editing)state.dirty=true;});
    activityForm.addEventListener('change',()=>{if(state.editing)state.dirty=true;});
    document.addEventListener('click',event=>{if(!event.target.closest('[data-multiselect]'))multiselectContainers().forEach(closeMsPopover);});
    document.addEventListener('keydown',async event=>{
      const isOpen=document.getElementById('activity-drawer').classList.contains('open');
      if(event.key==='Escape'){
        const openPop=document.querySelector('.ms-popover:not([hidden])');
        if(openPop){const container=openPop.closest('[data-multiselect]');closeMsPopover(container);container.querySelector('.ms-trigger').focus();return;}
        if(await confirmDiscardIfDirty())closeDrawer();return;
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
