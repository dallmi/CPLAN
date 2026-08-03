const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const snapshot = require('../pipeline/studio/snapshot.js');

const APP_JS = fs.readFileSync(path.join(__dirname, '..', 'pipeline', 'studio', 'app.js'), 'utf8');

/**
 * Method names declared on a class in app.js, read from the source.
 *
 * app.js is a browser IIFE that calls init() on load and touches document, so it
 * cannot be require()d here. Reading the class body is the honest alternative:
 * it costs a regex, and it fails loudly if the class is renamed or restructured
 * rather than quietly asserting nothing.
 */
function methodsOf(className) {
  const start = APP_JS.indexOf(`class ${className} {`);
  assert.notEqual(start, -1, `class ${className} not found in app.js`);
  let depth = 0;
  let end = start;
  for (let i = APP_JS.indexOf('{', start); i < APP_JS.length; i++) {
    if (APP_JS[i] === '{') depth++;
    else if (APP_JS[i] === '}') { depth--; if (depth === 0) { end = i; break; } }
  }
  assert.ok(end > start, `could not find the end of class ${className}`);
  const body = APP_JS.slice(start, end);
  return new Set(Array.from(body.matchAll(/^\s{4}(\w+)\s*\(/gm), match => match[1]));
}

function withPayload(payload, fn) {
  const previous = global.window;
  global.window = { __CPLAN_SNAPSHOT__: payload };
  try { return fn(); } finally { global.window = previous; }
}

// --- the contract test ------------------------------------------------------

test('the snapshot repository implements every method the database one has', () => {
  // Without this, the standalone build breaks silently the first time the studio
  // grows an endpoint: the new call simply throws "not a function" inside a
  // catch somewhere, and the page renders with a piece quietly missing.
  const expected = methodsOf('DatabasePlanningRepository');
  expected.delete('request'); // the HTTP plumbing itself; there is nothing to mirror
  assert.ok(expected.size >= 7, `expected a real method surface, got ${[...expected]}`);

  const actual = new snapshot.SnapshotPlanningRepository();
  for (const name of expected) {
    assert.equal(typeof actual[name], 'function', `SnapshotPlanningRepository is missing ${name}()`);
  }
});

// --- reads ------------------------------------------------------------------

test('listActivities answers from the embedded payload', async () => {
  const items = [{ id: 'a', activity_name: 'Launch email' }];
  const result = await withPayload({ items }, () => new snapshot.SnapshotPlanningRepository().listActivities());
  assert.deepEqual(result, { items, total: 1 });
});

test('an empty or absent payload reads as zero activities, not as a crash', async () => {
  const repo = new snapshot.SnapshotPlanningRepository();
  assert.deepEqual(await repo.listActivities(), { items: [], total: 0 });
  assert.deepEqual(await withPayload({}, () => repo.listActivities()), { items: [], total: 0 });
});

test('health reports the snapshot backend, which drives the "Snapshot" label', async () => {
  const health = await new snapshot.SnapshotPlanningRepository().health();
  assert.equal(health.database, 'snapshot');
});

test('a missing sync run is a status, not an error', async () => {
  const run = await new snapshot.SnapshotPlanningRepository().latestSyncRun();
  assert.deepEqual(run, { status: 'never_synced' });
});

test('an embedded sync run is passed through unchanged', async () => {
  const sync_run = { ran_at: '2026-08-03T06:00:00Z', created: 3, updated: 2, conflicts: 0, local_only: 1 };
  const run = await withPayload({ sync_run }, () => new snapshot.SnapshotPlanningRepository().latestSyncRun());
  assert.deepEqual(run, sync_run);
});

// --- writes -----------------------------------------------------------------

test('every write rejects with a message that explains the mode', async () => {
  const repo = new snapshot.SnapshotPlanningRepository();
  for (const call of [
    () => repo.createActivity({}),
    () => repo.createActivitiesBatch([]),
    () => repo.updateActivity('id', 1, {})
  ]) {
    await assert.rejects(call, /read-only snapshot/i);
  }
});

test('history rejects separately, naming where the history actually lives', async () => {
  // Deliberately not embedded: it names who changed what, and this file is made
  // to be forwarded. loadHistory() renders the message as an empty state.
  await assert.rejects(() => new snapshot.SnapshotPlanningRepository().getActivityChanges('id'), /planning studio/i);
});

// --- session ----------------------------------------------------------------

test('the snapshot session is a viewer, which is what makes the UI read-only', () => {
  // Every hidden create button and every absent edit affordance follows from
  // this one value, through role gating the studio already had.
  assert.deepEqual(snapshot.session(), { username: 'snapshot', role: 'viewer', auth: false });
});

test('isActive and exportedAt describe the payload, and tolerate its absence', () => {
  assert.equal(snapshot.isActive(), false);
  assert.equal(snapshot.exportedAt(), null);
  withPayload({ exported_at: '2026-08-03T12:00:00Z' }, () => {
    assert.equal(snapshot.isActive(), true);
    assert.equal(snapshot.exportedAt(), '2026-08-03T12:00:00Z');
  });
});
