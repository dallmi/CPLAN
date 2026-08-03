/**
 * Read-only snapshot repository.
 *
 * Mirrors DatabasePlanningRepository's method surface exactly, but answers from
 * window.__CPLAN_SNAPSHOT__ — the payload build_studio_standalone.py embeds —
 * instead of the REST API. Every page, filter and analytic in the studio derives
 * from the single listActivities() payload, so swapping this in at the one seam
 * is all it takes to run the whole interface from a file:// URL.
 *
 * This file is loaded in both modes and is inert in the served studio: it only
 * defines window.CplanSnapshot, and app.js only reaches for it when a snapshot
 * payload is actually present.
 *
 * The write methods exist as a safety net, not as a reachable path. The snapshot
 * session declares the `viewer` role, and the studio's existing role gating
 * removes every affordance that could call them.
 *
 * tests/snapshot.test.js pins this class's method surface to
 * DatabasePlanningRepository's. Without that test the standalone build breaks
 * silently the first time the studio grows an endpoint.
 */
(function () {
  'use strict';

  var READ_ONLY = 'This is a read-only snapshot. Open the planning studio to make changes.';
  var NO_HISTORY = 'Change history is not included in a snapshot. Open the planning studio to see it.';

  function payload() {
    return (typeof window !== 'undefined' && window.__CPLAN_SNAPSHOT__) || null;
  }

  function reject(message) {
    return Promise.reject(new Error(message));
  }

  class SnapshotPlanningRepository {
    listActivities() {
      var data = payload();
      var items = (data && data.items) || [];
      return Promise.resolve({ items: items, total: items.length });
    }
    health() {
      return Promise.resolve({ status: 'ok', database: 'snapshot' });
    }
    latestSyncRun() {
      var data = payload();
      // Same contract as the API: "no sync has ever run" is a status, not an
      // error, so the reconciliation card can distinguish it from a failure.
      return Promise.resolve((data && data.sync_run) || { status: 'never_synced' });
    }
    getActivityChanges() {
      return reject(NO_HISTORY);
    }
    createActivity() {
      return reject(READ_ONLY);
    }
    createActivitiesBatch() {
      return reject(READ_ONLY);
    }
    updateActivity() {
      return reject(READ_ONLY);
    }
  }

  var api = {
    SnapshotPlanningRepository: SnapshotPlanningRepository,
    READ_ONLY_MESSAGE: READ_ONLY,
    NO_HISTORY_MESSAGE: NO_HISTORY,

    isActive: function () {
      return Boolean(payload());
    },

    // ISO timestamp the snapshot was exported at, or null. Drives both the
    // header band and the Health page: a file handed around for weeks must say
    // how old it is before anyone reads a number off it.
    exportedAt: function () {
      var data = payload();
      return (data && data.exported_at) || null;
    },

    // The session a snapshot runs under. `viewer` is what switches off every
    // create/edit/delete affordance, through role gating the studio already
    // has; auth:false keeps the user chip hidden, as in single-user mode.
    session: function () {
      return { username: 'snapshot', role: 'viewer', auth: false };
    }
  };

  if (typeof window !== 'undefined') window.CplanSnapshot = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})();
