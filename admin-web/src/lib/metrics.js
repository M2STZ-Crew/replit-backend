/// The operational success metrics of Master Context v10 §11.2, computed from
/// the incident timestamps the console already loads — nothing estimated.
///
///   * report → verification           reported_at → verified_at
///   * verification → units on scene   verified_at → arrived_at
///   * fire out → Post-Incident Report  resolved_at → closed_at (new in v10)
///   * share reaching high confidence  final confidence band
///   * false-alarm rate                rejected ÷ decided (verified or rejected)
///
/// Each interval is a median — one slow night should not define the figure —
/// over the incidents that reached both ends, with the count it rests on. An
/// interval nobody has reached yet is null ("—"), never a zero that would read
/// as instant. Merged areas are left out: their reports moved to the survivor.

function minutesBetween(a, b) {
  return (new Date(b).getTime() - new Date(a).getTime()) / 60000;
}

export function median(values) {
  if (values.length === 0) return null;
  const s = [...values].sort((x, y) => x - y);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

function interval(incidents, from, to) {
  const values = incidents
    .filter((i) => i[from] && i[to])
    .map((i) => minutesBetween(i[from], i[to]))
    .filter((m) => m >= 0);
  return { median: median(values), n: values.length };
}

export function responseMetrics(incidents, { days = 30, now = Date.now() } = {}) {
  const since = now - days * 864e5;
  const inWindow = incidents.filter(
    (i) => i.status !== 'merged' && new Date(i.reported_at).getTime() >= since,
  );
  const decided = inWindow.filter((i) => i.verified_at || i.rejected_at);
  const rejected = decided.filter((i) => i.rejected_at);
  const high = inWindow.filter((i) => i.confidence_band === 'high');
  return {
    days,
    count: inWindow.length,
    reportToVerify: interval(inWindow, 'reported_at', 'verified_at'),
    verifyToScene: interval(inWindow, 'verified_at', 'arrived_at'),
    fireOutToReport: interval(inWindow, 'resolved_at', 'closed_at'),
    highConfidence: {
      share: inWindow.length ? high.length / inWindow.length : null,
      n: inWindow.length,
    },
    falseAlarm: {
      share: decided.length ? rejected.length / decided.length : null,
      n: decided.length,
    },
  };
}

export function formatMinutes(m) {
  if (m == null) return '—';
  if (m < 1) return `${Math.round(m * 60)} s`;
  if (m < 60) return `${m < 10 ? m.toFixed(1) : Math.round(m)} min`;
  const h = Math.floor(m / 60);
  return `${h} h ${Math.round(m % 60)} min`;
}

export function formatShare(share) {
  return share == null ? '—' : `${Math.round(share * 100)}%`;
}
