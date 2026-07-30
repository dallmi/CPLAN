const test = require('node:test');
const assert = require('node:assert/strict');
const analytics = require('../pipeline/studio/analytics.js');

const base = {
  tracking_id: 'AAA-0000001-260801-0000001-EMI',
  tracking_pack_id: 'AAA-0000001',
  activity_name: 'Launch email',
  activity_description: 'Announce the summer launch to employees.',
  start_date: '2026-08-01T09:00:00+02:00',
  end_date: '2026-08-01T17:00:00+02:00',
  created: '2026-07-10T09:00:00+02:00',
  planning_lead_days: 22,
  channel: 'Email',
  lead_team: 'Campaigns',
  lead: 'Planner',
  target_audience: 'Employees',
  priority: 'High',
  strategic_objectives: 'Trust',
  campaign: 'Summer launch',
  source_type: 'internal'
};

// --- Brute-force collision reference (kept independent from analytics.js's optimized implementation) ---

function refEmpty(value) {
  return value === null || value === undefined || String(value).trim() === '' || value === 'None' || value === 'null';
}

function refNormalizeMulti(value) {
  if (refEmpty(value)) return [];
  if (Array.isArray(value)) return value.map(String).map(v => v.trim()).filter(Boolean);
  return String(value).split(/[;,]/).map(v => v.trim()).filter(Boolean);
}

function refSharesDimension(a, b, field) {
  const right = new Set(refNormalizeMulti(b[field]).map(v => v.toLowerCase()));
  return refNormalizeMulti(a[field]).some(v => right.has(v.toLowerCase()));
}

function refPriorityRank(value) {
  const ranks = {critical: 4, high: 3, medium: 2, normal: 1, low: 0};
  return ranks[String(value || '').toLowerCase()] ?? 1;
}

function refDayGap(a, b) {
  const leftDay = Date.UTC(a.getFullYear(), a.getMonth(), a.getDate());
  const rightDay = Date.UTC(b.getFullYear(), b.getMonth(), b.getDate());
  return Math.abs(leftDay - rightDay) / 86400000;
}

// Deliberately O(n^2) — mirrors the pre-optimization detectCollisions semantics exactly,
// so it can serve as an oracle for the sort + sliding-window rewrite.
function bruteForceCollisions(rows, proximityDays) {
  const collisions = [];
  for (let i = 0; i < rows.length; i += 1) {
    for (let j = i + 1; j < rows.length; j += 1) {
      const left = rows[i];
      const right = rows[j];
      const leftStart = analytics.parseDate(left.start_date);
      const rightStart = analytics.parseDate(right.start_date);
      if (!leftStart || !rightStart || refDayGap(leftStart, rightStart) > proximityDays) continue;
      if (!refSharesDimension(left, right, 'channel') || !refSharesDimension(left, right, 'target_audience')) continue;
      const samePack = !refEmpty(left.tracking_pack_id) && left.tracking_pack_id === right.tracking_pack_id;
      const rank = Math.max(refPriorityRank(left.priority), refPriorityRank(right.priority));
      const severity = samePack ? 'info' : rank >= 4 ? 'critical' : rank >= 3 ? 'high' : 'medium';
      collisions.push({
        id: `${left.tracking_id || i}::${right.tracking_id || j}`,
        kind: samePack ? 'orchestration' : 'conflict',
        severity,
        gapDays: refDayGap(leftStart, rightStart)
      });
    }
  }
  return collisions;
}

