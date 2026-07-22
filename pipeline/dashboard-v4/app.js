(() => {
  'use strict';

  const A = window.CplanAnalytics;
  const COLORS = {grey:'#404040', bronze:'#B98E2C'};
  const state = {snapshotRows:[], rows:[], meta:null, horizonWeeks:8, calendarDate:new Date(), selected:null, editing:false, filteredRows:[]};

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

  class PlanningRepository {
    listChanges() { throw new Error('listChanges must be implemented'); }
    saveChange() { throw new Error('saveChange must be implemented'); }
    removeChange() { throw new Error('removeChange must be implemented'); }
  }

  class LocalDraftRepository extends PlanningRepository {
    constructor(storage, key) { super(); this.storage = storage; this.key = key; }
    listChanges() {
      try { return JSON.parse(this.storage.getItem(this.key) || '[]'); }
      catch (_) { return []; }
    }
    persist(changes) { this.storage.setItem(this.key, JSON.stringify(changes)); }
    saveChange(change) {
      const changes = this.listChanges();
      const index = changes.findIndex(item => item.tracking_id === change.tracking_id);
      const record = Object.assign({}, change, {updated_at:new Date().toISOString(), adapter:'local-draft'});
      if (index >= 0) changes[index] = Object.assign({}, changes[index], record, {patch:Object.assign({}, changes[index].patch, record.patch)});
      else changes.push(record);
      this.persist(changes);
      return record;
    }
    removeChange(trackingId) { this.persist(this.listChanges().filter(item => item.tracking_id !== trackingId)); }
    clear() { this.persist([]); }
  }

  window.CplanRepositories = {PlanningRepository, LocalDraftRepository};
  const drafts = new LocalDraftRepository(window.localStorage, 'cplan-v4-local-drafts-v1');

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

  function exportDrafts() {
    const payload = {
      schema_version:'cplan-local-change-set/v1',
      generated_at:new Date().toISOString(),
      source_snapshot:state.meta && (state.meta.generated_at_iso || state.meta.generated_at),
      target_adapter:'sharepoint-planning-repository',
      changes:drafts.listChanges()
    };
    download(`CPLAN_V4_changes_${new Date().toISOString().slice(0,10)}.json`, JSON.stringify(payload,null,2), 'application/json');
  }

  async function waitForDuckDB() {
    if (window.duckdb) return;
    await Promise.race([
      new Promise(resolve => window.addEventListener('duckdb-ready', resolve, {once:true})),
      new Promise((_,reject) => window.setTimeout(() => reject(new Error('DuckDB-WASM did not load')),30000))
    ]);
  }

  async function fetchFirst(paths, kind) {
    let lastError;
    for (const path of paths) {
      try {
        const response = await fetch(path, {cache:'no-store'});
        if (!response.ok) continue;
        return kind === 'json' ? response.json() : new Uint8Array(await response.arrayBuffer());
      } catch (error) { lastError = error; }
    }
    throw lastError || new Error(`Unable to load ${paths[0]}`);
  }

  async function loadData() {
    await waitForDuckDB();
    const base = window.location.pathname.replace(/\/[^/]*$/,'');
    const parquetPaths = ['../output/communications.parquet','pipeline/output/communications.parquet',`${base}/../output/communications.parquet`];
    const metaPaths = ['../output/meta.json','pipeline/output/meta.json',`${base}/../output/meta.json`];
    let meta = null;
    try { meta = await fetchFirst(metaPaths, 'json'); } catch (_) { meta = {generated_at:'Unknown'}; }
    const bytes = await fetchFirst(parquetPaths, 'bytes');
    const m = window.duckdb;
    const bundle = await m.selectBundle(m.getJsDelivrBundles());
    const workerUrl = URL.createObjectURL(new Blob([`importScripts("${bundle.mainWorker}");`],{type:'text/javascript'}));
    const worker = new Worker(workerUrl);
    const db = new m.AsyncDuckDB(new m.ConsoleLogger(), worker);
    await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
    URL.revokeObjectURL(workerUrl);
    await db.registerFileBuffer('communications.parquet', bytes);
    const conn = await db.connect();
    const result = await conn.query("SELECT * FROM read_parquet('communications.parquet')");
    const rows = result.toArray().map(record => {
      const row = {};
      Object.keys(record).forEach(key => {
        const value = record[key];
        row[key] = typeof value === 'bigint' ? Number(value) : value;
      });
      return row;
    });
    await conn.close();
    return {rows,meta};
  }

  function refreshRows() {
    state.rows = A.applyChanges(state.snapshotRows, drafts.listChanges());
    updateDraftCount();
  }

  function updateDraftCount() {
    const count = drafts.listChanges().length;
    document.getElementById('draft-count').textContent = count;
    document.getElementById('overview-as-of').textContent = count ? `Operational view: ${count} local draft${count===1?'':'s'} over analytics snapshot` : 'Operational view: analytics snapshot';
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
    document.getElementById('attention-list').innerHTML = attention.length ? attention.slice(0,18).map(item=>`<div class="list-row" data-open-id="${esc(item.row.tracking_id||'')}"><span class="severity-line ${esc(item.severity)}"></span><div><div class="list-title">${esc(item.row.activity_name||'Untitled')}</div><div class="list-meta">${esc(item.type.replace('-',' '))} · ${esc(item.detail)}</div></div><span class="badge ${esc(item.severity)}">${esc(item.severity)}</span></div>`).join('') : '<div class="empty">No planning issues detected</div>';
    document.getElementById('readiness-summary').innerHTML = `<div class="metric-line"><span>Fully complete</span><strong>${fmtNum(rows.length-quality.incomplete)}</strong></div><div class="progress"><span style="width:${quality.completenessRate}%"></span></div><div class="metric-line"><span>Missing pack/campaign</span><strong>${fmtNum(quality.missingPackIds)}</strong></div><div class="metric-line"><span>Invalid date range</span><strong>${fmtNum(quality.invalidDateRanges)}</strong></div><div class="metric-line"><span>Local draft changes</span><strong>${fmtNum(drafts.listChanges().length)}</strong></div>`;
    document.getElementById('upcoming-list').innerHTML = upcoming.length ? upcoming.slice(0,12).map(row=>`<div class="list-row" data-open-id="${esc(row.tracking_id||'')}"><span class="severity-line medium"></span><div><div class="list-title">${esc(row.activity_name||'Untitled')}</div><div class="list-meta">${fmtDate(row.start_date)} · ${esc(row.channel||'No channel')} · ${esc(row.lead_team||row.lead||'Unassigned')}</div></div><span class="badge ${row.source_type==='external'?'info':'neutral'}">${esc(row.source_type||'')}</span></div>`).join('') : '<div class="empty">No activities starting in the next 30 days</div>';
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
      html+=`<div class="timeline-label" data-open-id="${esc(row.tracking_id||'')}" title="${esc(row.activity_name||'')}">${esc(row.activity_name||'Untitled')}</div>`;
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
    for(let i=0;i<total;i+=1){const d=new Date(year,month,i-offset+1),other=d.getMonth()!==month,isToday=d.toDateString()===today.toDateString();const events=state.rows.filter(row=>{const rd=A.parseDate(row.start_date);return rd&&rd.toDateString()===d.toDateString();});html+=`<div class="calendar-day ${other?'other':''} ${isToday?'today':''}"><div class="cal-number">${d.getDate()}</div>${events.slice(0,4).map(row=>`<div class="cal-event ${row.source_type==='external'?'external':''}" data-open-id="${esc(row.tracking_id||'')}" title="${esc(row.activity_name||'')}">${esc(row.activity_name||'Untitled')}</div>`).join('')}${events.length>4?`<div class="cal-event">+${events.length-4} more</div>`:''}</div>`;}
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
    document.getElementById('conflict-list').innerHTML=items.length?items.slice(0,60).map(item=>`<div class="conflict-row"><div class="conflict-top"><div><span class="badge ${esc(item.severity)}">${esc(item.severity)}</span> <span class="badge ${item.kind==='orchestration'?'info':'neutral'}">${esc(item.kind)}</span></div><span class="list-meta">${item.gapDays} day gap · ${esc(item.left.channel||'')}</span></div><div class="conflict-pair"><div class="conflict-item" data-open-id="${esc(item.left.tracking_id||'')}"><strong>${esc(item.left.activity_name||'Untitled')}</strong><br>${esc(item.left.campaign||item.left.tracking_pack_id||'No campaign')}</div><div class="conflict-vs">VS</div><div class="conflict-item" data-open-id="${esc(item.right.tracking_id||'')}"><strong>${esc(item.right.activity_name||'Untitled')}</strong><br>${esc(item.right.campaign||item.right.tracking_pack_id||'No campaign')}</div></div></div>`).join(''):'<div class="empty">No matching conflicts</div>';
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
      return (!q||Object.values(row).some(value=>String(value||'').toLowerCase().includes(q)))&&(!source||row.source_type===source)&&(!channel||split(row.channel).includes(channel))&&(!priority||split(row.priority).includes(priority))&&(!readiness||(readiness==='complete'&&complete)||(readiness==='incomplete'&&!complete)||(readiness==='draft'&&(row._localDraft||row._draftConflict)));
    }).sort((a,b)=>(A.parseDate(b.start_date)||0)-(A.parseDate(a.start_date)||0));
    state.filteredRows=rows;
    document.getElementById('activity-result-count').textContent=`${fmtNum(rows.length)} of ${fmtNum(state.rows.length)}`;
    document.getElementById('activity-table-body').innerHTML=rows.map(row=>{const ready=A.planningCompleteness(row),status=row._draftConflict?'<span class="badge danger">Draft conflict</span> ':row._localDraft?'<span class="badge info">Draft</span> ':'';return `<tr data-open-id="${esc(row.tracking_id||'')}"><td title="${esc(row.activity_name||'')}">${status}${esc(row.activity_name||'Untitled')}</td><td>${esc(row.tracking_id||'—')}</td><td>${esc(row.channel||'—')}</td><td>${fmtDate(row.start_date)}</td><td>${esc(row.priority||'—')}</td><td>${esc(row.lead_team||row.lead||'—')}</td><td>${esc(row.campaign||row.tracking_pack_id||'—')}</td><td><span class="badge ${ready.score===100?'success':ready.score<63?'danger':'warning'}">${ready.score}%</span></td></tr>`;}).join('') || '<tr><td colspan="8" class="empty">No matching activities</td></tr>';
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
    document.getElementById('unaligned-list').innerHTML=unaligned.length?unaligned.slice(0,30).map(row=>`<div class="list-row" data-open-id="${esc(row.tracking_id||'')}"><span class="severity-line high"></span><div><div class="list-title">${esc(row.activity_name||'Untitled')}</div><div class="list-meta">${fmtDate(row.start_date)} · ${esc(row.lead_team||row.lead||'Unassigned')}</div></div><span class="badge warning">Unaligned</span></div>`).join(''):'<div class="empty">All activities have a strategic objective</div>';
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
    document.getElementById('reconciliation').innerHTML=`<div class="metric-line"><span>Analytics snapshot</span><strong>${esc(String(generated))}</strong></div><div class="metric-line"><span>Snapshot rows</span><strong>${fmtNum(state.snapshotRows.length)}</strong></div><div class="metric-line"><span>Local changes applied</span><strong>${fmtNum(drafts.listChanges().length)}</strong></div><div class="metric-line"><span>Write adapter</span><strong>Local draft</strong></div><div class="notice"><strong>SharePoint-ready boundary:</strong> replace the repository adapter; analytics remain snapshot-based until refresh and reconciliation complete.</div>`;
  }

  function renderAll() {
    refreshRows(); renderOverview(); renderBoard(); renderCalendar(); renderConflicts(); renderCapacity(); populateActivityFilters(); applyActivityFilters(); renderPlanningHealth(); renderStrategic(); renderCampaignQuality(); renderDataQuality(); renderChangeQueue(); bindOpenRows();
  }

  function bindOpenRows() {
    document.querySelectorAll('[data-open-id]').forEach(el=>{el.onclick=()=>{const row=state.rows.find(item=>String(item.tracking_id||'')===String(el.dataset.openId));if(row)openDrawer(row);};});
  }

  function trackingIdCount(trackingId) {
    return state.snapshotRows.filter(row=>String(row.tracking_id||'')===String(trackingId||'')).length;
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
    document.getElementById('activity-drawer').classList.remove('open');document.getElementById('activity-drawer').setAttribute('aria-hidden','true');state.selected=null;state.editing=false;
  }

  function setDrawerEditing(editing) {
    state.editing=editing;const form=document.getElementById('activity-form');
    Array.from(form.elements).forEach(el=>{if(el.name)el.disabled=!editing;});
    document.getElementById('drawer-mode-label').textContent=editing?'Local edit mode':'Read only';
    document.getElementById('drawer-mode-label').className=`badge ${editing?'info':'neutral'}`;
    document.getElementById('drawer-edit').style.display=editing?'none':'block';
    document.querySelector('.drawer-actions').style.display=editing?'flex':'none';
    document.getElementById('form-validation').textContent='';
  }

  function saveDraft(event) {
    event.preventDefault();if(!state.selected||!state.selected.tracking_id)return;
    if(trackingIdCount(state.selected.tracking_id)!==1){document.getElementById('form-validation').textContent='Editing is blocked because this tracking ID is not unique.';return;}
    const data=new FormData(event.currentTarget),patch={};
    data.forEach((value,key)=>{let normalized=String(value);if((key==='start_date'||key==='end_date')&&normalized)normalized=new Date(normalized).toISOString();if(A.fieldValueChanged(key,state.selected[key],normalized))patch[key]=normalized;});
    if(!patch.activity_name&&data.get('activity_name').trim()===''){document.getElementById('form-validation').textContent='Activity name is required.';return;}
    const start=A.parseDate(patch.start_date||state.selected.start_date),end=A.parseDate(patch.end_date||state.selected.end_date);if(start&&end&&end<start){document.getElementById('form-validation').textContent='End date cannot be before start date.';return;}
    if(!Object.keys(patch).length){toast('No changes to save');setDrawerEditing(false);return;}
    drafts.saveChange({tracking_id:state.selected.tracking_id,base_modified:state.selected.modified||null,patch});
    toast('Local draft saved');closeDrawer();renderAll();
  }

  function renderChangeQueue() {
    const changes=drafts.listChanges();document.getElementById('change-list').innerHTML=changes.length?changes.map(change=>{const row=state.rows.find(r=>r.tracking_id===change.tracking_id),conflict=row&&row._draftConflict;return `<div class="queue-item"><strong>${esc(row&&row.activity_name||change.tracking_id)}</strong> ${conflict?`<span class="badge danger">${esc(conflict.replace(/-/g,' '))}</span>`:''}<div class="list-meta">${esc(change.tracking_id)} · ${fmtDate(change.updated_at)}</div>${conflict?'<div class="notice">This draft was not applied. Discard it or open the current record and save a reviewed replacement.</div>':''}<pre>${esc(JSON.stringify(change.patch,null,2))}</pre><button class="btn secondary" data-remove-change="${esc(change.tracking_id)}">Discard</button></div>`;}).join(''):'<div class="empty">No local draft changes</div>';
    document.querySelectorAll('[data-remove-change]').forEach(btn=>btn.onclick=()=>{drafts.removeChange(btn.dataset.removeChange);renderAll();toast('Draft discarded');});
  }

  function exportFilteredCsv() {
    const columns=['tracking_id','activity_name','channel','start_date','end_date','priority','lead','lead_team','target_audience','business_division','region','campaign','strategic_objectives','source_type'];
    const cell=value=>`"${A.safeCsvValue(value).replace(/"/g,'""')}"`;
    download(`CPLAN_V4_activities_${new Date().toISOString().slice(0,10)}.csv`,[columns.join(','),...state.filteredRows.map(row=>columns.map(c=>cell(row[c])).join(','))].join('\n'),'text/csv');
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
    document.querySelectorAll('[data-close-drawer]').forEach(el=>el.onclick=closeDrawer);
    document.getElementById('drawer-edit').onclick=()=>{if(!state.selected.tracking_id){toast('Tracking ID required for safe editing');return;}if(trackingIdCount(state.selected.tracking_id)!==1){toast('Editing blocked: duplicate tracking ID');return;}setDrawerEditing(true);};
    document.getElementById('drawer-cancel').onclick=()=>{if(state.selected)populateDrawerForm(state.selected);setDrawerEditing(false);};
    document.getElementById('activity-form').onsubmit=saveDraft;
    const queue=document.getElementById('change-queue'),closeQueue=()=>{queue.classList.remove('open');queue.setAttribute('aria-hidden','true');};document.getElementById('open-change-queue').onclick=()=>{renderChangeQueue();queue.classList.add('open');queue.setAttribute('aria-hidden','false');};document.querySelectorAll('[data-close-queue]').forEach(el=>el.onclick=closeQueue);
    document.getElementById('export-changes').onclick=exportDrafts;document.getElementById('queue-export').onclick=exportDrafts;
    document.getElementById('discard-all-changes').onclick=()=>{if(window.confirm('Discard all local draft changes?')){drafts.clear();closeQueue();renderAll();toast('All drafts discarded');}};
    document.addEventListener('keydown',event=>{if(event.key==='Escape'){closeDrawer();closeQueue();}});
  }

  async function init() {
    wireEvents();
    try {
      const loaded=await loadData();state.snapshotRows=loaded.rows;state.meta=loaded.meta;refreshRows();
      const generated=loaded.meta&&(loaded.meta.generated_at_iso||loaded.meta.generated_at);
      document.getElementById('status-dot').className='status-dot ready';document.getElementById('status-label').textContent=`${fmtNum(loaded.rows.length)} activities loaded`;document.getElementById('snapshot-time').textContent=`Analytics snapshot: ${generated||'unknown'}`;
      renderAll();
    } catch(error) {
      console.error('CPLAN V4 initialization failed',error);
      document.getElementById('status-dot').className='status-dot error';document.getElementById('status-label').textContent='Data load failed';document.getElementById('snapshot-time').textContent=error.message;
      document.querySelector('.content').innerHTML=`<div class="card"><div class="empty"><strong>CPLAN V4 could not initialize.</strong><br>${esc(error.message)}<br><br>Serve the project root with a local web server or use the generated V4 standalone file.</div></div>`;
    }
  }

  init();
})();
