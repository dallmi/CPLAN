(() => {
  'use strict';

  const A = window.CplanAnalytics;
  const COLORS = {grey:'#404040', bronze:'#B98E2C'};
  const state = {snapshotRows:[], rows:[], meta:null, horizonWeeks:8, calendarDate:new Date(), selected:null, editing:false, dirty:false, filteredRows:[]};

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

  const apiErrorMessage = (detail, status) => {
    if (Array.isArray(detail)) {
      return detail.map(item => {
        const loc = Array.isArray(item.loc) ? (item.loc[0] === 'body' ? item.loc.slice(1) : item.loc).join('.') : '';
        return loc ? `${loc}: ${item.msg}` : (item.msg || 'Invalid value');
      }).join('; ');
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

  function refreshRows() {
    state.rows = state.snapshotRows.slice();
    updateDraftCount();
  }

  function updateDraftCount() {
    document.getElementById('overview-as-of').textContent = `Operational view: ${backendLabel()} live data`;
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
    if (!entries.length) return '<div class="empty">No data available</div>';
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
    const collisions = A.detectCollisions(rows,{proximityDays:1}).filter(item=>item.kind==='conflict');
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
    document.getElementById('attention-list').innerHTML = attention.length ? attention.slice(0,18).map(item=>`<div class="list-row" data-open-id="${esc(item.row.id||'')}"><span class="severity-line ${esc(item.severity)}"></span><div><div class="list-title">${esc(item.row.activity_name||'Untitled')}</div><div class="list-meta">${esc(item.type.replace('-',' '))} · ${esc(item.detail)}</div></div><span class="badge ${esc(item.severity)}">${esc(item.severity)}</span></div>`).join('') : '<div class="empty">No planning issues detected</div>';
    document.getElementById('readiness-summary').innerHTML = `<div class="metric-line"><span>Fully complete</span><strong>${fmtNum(rows.length-quality.incomplete)}</strong></div><div class="progress"><span style="width:${quality.completenessRate}%"></span></div><div class="metric-line"><span>Missing pack/campaign</span><strong>${fmtNum(quality.missingPackIds)}</strong></div><div class="metric-line"><span>Invalid date range</span><strong>${fmtNum(quality.invalidDateRanges)}</strong></div><div class="metric-line"><span>Persisted records</span><strong>${fmtNum(rows.length)}</strong></div>`;
    document.getElementById('upcoming-list').innerHTML = upcoming.length ? upcoming.slice(0,12).map(row=>`<div class="list-row" data-open-id="${esc(row.id||'')}"><span class="severity-line medium"></span><div><div class="list-title">${esc(row.activity_name||'Untitled')}</div><div class="list-meta">${fmtDate(row.start_date)} · ${esc(row.channel||'No channel')} · ${esc(row.lead_team||row.lead||'Unassigned')}</div></div><span class="badge ${row.source_type==='external'?'info':'neutral'}">${esc(row.source_type||'')}</span></div>`).join('') : '<div class="empty">No activities starting in the next 30 days</div>';
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
    document.getElementById('planning-board').innerHTML=rows.length?html:'<div class="empty">No upcoming activities in this horizon</div>';
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
    return A.detectCollisions(state.rows,{proximityDays:proximity}).filter(item=>(!type||item.kind===type)&&(!severity||item.severity===severity));
  }

  function renderConflicts() {
    const all=A.detectCollisions(state.rows,{proximityDays:Number(document.getElementById('conflict-proximity').value)}),items=filteredConflicts();
    const conflicts=all.filter(i=>i.kind==='conflict'),orchestration=all.filter(i=>i.kind==='orchestration');
    document.getElementById('conflict-kpis').innerHTML=[kpi('Matching pairs',items.length,'Current filters','highlight'),kpi('Critical',conflicts.filter(i=>i.severity==='critical').length,'Requires review','danger'),kpi('Other conflicts',conflicts.filter(i=>i.severity!=='critical').length,'Potential competition','warning'),kpi('Orchestration',orchestration.length,'Same-pack coordination','')].join('');
    document.getElementById('conflict-list').innerHTML=items.length?items.slice(0,60).map(item=>`<div class="conflict-row"><div class="conflict-top"><div><span class="badge ${esc(item.severity)}">${esc(item.severity)}</span> <span class="badge ${item.kind==='orchestration'?'info':'neutral'}">${esc(item.kind)}</span></div><span class="list-meta">${item.gapDays} day gap · ${esc(item.left.channel||'')}</span></div><div class="conflict-pair"><div class="conflict-item" data-open-id="${esc(item.left.id||'')}"><strong>${esc(item.left.activity_name||'Untitled')}</strong><br>${esc(item.left.campaign||item.left.tracking_pack_id||'No campaign')}</div><div class="conflict-vs">VS</div><div class="conflict-item" data-open-id="${esc(item.right.id||'')}"><strong>${esc(item.right.activity_name||'Untitled')}</strong><br>${esc(item.right.campaign||item.right.tracking_pack_id||'No campaign')}</div></div></div>`).join(''):'<div class="empty">No matching conflicts</div>';
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
    document.getElementById('activity-table-body').innerHTML=rows.map(row=>{const ready=A.planningCompleteness(row);return `<tr data-open-id="${esc(row.id||'')}"><td title="${esc(row.activity_name||'')}">${esc(row.activity_name||'Untitled')}</td><td>${esc(row.tracking_id||'—')}</td><td>${esc(row.channel||'—')}</td><td>${fmtDate(row.start_date)}</td><td>${esc(row.priority||'—')}</td><td>${esc(row.lead_team||row.lead||'—')}</td><td>${esc(row.campaign||row.tracking_pack_id||'—')}</td><td><span class="badge ${ready.score===100?'success':'warning'}">${ready.score}%</span></td></tr>`;}).join('')||'<tr><td colspan="8" class="empty">No activities match the filters</td></tr>';
  }

  function renderPlanningHealth() {
    const rows=state.rows,quality=A.dataQuality(rows),lead=A.leadTimeStats(rows,7),complete=rows.length-quality.incomplete;
    document.getElementById('health-kpis').innerHTML=[kpi('Complete',`${quality.completenessRate}%`,`${complete} of ${rows.length}`,'success'),kpi('Short notice',`${lead.shortNoticeRate}%`,`Threshold <7 days`,'warning'),kpi('Median lead',lead.median===null?'—':`${lead.median}d`,`P25 ${lead.p25??'—'} · P75 ${lead.p75??'—'}`,''),kpi('Excluded',lead.excluded,'Missing or negative lead time','')].join('');
    const max=Math.max(lead.p75||0,lead.median||0,lead.p25||0,1),point=(v,label)=>v===null?'':`<span class="distribution-point" style="left:${v/max*90+5}%"></span><span class="distribution-label" style="left:${v/max*90+5}%">${label} ${v}d</span>`;
    document.getElementById('lead-distribution').innerHTML=`<div class="distribution"><div class="distribution-range" style="left:${(lead.p25||0)/max*90+5}%;width:${((lead.p75||0)-(lead.p25||0))/max*90}%"></div>${point(lead.p25,'P25')}${point(lead.median,'Median')}${point(lead.p75,'P75')}</div>`;
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
    document.getElementById('unaligned-list').innerHTML=unaligned.length?unaligned.slice(0,30).map(row=>`<div class="list-row" data-open-id="${esc(row.id||'')}"><span class="severity-line high"></span><div><div class="list-title">${esc(row.activity_name||'Untitled')}</div><div class="list-meta">${fmtDate(row.start_date)} · ${esc(row.lead_team||row.lead||'Unassigned')}</div></div><span class="badge warning">Unaligned</span></div>`).join(''):'<div class="empty">All activities have a strategic objective</div>';
  }

  function renderCampaignQuality() {
    const cards=A.campaignScorecards(state.rows),multi=cards.filter(c=>c.channels>1),single=cards.filter(c=>c.channels===1),avg=cards.length?Math.round(cards.reduce((s,c)=>s+c.activities,0)/cards.length*10)/10:0;
    document.getElementById('campaign-kpis').innerHTML=[kpi('Packs / campaigns',cards.length,'Identified planning units','highlight'),kpi('Multi-channel',multi.length,`${cards.length?Math.round(multi.length/cards.length*100):0}% of units`,'success'),kpi('Single-channel',single.length,'Review orchestration','warning'),kpi('Avg activities',avg,'Per planning unit','')].join('');
    document.getElementById('campaign-scorecard').innerHTML=cards.length?`<table><thead><tr><th>Campaign / pack</th><th class="num">Activities</th><th class="num">Channels</th><th>Channel mix</th><th class="num">Objectives</th><th class="num">Audiences</th><th>Activity window</th><th class="num">Gap</th></tr></thead><tbody>${cards.slice(0,50).map(card=>`<tr><td>${esc(card.campaign)}</td><td class="num">${card.activities}</td><td class="num"><span class="badge ${card.channels>1?'success':'warning'}">${card.channels}</span></td><td title="${esc(card.channelNames.join(', '))}">${esc(card.channelNames.join(', ')||'—')}</td><td class="num">${card.objectives}</td><td class="num">${card.audiences}</td><td>${fmtDate(card.firstDate)} – ${fmtDate(card.lastDate)}</td><td class="num">${card.channelGapDays===null?'—':card.channelGapDays+'d'}</td></tr>`).join('')}</tbody></table>`:'<div class="empty">No campaign or pack identifiers available</div>';
  }

  function renderDataQuality() {
    const q=A.dataQuality(state.rows),generated=state.meta&&(state.meta.generated_at_iso||state.meta.generated_at)||'Unknown';
    document.getElementById('quality-kpis').innerHTML=[kpi('Complete records',`${q.completenessRate}%`,`${q.incomplete} incomplete`,'highlight'),kpi('Duplicate IDs',q.duplicateTrackingIds,'Unique duplicated identifiers',q.duplicateTrackingIds?'danger':'success'),kpi('Missing IDs',q.missingTrackingIds,'Cannot safely edit',q.missingTrackingIds?'danger':'success'),kpi('Invalid dates',q.invalidDateRanges,'End before start',q.invalidDateRanges?'danger':'success')].join('');
    document.getElementById('quality-diagnostics').innerHTML=[['Missing campaign / pack',q.missingPackIds],['Incomplete planning records',q.incomplete],['Duplicate tracking IDs',q.duplicateTrackingIds],['Missing tracking IDs',q.missingTrackingIds],['Invalid date ranges',q.invalidDateRanges]].map(([label,value])=>`<div class="metric-line"><span>${esc(label)}</span><strong>${fmtNum(value)}</strong></div>`).join('');
    document.getElementById('reconciliation').innerHTML=`<div class="metric-line"><span>API refresh</span><strong>${esc(String(generated))}</strong></div><div class="metric-line"><span>${esc(backendLabel())} rows</span><strong>${fmtNum(state.snapshotRows.length)}</strong></div><div class="metric-line"><span>Write adapter</span><strong>${esc(backendLabel())} REST API</strong></div><div class="notice"><strong>Versioned writes:</strong> stale updates are rejected with HTTP 409 and must be reviewed against the current database record.</div>`;
  }

  function renderAll() {
    refreshRows(); renderOverview(); renderBoard(); renderCalendar(); renderConflicts(); renderCapacity(); populateActivityFilters(); applyActivityFilters(); renderPlanningHealth(); renderStrategic(); renderCampaignQuality(); renderDataQuality(); bindOpenRows();
  }

  function bindOpenRows() {
    document.querySelectorAll('[data-open-id]').forEach(el=>{el.onclick=()=>{const key=String(el.dataset.openId);const row=state.rows.find(item=>String(item.id)===key);if(row)openDrawer(row);};});
  }

  function populateDrawerForm(row) {
    const form=document.getElementById('activity-form');
    Array.from(form.elements).forEach(el=>{if(!el.name)return;el.value=(el.type==='datetime-local'?isoLocal(row[el.name]):row[el.name])||'';});
  }

  function openDrawer(row) {
    state.selected=row;state.editing=false;
    document.getElementById('drawer-title').textContent=row.activity_name||'Untitled activity';
    document.getElementById('drawer-tracking').textContent=row.tracking_id||'No tracking ID';
    populateDrawerForm(row);
    setDrawerEditing(false);
    document.getElementById('activity-drawer').classList.add('open');
    document.getElementById('activity-drawer').setAttribute('aria-hidden','false');
  }

  function closeDrawer() {
    document.getElementById('activity-drawer').classList.remove('open');document.getElementById('activity-drawer').setAttribute('aria-hidden','true');state.selected=null;state.editing=false;state.dirty=false;
  }

  function confirmDiscardIfDirty() {
    return !(state.editing && state.dirty) || window.confirm('Discard unsaved changes?');
  }

  function setDrawerEditing(editing) {
    state.editing=editing;state.dirty=false;const form=document.getElementById('activity-form');
    Array.from(form.elements).forEach(el=>{if(el.name)el.disabled=!editing;});
    document.getElementById('drawer-mode-label').textContent=editing?`${backendLabel()} edit mode`:'Read only';
    document.getElementById('drawer-mode-label').className=`badge ${editing?'info':'neutral'}`;
    document.getElementById('drawer-edit').style.display=editing?'none':'block';
    document.querySelector('.drawer-actions').style.display=editing?'flex':'none';
    document.getElementById('form-validation').textContent='';
  }

  async function saveDraft(event) {
    event.preventDefault();if(!state.selected||!state.selected.id||!state.selected.version)return;
    const data=new FormData(event.currentTarget),patch={};
    data.forEach((value,key)=>{let normalized=String(value);if((key==='start_date'||key==='end_date')&&normalized)normalized=new Date(normalized).toISOString();if(A.fieldValueChanged(key,state.selected[key],normalized))patch[key]=normalized===''?null:normalized;});
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
    ['activity-search','activity-source','activity-channel','activity-priority','activity-readiness'].forEach(id=>{const el=document.getElementById(id);el.addEventListener(id==='activity-search'?'input':'change',()=>{applyActivityFilters();bindOpenRows();});});
    document.getElementById('activity-clear').onclick=()=>{['activity-search','activity-source','activity-channel','activity-priority','activity-readiness'].forEach(id=>document.getElementById(id).value='');applyActivityFilters();bindOpenRows();};
    document.getElementById('activity-export').onclick=exportFilteredCsv;
    document.querySelectorAll('[data-close-drawer]').forEach(el=>el.onclick=()=>{if(confirmDiscardIfDirty())closeDrawer();});
    document.getElementById('drawer-edit').onclick=()=>{if(!state.selected||!state.selected.id){toast('Database ID required for safe editing');return;}setDrawerEditing(true);};
    document.getElementById('drawer-cancel').onclick=()=>{if(!confirmDiscardIfDirty())return;if(state.selected)populateDrawerForm(state.selected);setDrawerEditing(false);};
    const activityForm=document.getElementById('activity-form');
    activityForm.onsubmit=saveDraft;
    activityForm.addEventListener('input',()=>{if(state.editing)state.dirty=true;});
    activityForm.addEventListener('change',()=>{if(state.editing)state.dirty=true;});
    document.addEventListener('keydown',event=>{if(event.key==='Escape'&&confirmDiscardIfDirty())closeDrawer();});
  }

  async function init() {
    wireEvents();
    try {
      const loaded=await loadData();state.snapshotRows=loaded.rows;state.meta=loaded.meta;refreshRows();
      const generated=loaded.meta&&(loaded.meta.generated_at_iso||loaded.meta.generated_at);
      document.getElementById('status-dot').className='status-dot ready';document.getElementById('status-label').textContent=`${fmtNum(loaded.rows.length)} activities loaded`;document.getElementById('snapshot-time').textContent=`${backendLabel()} API: ${generated||'unknown'}`;
      renderAll();
    } catch(error) {
      console.error('CPLAN V6 initialization failed',error);
      document.getElementById('status-dot').className='status-dot error';document.getElementById('status-label').textContent='Data load failed';document.getElementById('snapshot-time').textContent=error.message;
      document.querySelector('.content').innerHTML=`<div class="card"><div class="empty"><strong>CPLAN V6 could not initialize.</strong><br>${esc(error.message)}<br><br>Start the configured local database API and reload this page.</div></div>`;
    }
  }

  init();
})();
