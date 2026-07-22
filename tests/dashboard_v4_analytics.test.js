const test = require('node:test');
const assert = require('node:assert/strict');
const analytics = require('../pipeline/dashboard-v4/analytics.js');

const base = {
  tracking_id: 'AAA-0000001-260801-0000001-EMI',
  tracking_pack_id: 'AAA-0000001',
  activity_name: 'Launch email',
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

test('planning completeness identifies missing applicable fields', () => {
  const result = analytics.planningCompleteness({...base, priority: ''});
  assert.equal(result.score, 88);
  assert.deepEqual(result.missing, ['priority']);
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
