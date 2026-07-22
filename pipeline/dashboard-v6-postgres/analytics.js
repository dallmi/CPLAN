(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.CplanAnalytics = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const REQUIRED_FIELDS = [
    'activity_name', 'start_date', 'channel', 'lead_team',
    'target_audience', 'priority', 'strategic_objectives', 'campaign_or_pack'
  ];

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
    return !empty(row.tracking_pack_id) || !empty(row.communication_pack) || !empty(row.campaign);
  }

  function planningCompleteness(row) {
    const missing = [];
    for (const field of REQUIRED_FIELDS) {
      if (field === 'campaign_or_pack') {
        if (!hasCampaignOrPack(row)) missing.push(field);
      } else if (field === 'lead_team') {
        if (empty(row.lead_team) && empty(row.lead)) missing.push(field);
      } else if (empty(row[field])) missing.push(field);
    }
    return {
      score: Math.round(((REQUIRED_FIELDS.length - missing.length) / REQUIRED_FIELDS.length) * 100),
      missing
    };
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
    const collisions = [];
    for (let i = 0; i < rows.length; i += 1) {
      for (let j = i + 1; j < rows.length; j += 1) {
        const left = rows[i];
        const right = rows[j];
        const leftStart = parseDate(left.start_date);
        const rightStart = parseDate(right.start_date);
        if (!leftStart || !rightStart || dayGap(leftStart, rightStart) > proximityDays) continue;
        if (!sharesDimension(left, right, 'channel') || !sharesDimension(left, right, 'target_audience')) continue;
        const samePack = !empty(left.tracking_pack_id) && left.tracking_pack_id === right.tracking_pack_id;
        const rank = Math.max(priorityRank(left.priority), priorityRank(right.priority));
        const severity = samePack ? 'info' : rank >= 4 ? 'critical' : rank >= 3 ? 'high' : 'medium';
        collisions.push({
          id: `${left.tracking_id || i}::${right.tracking_id || j}`,
          left,
          right,
          gapDays: dayGap(leftStart, rightStart),
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
    applyChanges,
    attentionItems,
    weeklyCoverage,
    parseDate
  };
});