// Deterministic LCG so the generated dataset is reproducible across runs/machines.
function makeLcg(seed) {
  let state = seed >>> 0;
  return function next() {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

function buildRandomRows(count, seed) {
  const rand = makeLcg(seed);
  const channels = ['Email', 'Intranet article (News)', 'Event', 'Social post', 'Video'];
  const audiences = ['Employees', 'Managers', 'Customers', 'Partners'];
  const packs = ['AAA-0000001', 'BBB-0000002', 'CCC-0000003', '', ''];
  const priorities = ['Critical', 'High', 'Medium', 'Normal', 'Low'];
  const baseMs = Date.UTC(2026, 6, 1);
  const rows = [];
  for (let i = 0; i < count; i += 1) {
    const hasDate = rand() > 0.08;
    const dayOffset = Math.floor(rand() * 120);
    rows.push({
      tracking_id: `SEED-${i}`,
      tracking_pack_id: packs[Math.floor(rand() * packs.length)],
      channel: channels[Math.floor(rand() * channels.length)],
      target_audience: audiences[Math.floor(rand() * audiences.length)],
      priority: priorities[Math.floor(rand() * priorities.length)],
      start_date: hasDate ? new Date(baseMs + dayOffset * 86400000).toISOString() : null
    });
  }
  return rows;
}

test('optimized collision detector matches the brute-force reference across proximities', () => {
  const rows = buildRandomRows(200, 123456789);
  for (const proximityDays of [0, 1, 3, 7]) {
    const optimized = analytics.detectCollisions(rows, {proximityDays});
    const reference = bruteForceCollisions(rows, proximityDays);
    const toSet = list => new Set(list.map(c => JSON.stringify([c.id, c.kind, c.severity, c.gapDays])));
    assert.equal(optimized.length, reference.length);
    assert.deepEqual(toSet(optimized), toSet(reference));
  }
});

test('optimized collision detector output stays sorted by severity desc then gap days asc', () => {
  const rows = buildRandomRows(200, 987654321);
  const result = analytics.detectCollisions(rows, {proximityDays: 3});
  assert.ok(result.length > 0);
  const order = {critical: 4, high: 3, medium: 2, info: 1};
  for (let i = 1; i < result.length; i += 1) {
    const prevRank = order[result[i - 1].severity];
    const curRank = order[result[i].severity];
    assert.ok(
      prevRank > curRank || (prevRank === curRank && result[i - 1].gapDays <= result[i].gapDays)
    );
  }
});

test('collision left/right ordering follows original input index even when dates sort differently', () => {
  const rows = [
    {...base, tracking_id: 'idx0-later-date', start_date: '2026-08-02T09:00:00+02:00'},
    {...base, tracking_id: 'idx1-earlier-date', start_date: '2026-08-01T09:00:00+02:00'}
  ];
  const result = analytics.detectCollisions(rows, {proximityDays: 1});
  assert.equal(result.length, 1);
  assert.equal(result[0].left.tracking_id, 'idx0-later-date');
  assert.equal(result[0].right.tracking_id, 'idx1-earlier-date');
  assert.equal(result[0].id, 'idx0-later-date::idx1-earlier-date');
});

// Completeness is variant-aware and matches the create form's required lists
// (single source of truth shared with app.js). Internal needs all 14 fields,
// external the 11 common ones. `base` alone is an incomplete internal row
// (no region/time_zone/audience/business_division) -- exactly the shape a
// source sync produces -- so it must read as a draft, not "ready".
const internalComplete = {
  ...base,
  region: 'EMEA', time_zone: 'Europe/Zurich', audience: '10-50k', business_division: 'Retail'
};
const externalComplete = {...internalComplete, source_type: 'external'};

test('a synced internal row missing its planning fields is not complete', () => {
  const result = analytics.planningCompleteness(base);
  assert.equal(result.score, 71); // 10 of 14 present
  assert.deepEqual(result.missing, ['region', 'time_zone', 'audience', 'business_division']);
});

test('planning completeness scores a fully planned internal activity 100%', () => {
  const result = analytics.planningCompleteness(internalComplete);
  assert.equal(result.score, 100);
  assert.deepEqual(result.missing, []);
  // Campaign/pack membership is not a completeness field: a standalone
  // activity with no campaign or pack still scores 100 when fully planned.
  const standalone = analytics.planningCompleteness({...internalComplete, tracking_pack_id: '', communication_pack: '', campaign: ''});
  assert.equal(standalone.score, 100);
  assert.deepEqual(standalone.missing, []);
});

test('planning completeness identifies a single missing applicable field', () => {
  const result = analytics.planningCompleteness({...internalComplete, priority: ''});
  assert.equal(result.score, 93); // 13 of 14
  assert.deepEqual(result.missing, ['priority']);
});

test('planning completeness flags a missing activity description', () => {
  const result = analytics.planningCompleteness({...internalComplete, activity_description: ''});
  assert.equal(result.score, 93);
  assert.deepEqual(result.missing, ['activity_description']);
});

test('external activities do not require the internal-only fields', () => {
  const result = analytics.planningCompleteness(externalComplete);
  assert.equal(result.score, 100);
  assert.deepEqual(result.missing, []);
  // ...and the same row as internal would flag the three internal-only gaps.
  const asInternal = analytics.planningCompleteness({...externalComplete, source_type: 'internal', target_audience: '', audience: '', business_division: ''});
  assert.deepEqual(asInternal.missing, ['target_audience', 'audience', 'business_division']);
});

test('lead and lead_team are both required (no either-satisfies shortcut)', () => {
  const result = analytics.planningCompleteness({...internalComplete, lead_team: ''});
  assert.deepEqual(result.missing, ['lead_team']);
});

test('lead time stats report distribution, short notice, and exclusions', () => {
  const rows = [3, 5, 10, 20].map((v, i) => ({...base, tracking_id: String(i), planning_lead_days: v}));
  rows.push({...base, tracking_id: 'x', planning_lead_days: -2});
  rows.push({...base, tracking_id: 'y', planning_lead_days: null});
  const result = analytics.leadTimeStats(rows, 7);
  assert.equal(result.valid, 4);
  assert.equal(result.excluded, 2);
  assert.equal(result.shortNotice, 2);
  assert.equal(result.shortNoticeRate, 50);
  assert.equal(result.median, 7.5);
  assert.equal(result.p25, 4.5);
  assert.equal(result.p75, 12.5);
});

test('collision detector separates orchestration from unrelated conflicts', () => {
  const rows = [
    base,
    {...base, tracking_id: 'same-pack', activity_name: 'Launch article', channel: 'Email', start_date: '2026-08-01T12:00:00+02:00'},
    {...base, tracking_id: 'other-pack', tracking_pack_id: 'BBB-0000002', campaign: 'Other campaign', priority: 'Critical', start_date: '2026-08-01T13:00:00+02:00'}
  ];
  const result = analytics.detectCollisions(rows, {proximityDays: 0});
  assert.equal(result.length, 3);
  assert.equal(result.filter(x => x.kind === 'orchestration').length, 1);
  assert.equal(result.filter(x => x.kind === 'conflict').length, 2);
  assert.ok(result.some(x => x.severity === 'critical'));
});

test('campaign scorecard aggregates pack orchestration', () => {
  const rows = [
    base,
    {...base, tracking_id: '2', channel: 'Intranet article (News)', start_date: '2026-08-03T09:00:00+02:00'}
  ];
  const cards = analytics.campaignScorecards(rows);
  assert.equal(cards.length, 1);
  assert.equal(cards[0].activities, 2);
  assert.equal(cards[0].channels, 2);
  assert.equal(cards[0].channelGapDays, 2);
});

test('data quality reports invalid dates, missing IDs, and duplicate IDs', () => {
  const rows = [
    base,
    {...base},
    {...base, tracking_id: '', start_date: '2026-09-02', end_date: '2026-09-01'}
  ];
  const result = analytics.dataQuality(rows);
  assert.equal(result.duplicateTrackingIds, 1);
  assert.equal(result.missingTrackingIds, 1);
  assert.equal(result.invalidDateRanges, 1);
});

test('missing campaign/pack ignores the derived tracking_pack_id', () => {
  // The API derives tracking_pack_id from the first two segments of every
  // tracking_id, so it is populated for practically every activity. Counting it
  // as pack membership pinned this metric to zero regardless of the data — the
  // studio reported "Missing campaign / pack: 0" while a third of the portfolio
  // belonged to no pack at all, and readers concluded the numbers contradicted
  // each other. Membership is judged by the fields that record it.
  const unpacked = {
    ...base,
    tracking_id: 'IC-2026-0001-DI',
    tracking_pack_id: 'IC-2026',
    tracking_pack_ltid: undefined,
    campaign: '',
    communication_pack: '',
    communication_pack_cpid: ''
  };
  const packed = {...unpacked, tracking_id: 'IC-2026-0002-DI', communication_pack_cpid: 'CP-01-004'};
  const viaCampaign = {...unpacked, tracking_id: 'IC-2026-0003-DI', campaign: 'Summer launch'};

  assert.equal(analytics.dataQuality([unpacked]).missingPackIds, 1);
  assert.equal(analytics.dataQuality([packed]).missingPackIds, 0);
  assert.equal(analytics.dataQuality([viaCampaign]).missingPackIds, 0);
  assert.equal(analytics.dataQuality([unpacked, packed, viaCampaign]).missingPackIds, 1);
});

test('intake cohort selects by source_created_at and falls back to created_at', () => {
  // The window is half-open: [from, to). Two adjacent 30-day windows must not
  // both claim the same activity, or every comparison double-counts its edge.
  const at = (source, local) => ({...base, source_created_at: source, created_at: local});
  const rows = [
    at('2026-07-20T00:00:00Z', null),
    at('2026-06-20T00:00:00Z', null),
    at(null, '2026-07-22T00:00:00Z'),
    at('', ''),
    at('2026-06-30T00:00:00Z', null)
  ];
  const from = new Date('2026-06-30T00:00:00Z');
  const to = new Date('2026-07-30T00:00:00Z');
  const current = analytics.createdBetween(rows, from, to);
  assert.equal(current.length, 3);

  const prior = analytics.createdBetween(rows, new Date('2026-05-31T00:00:00Z'), from);
  assert.equal(prior.length, 1);
  assert.equal(prior[0].source_created_at, '2026-06-20T00:00:00Z');
});

test('comparison window follows the range filter and flags an unfinished period', () => {
  // Local time throughout: the range presets build their bounds with the local
  // Date constructor, so a UTC literal here would compare across zones and the
  // "ends today" case would read as reaching into the future.
  const now = new Date(2026, 6, 29, 10, 0, 0);

  // No range: falls back to the next 30 days, which necessarily reaches past
  // today and is therefore provisional.
  const open = analytics.comparisonWindow(null, null, now);
  assert.equal(open.active, false);
  assert.equal(open.spanDays, 30);
  assert.equal(open.provisional, true);
  assert.equal(open.previous.to.getTime(), open.current.from.getTime());
  assert.equal(open.current.from - open.previous.from, open.current.to - open.current.from);

  // A range ending today is complete, not provisional -- the presets end at
  // 23:59:59.999, which is in the future by the clock but holds nothing left
  // to plan.
  const past = analytics.comparisonWindow(
    new Date(2026, 5, 29, 0, 0, 0), new Date(2026, 6, 29, 23, 59, 59, 999), now
  );
  assert.equal(past.active, true);
  assert.equal(past.provisional, false);
  assert.equal(past.spanDays, 30);

  // A range running into the future is provisional.
  const ahead = analytics.comparisonWindow(
    new Date(2026, 6, 1, 0, 0, 0), new Date(2026, 8, 30, 23, 59, 59), now
  );
  assert.equal(ahead.provisional, true);
  assert.equal(ahead.previous.from.getTime(), ahead.current.from.getTime() - (ahead.current.to - ahead.current.from));
});

test('local changes overlay records without mutating the snapshot', () => {
  const rows = [base];
  const changes = [{tracking_id: base.tracking_id, patch: {priority: 'Low'}}];
  const merged = analytics.applyChanges(rows, changes);
  assert.equal(merged[0].priority, 'Low');
  assert.equal(rows[0].priority, 'High');
});

test('local changes are blocked for duplicate tracking IDs', () => {
  const duplicate = {...base, activity_name: 'Second activity'};
  const rows = [base, duplicate];
  const changes = [{tracking_id: base.tracking_id, patch: {priority: 'Low'}}];
  const merged = analytics.applyChanges(rows, changes);
  assert.deepEqual(merged.map(row => row.priority), ['High', 'High']);
  assert.deepEqual(merged.map(row => row._draftConflict), ['duplicate-tracking-id', 'duplicate-tracking-id']);
});

test('stale local change is marked as conflict and not overlaid', () => {
  const rows = [{...base, modified: '2026-08-02T10:00:00Z'}];
  const changes = [{tracking_id: base.tracking_id, base_modified: '2026-08-01T10:00:00Z', patch: {priority: 'Low'}}];
  const merged = analytics.applyChanges(rows, changes);
  assert.equal(merged[0].priority, 'High');
  assert.equal(merged[0]._draftConflict, 'stale-snapshot');
});

test('HTML escaping is safe in both text and quoted attributes', () => {
  const value = '\"><img src=x onerror=alert(1)>';
  assert.equal(
    analytics.escapeHtml(value),
    '&quot;&gt;&lt;img src=x onerror=alert(1)&gt;'
  );
});

test('date fields do not become changes solely because their representation differs', () => {
  const original = new Date('2026-07-25T00:00:00.000Z');
  assert.equal(analytics.fieldValueChanged('start_date', original, '2026-07-25T00:00:00.000Z'), false);
  assert.equal(analytics.fieldValueChanged('end_date', '2026-07-25', '2026-07-26T00:00:00.000Z'), true);
  assert.equal(analytics.fieldValueChanged('priority', 'Low', 'High'), true);
});

test('same-day collision filter uses calendar days rather than rounded hours', () => {
  const rows = [
    {...base, tracking_id: 'A', start_date: '2026-08-01T23:30:00', end_date: '2026-08-01T23:30:00'},
    {...base, tracking_id: 'B', start_date: '2026-08-02T00:30:00', end_date: '2026-08-02T00:30:00'}
  ];
  assert.equal(analytics.detectCollisions(rows, {proximityDays: 0}).length, 0);
  assert.equal(analytics.detectCollisions(rows, {proximityDays: 1})[0].gapDays, 1);
});

test('CSV values that could execute as spreadsheet formulas are neutralized', () => {
  assert.equal(analytics.safeCsvValue('=HYPERLINK("https://example.com")'), "'=HYPERLINK(\"https://example.com\")");
  assert.equal(analytics.safeCsvValue('+cmd'), "'+cmd");
  assert.equal(analytics.safeCsvValue('-1+1'), "'-1+1");
  assert.equal(analytics.safeCsvValue('@SUM(A1:A2)'), "'@SUM(A1:A2)");
  assert.equal(analytics.safeCsvValue('Normal'), 'Normal');
});

// --- Issue rule (rowIssues + the two date predicates) ---

const complete = {
  ...base,
  region: 'EMEA',
  time_zone: 'Europe/Zurich',
  audience: '1000',
  business_division: 'GWM'
};

test('a fully complete, well-dated, long-notice row has no issues', () => {
  assert.deepEqual(analytics.rowIssues(complete), []);
});

test('isShortNotice is true below seven days and false at seven and above', () => {
  assert.equal(analytics.isShortNotice({...complete, planning_lead_days: 0}), true);
  assert.equal(analytics.isShortNotice({...complete, planning_lead_days: 6}), true);
  assert.equal(analytics.isShortNotice({...complete, planning_lead_days: 7}), false);
  assert.equal(analytics.isShortNotice({...complete, planning_lead_days: 22}), false);
});

test('isShortNotice ignores absent and negative lead times', () => {
  assert.equal(analytics.isShortNotice({...complete, planning_lead_days: null}), false);
  assert.equal(analytics.isShortNotice({...complete, planning_lead_days: ''}), false);
  assert.equal(analytics.isShortNotice({...complete, planning_lead_days: -3}), false);
});

test('hasInvalidDates is true only when the end precedes the start', () => {
  assert.equal(analytics.hasInvalidDates(complete), false);
  assert.equal(analytics.hasInvalidDates({
    ...complete,
    start_date: '2026-08-01T09:00:00+02:00',
    end_date: '2026-07-31T09:00:00+02:00'
  }), true);
  assert.equal(analytics.hasInvalidDates({...complete, end_date: ''}), false);
});

test('rowIssues puts the date error first, then short notice, then missing fields', () => {
  const row = {
    ...base,
    start_date: '2026-08-01T09:00:00+02:00',
    end_date: '2026-07-31T09:00:00+02:00',
    planning_lead_days: 2
  };
  const issues = analytics.rowIssues(row);

  assert.deepEqual(issues[0], {kind: 'invalid-date', field: 'end_date'});
  assert.deepEqual(issues[1], {kind: 'short-notice', field: 'start_date', leadDays: 2});
  assert.deepEqual(issues.slice(2), [
    {kind: 'missing', field: 'region'},
    {kind: 'missing', field: 'time_zone'},
    {kind: 'missing', field: 'audience'},
    {kind: 'missing', field: 'business_division'}
  ]);
});

test('rowIssues follows the variant split for missing fields', () => {
  assert.deepEqual(analytics.rowIssues({...base, planning_lead_days: 22}), [
    {kind: 'missing', field: 'region'},
    {kind: 'missing', field: 'time_zone'},
    {kind: 'missing', field: 'audience'},
    {kind: 'missing', field: 'business_division'}
  ]);
  assert.deepEqual(analytics.rowIssues({...base, source_type: 'external', planning_lead_days: 22}), [
    {kind: 'missing', field: 'region'},
    {kind: 'missing', field: 'time_zone'}
  ]);
});

test('rowIssues reports both a date finding and completeness gaps on the same row', () => {
  const issues = analytics.rowIssues({...base, planning_lead_days: 3});
  assert.equal(issues.filter(i => i.kind === 'short-notice').length, 1);
  assert.equal(issues.filter(i => i.kind === 'missing').length, 4);
});

test('priority ranking understands the source system numbered labels', () => {
  // Reported from the real portfolio: the Overview's "Critical and high" tile
  // read 0 while activities at priority 1 and 2 sat in the list beside it. The
  // source system does not use the words the studio's own form offers -- its
  // values are numbered, lowest number most urgent, e.g.
  // "<n> - <label>", four levels, 1 most urgent. Synthetic labels below:
  // only the leading digit carries meaning, so the wording is ours.
  assert.equal(analytics.priorityRank('1 - Price-sensitive'), 4);
  assert.equal(analytics.priorityRank('2 - Board level, all staff'), 3);
  assert.equal(analytics.priorityRank('3 - Divisional / regional'), 2);
  assert.equal(analytics.priorityRank('4 - Functional and other'), 1);
  assert.equal(analytics.isHighPriority('1 - Price-sensitive'), true);
  assert.equal(analytics.isHighPriority('2 - Board level, all staff'), true);
  assert.equal(analytics.isHighPriority('3 - Divisional / regional'), false);

  // The studio's own vocabulary keeps working unchanged.
  assert.equal(analytics.priorityRank('Critical'), 4);
  assert.equal(analytics.priorityRank('High'), 3);
  assert.equal(analytics.isHighPriority('High'), true);
  assert.equal(analytics.isHighPriority('Medium'), false);

  // Neither shape: the middle rank, never silently "low".
  assert.equal(analytics.priorityRank(''), 1);
  assert.equal(analytics.priorityRank('Sonstiges'), 1);
});

test('collision severity follows the numbered priorities too', () => {
  const at = (tid, priority) => ({
    tracking_id: tid, activity_name: tid, channel: 'Email',
    target_audience: 'Managers', priority,
    start_date: '2026-09-01T09:00:00Z', end_date: '2026-09-01T17:00:00Z'
  });
  const [pair] = analytics.detectCollisions(
    [at('a', '1 - Price-sensitive'), at('b', '4 - Functional and other')], {proximityDays: 0});
  assert.equal(pair.severity, 'critical');
});

test('comingUp holds a rolling window, inclusive at both ends, sorted ascending', () => {
  const now = new Date('2026-08-01T12:00:00Z');
  const at = (id, start) => Object.assign({}, base, {id, start_date: start});
  const rows = [
    at('later', '2026-08-06T09:00:00Z'),
    at('starts-now', '2026-08-01T12:00:00Z'),
    at('past', '2026-07-31T09:00:00Z'),
    at('last-moment', '2026-08-08T12:00:00Z'),
    at('just-beyond', '2026-08-08T12:00:01Z'),
    at('unparseable', 'not a date'),
    at('missing', null)
  ];
  assert.deepEqual(
    analytics.comingUp(rows, now, 7).map(r => r.id),
    ['starts-now', 'later', 'last-moment']
  );
  // A window over nothing is an empty list, not a throw.
  assert.deepEqual(analytics.comingUp([], now, 7), []);
});

test('endingWithin finds what finishes in the window and ignores open-ended rows', () => {
  const now = new Date('2026-08-01T12:00:00Z');
  const at = (id, end) => Object.assign({}, base, {id, end_date: end});
  const rows = [
    at('ends-tomorrow', '2026-08-02T17:00:00Z'),
    at('ended-already', '2026-07-30T17:00:00Z'),
    at('ends-far-out', '2026-09-30T17:00:00Z'),
    at('open-ended', null)
  ];
  assert.deepEqual(
    analytics.endingWithin(rows, now, 7).map(r => r.id),
    ['ends-tomorrow']
  );
});

test('relativeDayLabel compares calendar days, not elapsed hours', () => {
  // Local-time constructors on purpose: the label is about the day a planner
  // sees on the wall, so the boundary that matters is local midnight.
  const now = new Date(2026, 7, 1, 12, 0, 0);            // Sat 1 Aug 2026, midday
  assert.equal(analytics.relativeDayLabel(new Date(2026, 7, 1, 23, 0, 0), now), 'Today');
  assert.equal(analytics.relativeDayLabel(new Date(2026, 7, 2, 1, 0, 0), now), 'Tomorrow');
  assert.equal(analytics.relativeDayLabel(new Date(2026, 7, 5, 9, 0, 0), now), 'Wednesday');
  // Across a month boundary it is still just a weekday — no special case.
  assert.equal(
    analytics.relativeDayLabel(new Date(2026, 8, 1, 9, 0, 0), new Date(2026, 7, 30, 12, 0, 0)),
    'Tuesday'
  );
  assert.equal(analytics.relativeDayLabel(null, now), '');
  assert.equal(analytics.relativeDayLabel('not a date', now), '');
});
