(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.CplanAnalytics = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // Single completeness authority, shared with the create/edit drawer
  // (app.js reads REQUIRED_INTERNAL/REQUIRED_EXTERNAL off this module). The
  // dashboard readiness badge, the "Drafts" KPI, the readiness filter and the
  // attention queue all run through planningCompleteness() below, so a row is
  // "complete" by exactly the same rule the create form enforces -- a synced
  // row still missing its planning fields therefore reads as a draft
  // everywhere, not "ready" in the table yet "draft" in the drawer.
  const REQUIRED_COMMON = ['activity_name', 'channel', 'priority', 'strategic_objectives', 'activity_description', 'region', 'start_date', 'end_date', 'time_zone', 'lead', 'lead_team'];
  const REQUIRED_INTERNAL = REQUIRED_COMMON.concat(['target_audience', 'audience', 'business_division']);
  const REQUIRED_EXTERNAL = REQUIRED_COMMON.slice();
  const requiredFor = row => (row && row.source_type === 'internal') ? REQUIRED_INTERNAL : REQUIRED_EXTERNAL;

  const empty = value => value === null || value === undefined || String(value).trim() === '' || value === 'None' || value === 'null';

  function escapeHtml(value) {
    return String(value === null || value === undefined ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function normalizeMulti(value) {
    if (empty(value)) return [];
    if (Array.isArray(value)) return value.map(String).map(v => v.trim()).filter(Boolean);
    return String(value).split(/[;,]/).map(v => v.trim()).filter(Boolean);
  }

  function hasCampaignOrPack(row) {
    // Deliberately NOT tracking_pack_id: the API derives it from the first two
    // segments of tracking_id, so every activity that has a tracking ID at all
    // produces one. Including it made the OR always true and pinned
    // "Missing campaign / pack" to zero regardless of the data — the metric
    // reported perfection while a third of the portfolio had no pack. Judge
    // membership by the fields that actually record it.
    return !empty(row.communication_pack_cpid) || !empty(row.communication_pack) || !empty(row.campaign);
  }

  function planningCompleteness(row) {
    // lead and lead_team are two distinct required fields (the create form
    // asks for both) -- no "either satisfies" shortcut, so the metric never
    // calls a row complete that the drawer would still flag.
    const required = requiredFor(row);
    const missing = required.filter(field => empty(row[field]));
    return {
      score: Math.round(((required.length - missing.length) / required.length) * 100),
      missing
    };
  }

  // A row lands in a review list for reasons that have nothing to do with
  // completeness: an end date before its start, or under a week of lead time.
  // Both predicates were inlined at three call sites in app.js; they live here
  // so the overview queue, the workbench filter and rowIssues cannot drift.
  const SHORT_NOTICE_DAYS = 7;

  function isShortNotice(row) {
    // Number(null) and Number('') both coerce to 0, which would otherwise
    // pass as "0 days notice" -- empty() catches those before the numeric
    // check so an absent value reads as unknown, not urgent.
    const value = row && row.planning_lead_days;
    if (empty(value)) return false;
    const lead = Number(value);
    return Number.isFinite(lead) && lead >= 0 && lead < SHORT_NOTICE_DAYS;
  }

  function hasInvalidDates(row) {
    const start = parseDate(row && row.start_date);
    const end = parseDate(row && row.end_date);
    return Boolean(start && end && end < start);
  }

  // Every reason this row is flagged, in one fixed order: hard date error,
  // then short notice, then missing fields in required-set order. The order is
  // deliberately NOT queue-aware -- a row must read the same wherever it
  // appears or the Issue column cannot be learned. Descriptors carry no
  // user-facing copy; app.js owns the wording.
  function rowIssues(row) {
    const issues = [];
    if (hasInvalidDates(row)) issues.push({kind: 'invalid-date', field: 'end_date'});
    if (isShortNotice(row)) {
      issues.push({kind: 'short-notice', field: 'start_date', leadDays: Number(row.planning_lead_days)});
    }
    planningCompleteness(row).missing.forEach(field => issues.push({kind: 'missing', field}));
    return issues;
  }

  function quantile(sorted, p) {
    if (!sorted.length) return null;
    if (sorted.length === 1) return sorted[0];
    const index = (sorted.length - 1) * p;
    const lower = Math.floor(index);
    const upper = Math.ceil(index);
    const value = sorted[lower] + (sorted[upper] - sorted[lower]) * (index - lower);
    return Math.round(value * 10) / 10;
  }

  function leadTimeStats(rows, thresholdDays) {
    const threshold = Number.isFinite(thresholdDays) ? thresholdDays : 7;
    const values = rows
      .filter(r => !empty(r.planning_lead_days))
      .map(r => Number(r.planning_lead_days))
      .filter(v => Number.isFinite(v) && v >= 0)
      .sort((a, b) => a - b);
    const shortNotice = values.filter(v => v < threshold).length;
    return {
      valid: values.length,
      excluded: rows.length - values.length,
      shortNotice,
      shortNoticeRate: values.length ? Math.round((shortNotice / values.length) * 1000) / 10 : 0,
      median: quantile(values, 0.5),
      p25: quantile(values, 0.25),
      p75: quantile(values, 0.75)
    };
  }

  function parseDate(value) {
    if (empty(value)) return null;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function fieldValueChanged(field, original, next) {
    if (field === 'start_date' || field === 'end_date') {
      const originalDate = parseDate(original);
      const nextDate = parseDate(next);
      if (originalDate && nextDate) return originalDate.getTime() !== nextDate.getTime();
    }
    return String(original === null || original === undefined ? '' : original) !== String(next === null || next === undefined ? '' : next);
  }

  function safeCsvValue(value) {
    const text = String(value === null || value === undefined ? '' : value);
    return /^\s*[=+\-@]/.test(text) ? `'${text}` : text;
  }

  function dayGap(a, b) {
    const leftDay = Date.UTC(a.getFullYear(), a.getMonth(), a.getDate());
    const rightDay = Date.UTC(b.getFullYear(), b.getMonth(), b.getDate());
    return Math.abs(leftDay - rightDay) / 86400000;
  }

  function sharesDimension(a, b, field) {
    const right = new Set(normalizeMulti(b[field]).map(v => v.toLowerCase()));
    return normalizeMulti(a[field]).some(v => right.has(v.toLowerCase()));
  }

  function priorityRank(value) {
    const ranks = {critical: 4, high: 3, medium: 2, normal: 1, low: 0};
    return ranks[String(value || '').toLowerCase()] ?? 1;
  }

  function detectCollisions(rows, options) {
    const proximityDays = Number.isFinite(options && options.proximityDays) ? options.proximityDays : 0;
    // Precompute epoch-day (same Date.UTC day math as dayGap) once per row, then sort
    // indices by day and slide a window instead of comparing every pair — O(n log n + n*k)
    // instead of O(n^2) for the n rows this app renders (5k+).
    const epochDay = rows.map(row => {
      const start = parseDate(row.start_date);
      return start ? Date.UTC(start.getFullYear(), start.getMonth(), start.getDate()) / 86400000 : null;
    });
    const sortedIdx = [];
    for (let i = 0; i < rows.length; i += 1) {
      if (epochDay[i] !== null) sortedIdx.push(i);
    }
    sortedIdx.sort((a, b) => epochDay[a] - epochDay[b]);

    const collisions = [];
    for (let a = 0; a < sortedIdx.length; a += 1) {
      for (let b = a + 1; b < sortedIdx.length; b += 1) {
        const idxA = sortedIdx[a];
        const idxB = sortedIdx[b];
        if (epochDay[idxB] - epochDay[idxA] > proximityDays) break;
        const leftIdx = Math.min(idxA, idxB);
        const rightIdx = Math.max(idxA, idxB);
        const left = rows[leftIdx];
        const right = rows[rightIdx];
        if (!sharesDimension(left, right, 'channel') || !sharesDimension(left, right, 'target_audience')) continue;
        const samePack = !empty(left.tracking_pack_id) && left.tracking_pack_id === right.tracking_pack_id;
        const rank = Math.max(priorityRank(left.priority), priorityRank(right.priority));
        const severity = samePack ? 'info' : rank >= 4 ? 'critical' : rank >= 3 ? 'high' : 'medium';
        collisions.push({
          id: `${left.tracking_id || leftIdx}::${right.tracking_id || rightIdx}`,
          left,
          right,
          gapDays: Math.abs(epochDay[leftIdx] - epochDay[rightIdx]),
          kind: samePack ? 'orchestration' : 'conflict',
          severity
        });
      }
    }
    return collisions.sort((a, b) => {
      const order = {critical: 4, high: 3, medium: 2, info: 1};
      return order[b.severity] - order[a.severity] || a.gapDays - b.gapDays;
    });
  }

  function campaignScorecards(rows) {
    const groups = new Map();
    rows.forEach(row => {
      const key = row.tracking_pack_id || row.communication_pack || row.campaign;
      if (empty(key)) return;
      if (!groups.has(key)) groups.set(key, {id: key, campaign: row.campaign || row.communication_pack || key, rows: [], channels: new Set(), objectives: new Set(), audiences: new Set(), dates: []});
      const group = groups.get(key);
      group.rows.push(row);
      normalizeMulti(row.channel).forEach(v => group.channels.add(v));
      normalizeMulti(row.strategic_objectives).forEach(v => group.objectives.add(v));
      normalizeMulti(row.target_audience).forEach(v => group.audiences.add(v));
      const date = parseDate(row.start_date);
      if (date) group.dates.push(date);
    });
    return Array.from(groups.values()).map(group => {
      group.dates.sort((a, b) => a - b);
      const first = group.dates[0] || null;
      const last = group.dates[group.dates.length - 1] || null;
      return {
        id: group.id,
        campaign: group.campaign,
        activities: group.rows.length,
        channels: group.channels.size,
        channelNames: Array.from(group.channels),
        objectives: group.objectives.size,
        audiences: group.audiences.size,
        firstDate: first,
        lastDate: last,
        channelGapDays: first && last ? dayGap(first, last) : null,
        rows: group.rows
      };
    }).sort((a, b) => b.activities - a.activities);
  }

  // Intake cohort: the activities that entered planning inside a window.
  //
  // The studio can only show stocks -- "108 records need remediation" -- and a
  // stock cannot move without a nightly snapshot nobody keeps. The flow can:
  // source_created_at records when each activity entered the plan, so the
  // quality of what arrives in one window is directly comparable with the
  // window before it. That answers the question a comms lead actually has,
  // which is not "how much debris is lying around" but "is what we take in
  // getting better".
  //
  // Falls back to created_at for rows that never came from the source system.
  function createdBetween(rows, from, to) {
    return rows.filter(row => {
      const date = parseDate(row.source_created_at) || parseDate(row.created_at);
      return date && date >= from && date < to;
    });
  }

  // Which period a comparison runs against. Pure arithmetic, kept out of the
  // renderer so it can be tested: an earlier version computed the window inline
  // and referenced a binding before its declaration, which `node --check` waves
  // through because it is a runtime error, not a syntax one.
  //
  // With a range selected the baseline is the equal-length span immediately
  // before it; without one there is nothing to compare "all time" against, so
  // the window falls back to the next 30 days. `provisional` marks a window
  // reaching past today, whose counts are still being planned and therefore
  // understate the period.
  function comparisonWindow(rangeFrom, rangeTo, now, forwardDays) {
    const days = Number.isFinite(forwardDays) ? forwardDays : 30;
    const active = Boolean(rangeFrom && rangeTo);
    const from = active ? new Date(rangeFrom) : new Date(now);
    const to = active ? new Date(rangeTo) : new Date(new Date(now).setDate(now.getDate() + days));
    const spanMs = Math.max(1, to - from);
    const endOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59, 999);
    return {
      active,
      current: {from, to},
      previous: {from: new Date(from.getTime() - spanMs), to: from},
      spanDays: Math.max(1, Math.floor(spanMs / 86400000)),
      provisional: to > endOfToday
    };
  }

  function dataQuality(rows) {
    const counts = new Map();
    let missingTrackingIds = 0;
    let invalidDateRanges = 0;
    let missingPackIds = 0;
    let incomplete = 0;
    rows.forEach(row => {
      if (empty(row.tracking_id)) missingTrackingIds += 1;
      else counts.set(row.tracking_id, (counts.get(row.tracking_id) || 0) + 1);
      const start = parseDate(row.start_date);
      const end = parseDate(row.end_date);
      if (start && end && end < start) invalidDateRanges += 1;
      if (!hasCampaignOrPack(row)) missingPackIds += 1;
      if (planningCompleteness(row).score < 100) incomplete += 1;
    });
    return {
      total: rows.length,
      missingTrackingIds,
      duplicateTrackingIds: Array.from(counts.values()).filter(n => n > 1).length,
      invalidDateRanges,
      missingPackIds,
      incomplete,
      completenessRate: rows.length ? Math.round(((rows.length - incomplete) / rows.length) * 1000) / 10 : 0
    };
  }

  function applyChanges(rows, changes) {
    const idCounts = new Map();
    rows.forEach(row => {
      const id = String(row.tracking_id || '');
      if (id) idCounts.set(id, (idCounts.get(id) || 0) + 1);
    });
    const byId = new Map((changes || []).map(change => [String(change.tracking_id), change]));
    return rows.map(row => {
      const id = String(row.tracking_id || '');
      const change = byId.get(id);
      if (!change) return Object.assign({}, row);
      if (idCounts.get(id) !== 1) return Object.assign({}, row, {_draftConflict: 'duplicate-tracking-id'});
      const baseModified = parseDate(change.base_modified);
      const currentModified = parseDate(row.modified);
      if (baseModified && currentModified && baseModified.getTime() !== currentModified.getTime()) {
        return Object.assign({}, row, {_draftConflict: 'stale-snapshot'});
      }
      return Object.assign({}, row, change.patch || {}, {_localDraft: true});
    });
  }

  function attentionItems(rows, options) {
    const threshold = Number.isFinite(options && options.shortNoticeDays) ? options.shortNoticeDays : 7;
    const items = [];
    rows.forEach(row => {
      const completeness = planningCompleteness(row);
      if (completeness.score < 100) items.push({type: 'incomplete', severity: completeness.score < 63 ? 'critical' : 'high', row, detail: `Missing: ${completeness.missing.join(', ')}`});
      const lead = Number(row.planning_lead_days);
      if (Number.isFinite(lead) && lead >= 0 && lead < threshold) items.push({type: 'short-notice', severity: lead < 3 ? 'critical' : 'high', row, detail: `${lead} days lead time`});
      const start = parseDate(row.start_date);
      const end = parseDate(row.end_date);
      if (start && end && end < start) items.push({type: 'invalid-date', severity: 'critical', row, detail: 'End date is before start date'});
    });
    return items;
  }

  function weeklyCoverage(rows, weeks, startDate) {
    const start = startDate ? new Date(startDate) : new Date();
    start.setHours(0, 0, 0, 0);
    const result = [];
    for (let i = 0; i < weeks; i += 1) {
      const from = new Date(start);
      from.setDate(from.getDate() + i * 7);
      const to = new Date(from);
      to.setDate(to.getDate() + 7);
      const inWeek = rows.filter(row => {
        const date = parseDate(row.start_date);
        return date && date >= from && date < to;
      });
      result.push({from, to, count: inWeek.length, rows: inWeek});
    }
    return result;
  }

  return {
    escapeHtml,
    normalizeMulti,
    fieldValueChanged,
    safeCsvValue,
    planningCompleteness,
    leadTimeStats,
    detectCollisions,
    campaignScorecards,
    dataQuality,
    createdBetween,
    comparisonWindow,
    applyChanges,
    attentionItems,
    weeklyCoverage,
    parseDate,
    REQUIRED_INTERNAL,
    REQUIRED_EXTERNAL,
    requiredFor,
    rowIssues,
    isShortNotice,
    hasInvalidDates
  };
});
