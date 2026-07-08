// Shared dashboard utility functions.
// Loaded by all dashboard templates before any page-specific scripts.
// NOTE: All color values are driven by dashboard.css — no hardcoded hex codes.

function opinionBadge(opinion) {
  const cls = opinion === 'BULLISH' ? 'badge-green' : opinion === 'BEARISH' ? 'badge-red' : 'badge-gray';
  return `<span class="badge ${cls}">${opinion}</span>`;
}

function formatPrice(v) {
  if (v == null || v === 0) return '&mdash;';
  return parseFloat(v).toFixed(2);
}

function formatLocalTime(isoStr) {
  if (!isoStr) return '&mdash;';
  try {
    const d = new Date(isoStr + (isoStr.endsWith('Z') ? '' : 'Z'));
    if (isNaN(d.getTime())) return isoStr;

    const pad = (n) => String(n).padStart(2, '0');

    // UTC: YYYY-MM-DD HH:MM:SSZ
    const utc = d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate())
      + ' ' + pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()) + ':' + pad(d.getUTCSeconds()) + 'Z';

    // Local: YYYY-MM-DD HH:MM:SS TZ
    const local = d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
      + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());

    const tz = Intl.DateTimeFormat('en', { timeZoneName: 'shortOffset' })
      .formatToParts(d).find(p => p.type === 'timeZoneName')?.value;

    return utc + ' (' + local + (tz ? ' ' + tz : '') + ')';
  } catch { return isoStr; }
}

/** Compact local time for table columns: MM-DD HH:MM */
function formatLocalTimeShort(isoStr) {
  if (!isoStr) return '&mdash;';
  try {
    const d = new Date(isoStr + (isoStr.endsWith('Z') ? '' : 'Z'));
    if (isNaN(d.getTime())) return isoStr;
    const pad = (n) => String(n).padStart(2, '0');
    return pad(d.getMonth() + 1) + '-' + pad(d.getDate())
      + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  } catch { return isoStr; }
}

function formatElapsed(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}
