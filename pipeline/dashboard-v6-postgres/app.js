(() => {
  'use strict';

  const A = window.CplanAnalytics;
  const COLORS = {grey:'#404040', bronze:'#B98E2C'};
  const state = {snapshotRows:[], rows:[], meta:null, syncRun:null, horizonWeeks:8, calendarDate:new Date(), selected:null, editing:false, creating:false, dirty:false, filteredRows:[], collisionsCache:new Map(), drawerOpener:null, discardModalOpen:false};

  const esc = A.escapeHtml;
  const fmtNum = value => Number(value || 0).toLocaleString('en-GB');
  const fmtDate = value => {
    const date = A.parseDate(value);
    return date ? date.toLocaleDateString('en-GB',{day:'2-digit',month:'short',year:'numeric'}) : '—';
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

  const AUDIENCE_BANDS = ['< 1000', '1–10k', '10–50k', '50–100k', '> 100k'];
  const MULTISELECT_FIELDS = ['strategic_objectives', 'business_division', 'region'];
  const REQUIRED_COMMON = ['activity_name', 'channel', 'priority', 'strategic_objectives', 'activity_description', 'region', 'start_date', 'end_date', 'time_zone', 'lead', 'lead_team'];
  const REQUIRED_INTERNAL = REQUIRED_COMMON.concat(['target_audience', 'audience', 'business_division']);
  const REQUIRED_EXTERNAL = REQUIRED_COMMON.slice();
  const FIELD_LABELS = {activity_name:'Activity name', channel:'Channel', priority:'Priority', strategic_objectives:'Communications pillars', activity_description:'Description', target_audience:'Target audience', audience:'Estimated audience size', business_division:'Business division', region:'Region', start_date:'Start date', end_date:'End date', time_zone:'Time zone', lead:'Lead', lead_team:'Lead team'};
  const CREATE_FIELDS = ['activity_name', 'activity_description', 'target_audience', 'business_division', 'business_area', 'region', 'channel', 'partner_team', 'lead_team', 'lead', 'start_date', 'end_date', 'time_zone', 'priority', 'strategic_objectives', 'campaign', 'communication_pack_cpid', 'audience'];

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

  class DatabasePlanningRepository {
    async request(path, options) {
      const response = await fetch(path, Object.assign({headers:{'Content-Type':'application/json'}}, options || {}));
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
    createActivity(payload) {
      return this.request('/api/activities', {method:'POST',body:JSON.stringify(payload)});
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

  function refreshRows() {
    state.rows = state.snapshotRows.slice();
    state.collisionsCache = new Map();
    updateDraftCount();
  }

  function updateDraftCount() {
    document.getElementById('overview-as-of').textContent = `Operational view: ${backendLabel()} live data`;
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

  function renderOverview() {
    const rows = state.rows;
    const now = new Date();
    const future30 = new Date(now); future30.setDate(now.getDate()+30);
    const active = rows.filter(row => {const s=A.parseDate(row.start_date),e=A.parseDate(row.end_date)||s;return s&&s<=now&&e>=now;});
    const upcoming = rows.filter(row => {const d=A.parseDate(row.start_date);return d&&d>=now&&d<=future30;}).sort((a,b)=>A.parseDate(a.start_date)-A.parseDate(b.start_date));
    const attention = A.attentionItems(rows,{shortNoticeDays:7});
    const collisions = collisionsFor(1).filter(item=>item.kind==='conflict');
    collisions.forEach(item => attention.push({type:'collision',severity:item.severity,row:item.left,detail:`With ${item.right.activity_name||'another activity'} · ${item.gapDays}d gap`}));
    const quality = A.dataQuality(rows);
    const lead = A.leadTimeStats(rows,7);
    document.getElementById('overview-kpis').innerHTML = [
      kpi('Activities',fmtNum(rows.length),`${active.length} active now`,'highlight'),
      kpi('Complete',`${quality.completenessRate}%`,`${quality.incomplete} need remediation`,quality.completenessRate>=80?'success':'warning'),
      kpi('Short notice',`${lead.shortNoticeRate}%`,`${lead.shortNotice} of ${lead.valid} valid records`,lead.shortNoticeRate>25?'danger':'warning'),
      kpi('Conflicts',fmtNum(collisions.length),'Shared audience and channel',collisions.length?'danger':'success')
    ].join('');
    document.getElementById('attention-count').textContent = attention.length;
    document.getElementById('attention-list').innerHTML = attention.length ? attention.slice(0,18).map(item=>`<div class="list-row" data-open-id="${esc(item.row.id||'')}"><span class="severity-line ${esc(item.severity)}"></span><div><div class="list-title">${esc(item.row.activity_name||'Untitled')}</div><div class="list-meta">${esc(item.type.replace('-',' '))} · ${esc(item.detail)}</div></div><span class="badge ${esc(item.severity)}">${esc(item.severity)}</span></div>`).join('') : emptyState(EMPTY_ICONS.checkCircle, 'No planning issues detected', 'Nothing needs review right now.');
    document.getElementById('readiness-summary').innerHTML = `<div class="metric-line"><span>Fully complete</span><strong>${fmtNum(rows.length-quality.incomplete)}</strong></div><div class="progress"><span style="width:${quality.completenessRate}%"></span></div><div class="metric-line"><span>Missing pack/campaign</span><strong>${fmtNum(quality.missingPackIds)}</strong></div><div class="metric-line"><span>Invalid date range</span><strong>${fmtNum(quality.invalidDateRanges)}</strong></div><div class="metric-line"><span>Persisted records</span><strong>${fmtNum(rows.length)}</strong></div>`;
    document.getElementById('upcoming-list').innerHTML = upcoming.length ? upcoming.slice(0,12).map(row=>`<div class="list-row" data-open-id="${esc(row.id||'')}"><span class="severity-line medium"></span><div><div class="list-title">${esc(row.activity_name||'Untitled')}</div><div class="list-meta">${fmtDate(row.start_date)} · ${esc(row.channel||'No channel')} · ${esc(row.lead_team||row.lead||'Unassigned')}</div></div><span class="badge ${row.source_type==='external'?'info':'neutral'}">${esc(row.source_type||'')}</span></div>`).join('') : emptyState(EMPTY_ICONS.calendar, 'No activities in the next 30 days', 'Check back later or widen the planning horizon.');
    document.getElementById('channel-load').innerHTML = barList(countBy(rows,'channel'));
  }

  function futureRows(weeks) {
    const now = new Date(); const end = new Date(now); end.setDate(end.getDate()+weeks*7);
    return state.rows.filter(row=>{const s=A.parseDate(row.start_date),e=A.parseDate(row.end_date)||s;return s&&e>=now&&s<=end;}).sort((a,b)=>A.parseDate(a.start_date)-A.parseDate(b.start_date));
  }

  function renderBoard() {
    const rows = futureRows(state.horizonWeeks);
    const lead=A.leadTimeStats(rows,7);
    const coverage=A.weeklyCoverage(rows,state.horizonWeeks,new Date());
    const peak=coverage.reduce((best,w)=>w.count>(best?best.count:-1)?w:best,null);
    document.getElementById('planning-kpis').innerHTML=[kpi('In horizon',rows.length,`Next ${state.horizonWeeks} weeks`,'highlight'),kpi('Short notice',lead.shortNotice,`${lead.shortNoticeRate}% of valid`,'warning'),kpi('Median lead',lead.median===null?'—':`${lead.median}d`,`${lead.excluded} excluded`,''),kpi('Peak week',peak?peak.count:0,peak?fmtDate(peak.from):'—','')].join('');
    const weeks=coverage;
    let html=`<div class="timeline"><div class="timeline-grid" style="grid-template-columns:190px repeat(${weeks.length},minmax(58px,1fr))"><div class="timeline-head">Activity</div>${weeks.map(w=>`<div class="timeline-head">${fmtDate(w.from).replace(/\s\d{4}$/,'')}</div>`).join('')}`;
    rows.slice(0,45).forEach(row=>{
      const start=A.parseDate(row.start_date),end=A.parseDate(row.end_date)||start;
      html+=`<div class="timeline-label" data-open-id="${esc(row.id||'')}" title="${esc(row.activity_name||'')}">${esc(row.activity_name||'Untitled')}</div>`;
      weeks.forEach(w=>{const overlaps=start&&start<w.to&&end>=w.from;html+=`<div class="timeline-cell">${overlaps?`<span class="timeline-dot ${row.source_type==='external'?'external':''}" title="${esc(row.channel||'')}"></span>`:''}</div>`;});
    });
    html+='</div></div>';
    document.getElementById('planning-board').innerHTML=rows.length?html:emptyState(EMPTY_ICONS.calendar, 'No upcoming activities in this horizon', 'Extend the horizon or adjust filters to see more.');
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
    document.getElementById('conflict-kpis').innerHTML=[kpi('Matching pairs',items.length,'Current filters','highlight'),kpi('Critical',conflicts.filter(i=>i.severity==='critical').length,'Requires review','danger'),kpi('Other conflicts',conflicts.filter(i=>i.severity!=='critical').length,'Potential competition','warning'),kpi('Orchestration',orchestration.length,'Same-pack coordination','')].join('');
    document.getElementById('conflict-list').innerHTML=items.length?items.slice(0,60).map(item=>`<div class="conflict-row"><div class="conflict-top"><div><span class="badge ${esc(item.severity)}">${esc(item.severity)}</span> <span class="badge ${item.kind==='orchestration'?'info':'neutral'}">${esc(item.kind)}</span></div><span class="list-meta">${item.gapDays} day gap · ${esc(item.left.channel||'')}</span></div><div class="conflict-pair"><div class="conflict-item" data-open-id="${esc(item.left.id||'')}"><strong>${esc(item.left.activity_name||'Untitled')}</strong><br>${esc(campaignLabel(item.left)||'No campaign')}</div><div class="conflict-vs">VS</div><div class="conflict-item" data-open-id="${esc(item.right.id||'')}"><strong>${esc(item.right.activity_name||'Untitled')}</strong><br>${esc(campaignLabel(item.right)||'No campaign')}</div></div></div>`).join(''):emptyState(EMPTY_ICONS.checkCircle, 'No matching conflicts', 'Try widening the proximity window or clearing filters.');
  }

  function renderCapacity() {
    const future=futureRows(26),weekly=A.weeklyCoverage(future,12,new Date()),max=Math.max(...weekly.map(w=>w.count),1);
    document.getElementById('weekly-load').innerHTML=`<div class="bar-list">${weekly.map(w=>`<div class="bar-row"><div class="bar-label">${fmtDate(w.from).replace(/\s\d{4}$/,'')}</div><div class="bar-track"><div class="bar-fill" style="width:${w.count/max*100}%"></div></div><div class="bar-value">${w.count}</div></div>`).join('')}</div>`;
    const horizons=[4,8,12,26].map(weeks=>({weeks,count:futureRows(weeks).length}));
    document.getElementById('forward-coverage').innerHTML=horizons.map(item=>`<div class="metric-line"><span>${item.weeks===26?'6 months':item.weeks+' weeks'}</span><strong>${fmtNum(item.count)} activities</strong></div><div class="progress"><span style="width:${future.length?item.count/future.length*100:0}%"></span></div>`).join('');
    const ownershipRows=future.map(row=>Object.assign({},row,{lead_team:row.lead_team||row.lead||'Unassigned'}));
    document.getElementById('coverage-dimensions').innerHTML=`<div class="grid two"><div><h3>Lead teams</h3>${barList(countBy(ownershipRows,'lead_team'))}</div><div><h3>Strategic objectives</h3>${barList(countBy(future,'strategic_objectives'),true)}</div></div>`;
  }

  function populateActivityFilters() {
    const fill=(id,values,label)=>{const el=document.getElementById(id),current=el.value;el.innerHTML=`<option value="">All ${label}</option>`+values.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');el.value=current;};
    fill('activity-channel',countBy(state.rows,'channel').map(x=>x[0]),'channels');
    fill('activity-priority',countBy(state.rows,'priority').map(x=>x[0]),'priorities');
  }

  function applyActivityFilters() {
    const q=document.getElementById('activity-search').value.toLowerCase(),source=document.getElementById('activity-source').value,channel=document.getElementById('activity-channel').value,priority=document.getElementById('activity-priority').value,readiness=document.getElementById('activity-readiness').value;
    const rows=state.rows.filter(row=>{
      const complete=A.planningCompleteness(row).score===100;
      return (!q||Object.values(row).some(value=>String(value||'').toLowerCase().includes(q)))&&(!source||row.source_type===source)&&(!channel||split(row.channel).includes(channel))&&(!priority||split(row.priority).includes(priority))&&(!readiness||(readiness==='complete'&&complete)||(readiness==='incomplete'&&!complete));
    }).sort((a,b)=>(A.parseDate(b.start_date)||0)-(A.parseDate(a.start_date)||0));
    state.filteredRows=rows;
    document.getElementById('activity-result-count').textContent=`${fmtNum(rows.length)} of ${fmtNum(state.rows.length)}`;
    document.getElementById('activity-table-body').innerHTML=rows.map(row=>{const ready=A.planningCompleteness(row);return `<tr data-open-id="${esc(row.id||'')}"><td title="${esc(row.activity_name||'')}">${esc(row.activity_name||'Untitled')}</td><td>${esc(row.tracking_id||'—')}</td><td>${esc(row.channel||'—')}</td><td>${fmtDate(row.start_date)}</td><td>${esc(row.priority||'—')}</td><td>${esc(row.lead_team||row.lead||'—')}</td><td>${esc(campaignLabel(row)||'—')}</td><td><span class="badge ${ready.score===100?'success':'warning'}">${ready.score}%</span></td></tr>`;}).join('')||`<tr><td colspan="8">${emptyState(EMPTY_ICONS.search, 'No activities match the filters', 'Clear filters or adjust your search to see more results.')}</td></tr>`;
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
    document.getElementById('health-kpis').innerHTML=[kpi('Complete',`${quality.completenessRate}%`,`${complete} of ${rows.length}`,'success'),kpi('Short notice',`${lead.shortNoticeRate}%`,`Threshold <7 days`,'warning'),kpi('Median lead',lead.median===null?'—':`${lead.median}d`,`P25 ${lead.p25??'—'} · P75 ${lead.p75??'—'}`,''),kpi('Excluded',lead.excluded,'Missing or negative lead time','')].join('');
    const max=Math.max(lead.p75||0,lead.median||0,lead.p25||0,1),xOf=v=>v/max*90+5;
    const markers=[['P25',lead.p25],['Median',lead.median],['P75',lead.p75]].filter(([,v])=>v!==null&&v!==undefined).map(([label,value])=>({label,value,x:xOf(value)}));
    const pointsHtml=clusterLeadMarkers(markers).map(cluster=>{
      const dots=cluster.map(m=>`<span class="distribution-point" style="left:${m.x}%"></span>`).join('');
      const center=cluster.reduce((sum,m)=>sum+m.x,0)/cluster.length;
      const sameValue=cluster.every(m=>m.value===cluster[0].value);
      const text=sameValue?`${cluster.map(m=>m.label).join(' · ')} ${cluster[0].value}d`:cluster.map(m=>`${m.label} ${m.value}d`).join(' · ');
      return `${dots}<span class="distribution-label" style="left:${center}%">${text}</span>`;
    }).join('');
    document.getElementById('lead-distribution').innerHTML=`<div class="distribution"><div class="distribution-range" style="left:${(lead.p25||0)/max*90+5}%;width:${((lead.p75||0)-(lead.p25||0))/max*90}%"></div>${pointsHtml}</div>`;
    const fields=new Map();rows.forEach(row=>A.planningCompleteness(row).missing.forEach(field=>fields.set(field,(fields.get(field)||0)+1)));
    document.getElementById('missing-fields').innerHTML=barList(Array.from(fields.entries()).sort((a,b)=>b[1]-a[1]),true);
    const teamRows=new Map();rows.forEach(row=>{const key=row.lead_team||row.lead||'Unassigned';if(!teamRows.has(key))teamRows.set(key,[]);teamRows.get(key).push(row);});
    document.getElementById('team-health').innerHTML=`<table><thead><tr><th>Team</th><th class="num">Activities</th><th class="num">Complete</th><th class="num">Short notice</th><th class="num">Median lead</th></tr></thead><tbody>${Array.from(teamRows.entries()).map(([team,items])=>{const q=A.dataQuality(items),l=A.leadTimeStats(items,7);return `<tr><td>${esc(team)}</td><td class="num">${items.length}</td><td class="num">${q.completenessRate}%</td><td class="num">${l.shortNoticeRate}%</td><td class="num">${l.median===null?'—':l.median+'d'}</td></tr>`;}).join('')}</tbody></table>`;
  }

  function renderStrategic() {
    const rows=state.rows,aligned=rows.filter(r=>nonempty(r.strategic_objectives)),objectives=countBy(rows,'strategic_objectives'),divisions=countBy(rows,'business_division'),unaligned=rows.filter(r=>!nonempty(r.strategic_objectives));
    document.getElementById('strategic-kpis').innerHTML=[kpi('Aligned',`${rows.length?Math.round(aligned.length/rows.length*100):0}%`,`${aligned.length} activities`,'success'),kpi('Unaligned',unaligned.length,'No objective','danger'),kpi('Objectives',objectives.length,'Unique values',''),kpi('Divisions',divisions.length,'Represented','')].join('');
    document.getElementById('objective-coverage').innerHTML=barList(objectives);
    document.getElementById('division-coverage').innerHTML=barList(divisions,true);
    document.getElementById('unaligned-list').innerHTML=unaligned.length?unaligned.slice(0,30).map(row=>`<div class="list-row" data-open-id="${esc(row.id||'')}"><span class="severity-line high"></span><div><div class="list-title">${esc(row.activity_name||'Untitled')}</div><div class="list-meta">${fmtDate(row.start_date)} · ${esc(row.lead_team||row.lead||'Unassigned')}</div></div><span class="badge warning">Unaligned</span></div>`).join(''):emptyState(EMPTY_ICONS.checkCircle, 'All activities have a strategic objective', 'Nothing left to align.');
  }

  function renderCampaignQuality() {
    const cards=A.campaignScorecards(state.rows),multi=cards.filter(c=>c.channels>1),single=cards.filter(c=>c.channels===1),avg=cards.length?Math.round(cards.reduce((s,c)=>s+c.activities,0)/cards.length*10)/10:0;
    document.getElementById('campaign-kpis').innerHTML=[kpi('Packs / campaigns',cards.length,'Identified planning units','highlight'),kpi('Multi-channel',multi.length,`${cards.length?Math.round(multi.length/cards.length*100):0}% of units`,'success'),kpi('Single-channel',single.length,'Review orchestration','warning'),kpi('Avg activities',avg,'Per planning unit','')].join('');
    document.getElementById('campaign-scorecard').innerHTML=cards.length?`<table><thead><tr><th>Campaign / pack</th><th class="num">Activities</th><th class="num">Channels</th><th>Channel mix</th><th class="num">Objectives</th><th class="num">Audiences</th><th>Activity window</th><th class="num">Gap</th></tr></thead><tbody>${cards.slice(0,50).map(card=>`<tr><td>${esc(card.campaign)}</td><td class="num">${card.activities}</td><td class="num"><span class="badge ${card.channels>1?'success':'warning'}">${card.channels}</span></td><td title="${esc(card.channelNames.join(', '))}">${esc(card.channelNames.join(', ')||'—')}</td><td class="num">${card.objectives}</td><td class="num">${card.audiences}</td><td>${fmtDate(card.firstDate)} – ${fmtDate(card.lastDate)}</td><td class="num">${card.channelGapDays===null?'—':card.channelGapDays+'d'}</td></tr>`).join('')}</tbody></table>`:emptyState(EMPTY_ICONS.layers, 'No campaign or pack identifiers available', 'Add a campaign, pack ID, or tracking pack to group activities.');
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
      lines.push(`<div class="notice" style="border-left-color:var(--warning);background:var(--warning-tint)"><strong>${fmtNum(sync.conflicts)} source conflicts overrode local edits (source wins).</strong></div>`);
    }
    return lines.join('');
  }

  function renderDataQuality() {
    const q=A.dataQuality(state.rows),generated=state.meta&&(state.meta.generated_at_iso||state.meta.generated_at)||'Unknown';
    document.getElementById('quality-kpis').innerHTML=[kpi('Complete records',`${q.completenessRate}%`,`${q.incomplete} incomplete`,'highlight'),kpi('Duplicate IDs',q.duplicateTrackingIds,'Unique duplicated identifiers',q.duplicateTrackingIds?'danger':'success'),kpi('Missing IDs',q.missingTrackingIds,'Cannot safely edit',q.missingTrackingIds?'danger':'success'),kpi('Invalid dates',q.invalidDateRanges,'End before start',q.invalidDateRanges?'danger':'success')].join('');
    document.getElementById('quality-diagnostics').innerHTML=[['Missing campaign / pack',q.missingPackIds],['Incomplete planning records',q.incomplete],['Duplicate tracking IDs',q.duplicateTrackingIds],['Missing tracking IDs',q.missingTrackingIds],['Invalid date ranges',q.invalidDateRanges]].map(([label,value])=>`<div class="metric-line"><span>${esc(label)}</span><strong>${fmtNum(value)}</strong></div>`).join('');
    document.getElementById('reconciliation').innerHTML=`<div class="metric-line"><span>API refresh</span><strong>${esc(String(generated))}</strong></div><div class="metric-line"><span>${esc(backendLabel())} rows</span><strong>${fmtNum(state.snapshotRows.length)}</strong></div><div class="metric-line"><span>Write adapter</span><strong>${esc(backendLabel())} REST API</strong></div>${syncRunSummaryHtml()}<div class="notice"><strong>Versioned writes:</strong> stale updates are rejected with HTTP 409 and must be reviewed against the current database record.</div>`;
  }

  function updateActivitiesCount() {
    document.getElementById('activities-count').textContent = fmtNum(state.rows.length);
  }

  function renderAll() {
    refreshRows(); renderOverview(); renderBoard(); renderCalendar(); renderConflicts(); renderCapacity(); populateActivityFilters(); applyActivityFilters(); renderPlanningHealth(); renderStrategic(); renderCampaignQuality(); renderDataQuality(); updateActivitiesCount(); bindOpenRows();
  }

  function bindOpenRows() {
    document.querySelectorAll('[data-open-id]').forEach(el=>{
      el.setAttribute('tabindex','0');
      el.setAttribute('role','button');
      const activate=()=>{const key=String(el.dataset.openId);const row=state.rows.find(item=>String(item.id)===key);if(row)openDrawer(row,el);};
      el.onclick=activate;
      el.onkeydown=event=>{if(event.key==='Enter'||event.key===' '||event.key==='Spacebar'){event.preventDefault();activate();}};
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
    fillDatalist('dl-communication_pack_cpid',distinctValues('communication_pack_cpid'));
    fillDatalist('dl-business_area',distinctValues('business_area'));
    fillDatalist('dl-lead_team',distinctValues('lead_team'));
    fillDatalist('dl-partner_team',distinctValues('partner_team'));
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

  function openDrawer(row, opener) {
    state.selected=row;state.editing=false;state.creating=false;state.drawerOpener=opener||document.activeElement;
    const sourceType=row.source_type||'internal';
    document.getElementById('drawer-title').textContent=row.activity_name||'Untitled activity';
    document.getElementById('drawer-tracking').textContent=row.tracking_id||'No tracking ID';
    document.getElementById('form-variant').hidden=true;
    applyVariant(sourceType);
    populateSelectOptions(sourceType);
    populateDrawerForm(row);
    renderMultiselectOptions();
    setDrawerEditing(false);
    document.getElementById('activity-drawer').classList.add('open');
    document.getElementById('activity-drawer').setAttribute('aria-hidden','false');
    document.getElementById('drawer-close').focus();
  }

  function openCreateDrawer(opener) {
    state.selected=null;state.creating=true;state.editing=true;state.dirty=false;state.drawerOpener=opener||document.activeElement;
    document.getElementById('drawer-title').textContent='New activity';
    document.getElementById('drawer-tracking').textContent='Tracking ID is generated on save';
    document.getElementById('drawer-mode-label').textContent='New record';
    document.getElementById('drawer-mode-label').className='badge info';
    document.getElementById('drawer-edit').style.display='none';
    document.querySelector('.drawer-actions').style.display='flex';
    document.getElementById('drawer-save').textContent='Create activity';
    document.getElementById('form-validation').textContent='';
    document.getElementById('form-variant').hidden=false;
    setSourceToggle('internal');
    resetCreateForm();
    applyVariant('internal');
    populateSelectOptions('internal');
    renderMultiselectOptions();
    setFormEnabled(true);
    document.getElementById('activity-drawer').classList.add('open');
    document.getElementById('activity-drawer').setAttribute('aria-hidden','false');
    form().elements.activity_name.focus();
  }

  function closeDrawer() {
    multiselectContainers().forEach(closeMsPopover);
    document.getElementById('activity-drawer').classList.remove('open');document.getElementById('activity-drawer').setAttribute('aria-hidden','true');state.selected=null;state.editing=false;state.creating=false;state.dirty=false;
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

  async function confirmDiscardIfDirty() {
    if (!(state.editing && state.dirty)) return true;
    return openDiscardModal();
  }

  function setFormEnabled(enabled) {
    Array.from(form().elements).forEach(el=>{if(el.name)el.disabled=!enabled;});
    multiselectContainers().forEach(container=>setMultiselectEnabled(container,enabled));
  }

  function setDrawerEditing(editing) {
    state.editing=editing;state.creating=false;state.dirty=false;
    setFormEnabled(editing);
    document.getElementById('drawer-mode-label').textContent=editing?`${backendLabel()} edit mode`:'Read only';
    document.getElementById('drawer-mode-label').className=`badge ${editing?'info':'neutral'}`;
    document.getElementById('drawer-edit').style.display=editing?'none':'block';
    document.querySelector('.drawer-actions').style.display=editing?'flex':'none';
    document.getElementById('drawer-save').textContent='Save activity';
    document.getElementById('form-validation').textContent='';
  }

  async function saveDraft(event) {
    event.preventDefault();if(!state.selected||!state.selected.id||!state.selected.version)return;
    const data=new FormData(event.currentTarget),patch={};
    data.forEach((value,key)=>{if(key==='news_digest')return;let normalized=String(value);if((key==='start_date'||key==='end_date')&&normalized)normalized=new Date(normalized).toISOString();if(A.fieldValueChanged(key,state.selected[key],normalized))patch[key]=normalized===''?null:normalized;});
    if(state.selected.source_type==='internal'){const checked=form().elements.news_digest.checked;if(Boolean(state.selected.news_digest)!==checked)patch.news_digest=checked;}
    if(!patch.activity_name&&data.get('activity_name').trim()===''){document.getElementById('form-validation').textContent='Activity name is required.';return;}
    const start=A.parseDate(patch.start_date||state.selected.start_date),end=A.parseDate(patch.end_date||state.selected.end_date);if(start&&end&&end<start){document.getElementById('form-validation').textContent='End date cannot be before start date.';return;}
    if(!Object.keys(patch).length){toast('No changes to save');setDrawerEditing(false);return;}
    const validation=document.getElementById('form-validation');
    try {
      const updated=await repository.updateActivity(state.selected.id,state.selected.version,patch);
      state.snapshotRows=state.snapshotRows.map(row=>row.id===updated.id?updated:row);
      toast(`Activity saved to ${backendLabel()}`);closeDrawer();renderAll();
    } catch(error) {
      if(error.status===409){
        const loaded=await loadData();
        state.snapshotRows=loaded.rows;state.meta=loaded.meta;refreshRows();
        const fresh=state.rows.find(row=>String(row.id)===String(state.selected.id));
        if(fresh)state.selected=fresh;
        validation.textContent='This activity changed in the database since you opened it. Your entries are kept — review them, then save again to apply, or cancel to discard.';
      } else {
        validation.textContent=error.message;
      }
    }
  }

  async function submitCreate(event) {
    event.preventDefault();
    const sourceType=currentSourceType(),validation=document.getElementById('form-validation');
    const value=name=>{const el=form().elements[name];return el?String(el.value||'').trim():'';};
    const required=sourceType==='internal'?REQUIRED_INTERNAL:REQUIRED_EXTERNAL;
    const missing=required.filter(name=>!value(name));
    if(missing.length){
      validation.textContent=`Complete the required fields: ${missing.map(name=>FIELD_LABELS[name]||name).join(', ')}.`;
      focusField(missing[0]);
      return;
    }
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
    download(`CPLAN_V6_activities_${new Date().toISOString().slice(0,10)}.csv`,[columns.join(','),...state.filteredRows.map(row=>columns.map(c=>cell(row[c])).join(','))].join('\n'),'text/csv');
  }

  function wireEvents() {
    document.querySelectorAll('.nav-item').forEach(btn=>btn.onclick=()=>{document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.page').forEach(x=>x.classList.remove('active'));btn.classList.add('active');document.getElementById(`page-${btn.dataset.page}`).classList.add('active');});
    document.querySelectorAll('[data-subnav]').forEach(nav=>nav.querySelectorAll('.subnav-item').forEach(btn=>btn.onclick=()=>{nav.querySelectorAll('.subnav-item').forEach(x=>x.classList.remove('active'));const page=nav.parentElement;page.querySelectorAll(':scope > .subpage').forEach(x=>x.classList.remove('active'));btn.classList.add('active');document.getElementById(`sub-${btn.dataset.sub}`).classList.add('active');}));
    document.getElementById('horizon-toggle').onclick=event=>{const btn=event.target.closest('button');if(!btn)return;document.querySelectorAll('#horizon-toggle button').forEach(x=>x.classList.remove('active'));btn.classList.add('active');state.horizonWeeks=Number(btn.dataset.weeks);renderBoard();bindOpenRows();};
    ['conflict-proximity','conflict-type','conflict-severity'].forEach(id=>document.getElementById(id).onchange=()=>{renderConflicts();bindOpenRows();});
    document.getElementById('cal-prev').onclick=()=>{state.calendarDate=new Date(state.calendarDate.getFullYear(),state.calendarDate.getMonth()-1,1);renderCalendar();bindOpenRows();};
    document.getElementById('cal-next').onclick=()=>{state.calendarDate=new Date(state.calendarDate.getFullYear(),state.calendarDate.getMonth()+1,1);renderCalendar();bindOpenRows();};
    document.getElementById('cal-today').onclick=()=>{state.calendarDate=new Date();renderCalendar();bindOpenRows();};
    const runActivityFilters=()=>{applyActivityFilters();bindOpenRows();};
    const debouncedActivityFilters=debounce(runActivityFilters,200);
    document.getElementById('activity-search').addEventListener('input',debouncedActivityFilters);
    ['activity-source','activity-channel','activity-priority','activity-readiness'].forEach(id=>document.getElementById(id).addEventListener('change',runActivityFilters));
    document.getElementById('activity-clear').onclick=()=>{['activity-search','activity-source','activity-channel','activity-priority','activity-readiness'].forEach(id=>document.getElementById(id).value='');runActivityFilters();};
    document.getElementById('activity-export').onclick=exportFilteredCsv;
    document.getElementById('activity-new').onclick=event=>openCreateDrawer(event.currentTarget);
    wireMultiselects();
    document.getElementById('source-toggle').onclick=event=>{
      const btn=event.target.closest('button');if(!btn)return;
      const source=btn.dataset.source;if(source===currentSourceType())return;
      setSourceToggle(source);applyVariant(source);populateSelectOptions(source);renderMultiselectOptions();
      if(state.editing)state.dirty=true;
    };
    document.querySelectorAll('[data-close-drawer]').forEach(el=>el.onclick=async()=>{if(await confirmDiscardIfDirty())closeDrawer();});
    document.getElementById('drawer-edit').onclick=()=>{if(!state.selected||!state.selected.id){toast('Database ID required for safe editing');return;}setDrawerEditing(true);};
    document.getElementById('drawer-cancel').onclick=async()=>{
      if(!await confirmDiscardIfDirty())return;
      if(state.creating){closeDrawer();return;}
      if(state.selected){const sourceType=state.selected.source_type||'internal';applyVariant(sourceType);populateSelectOptions(sourceType);populateDrawerForm(state.selected);renderMultiselectOptions();}
      setDrawerEditing(false);
    };
    const activityForm=document.getElementById('activity-form');
    activityForm.onsubmit=event=>state.creating?submitCreate(event):saveDraft(event);
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
  }

  async function init() {
    wireEvents();
    try {
      const [loaded,syncRun]=await Promise.all([loadData(),loadSyncRun()]);
      state.snapshotRows=loaded.rows;state.meta=loaded.meta;state.syncRun=syncRun;refreshRows();
      const generated=loaded.meta&&(loaded.meta.generated_at_iso||loaded.meta.generated_at);
      document.getElementById('status-dot').className='status-dot ready';document.getElementById('status-label').textContent=`${fmtNum(loaded.rows.length)} activities loaded`;document.getElementById('snapshot-time').textContent=`${backendLabel()} API: ${generated||'unknown'}`;
      renderAll();
    } catch(error) {
      console.error('CPLAN V6 initialization failed',error);
      document.getElementById('status-dot').className='status-dot error';document.getElementById('status-label').textContent='Data load failed';document.getElementById('snapshot-time').textContent=error.message;
      document.querySelector('.content').innerHTML=`<div class="card">${emptyState(EMPTY_ICONS.alertTriangle, 'CPLAN V6 could not initialize', `${error.message} Start the configured local database API and reload this page.`)}</div>`;
    }
  }

  init();
})();
