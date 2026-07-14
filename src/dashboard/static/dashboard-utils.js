// Shared dashboard utility functions.
// Loaded by all dashboard templates before any page-specific scripts.
// NOTE: All color values are driven by dashboard.css — no hardcoded hex codes.

function opinionBadge(opinion) {
  const cls = opinion === 'BULLISH' ? 'badge-green' : opinion === 'BEARISH' ? 'badge-red' : 'badge-gray';
  var label;
  if (opinion === 'BULLISH') label = t('opinion.bullish');
  else if (opinion === 'BEARISH') label = t('opinion.bearish');
  else if (opinion === 'NEUTRAL') label = t('opinion.neutral');
  else label = opinion || t('opinion.unknown');
  return `<span class="badge ${cls}">${label}</span>`;
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

// ── API URL builder ──────────────────────────────
function apiUrl(path, extra = {}) {
  const p = new URLSearchParams();
  const pageParams = new URLSearchParams(window.location.search);
  const user = pageParams.get('user');
  if (user) p.set('user', user);
  for (const [k, v] of Object.entries(extra)) p.set(k, v);
  const qs = p.toString();
  return qs ? `${path}?${qs}` : path;
}

// ── Filter clear helper ──────────────────────────
function clearFilter(id) {
  var el = document.getElementById(id);
  if (el) { el.value = ''; el.dispatchEvent(new Event('input')); el.focus(); }
}
