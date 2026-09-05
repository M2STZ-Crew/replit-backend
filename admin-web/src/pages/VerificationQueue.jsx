import { useCallback, useEffect, useState } from 'react';

import { api } from '../api/client.js';
import {
  agencyLabel,
  canRejectIncidents,
  canVerifyIncidents,
  isObserver,
  useAuth,
} from '../auth.jsx';

// Confidence bands from the backend's generated column (Section 2.3).
const BAND = {
  high: { label: 'High confidence', color: '#22C55E' },
  medium: { label: 'Medium confidence', color: '#EAB308' },
  low: { label: 'Low confidence', color: '#FF544E' },
};

// Reporter credibility badges (Section 2.1).
const BADGE = {
  green_check: { label: '100% verified', color: '#22C55E' },
  green: { label: 'High credibility', color: '#22C55E' },
  light_green: { label: 'Partly verified', color: '#EAB308' },
  yellow: { label: 'Low credibility', color: '#EAB308' },
};

function badgeOf(pct) {
  if (pct >= 100) return BADGE.green_check;
  if (pct >= 90) return BADGE.green;
  if (pct >= 50) return BADGE.light_green;
  return BADGE.yellow;
}

function when(ts) {
  if (!ts) return '—';
  return new Date(ts).toLocaleString(undefined, {
    day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit',
  });
}

/// Stage 3 of the incident lifecycle: a Fire Volunteer Sub-Admin reviews the
/// evidence and decides (Section 2.5).
///
/// Everything the master context lists as a decision input is on screen —
/// photographs, the reporter's verification percentage, neighbourhood
/// corroboration, the area confidence score and the GPS cross-reference — so the
/// judgement is human but informed, which is the whole point of v8 dropping
/// automated fire detection.
export default function VerificationQueue() {
  const { user } = useAuth();
  const [pending, setPending] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState('');

  const mayVerify = canVerifyIncidents(user);
  const mayReject = canRejectIncidents(user);

  // An observer agency cannot action anything, so a pending-only queue would be
  // a list of things they are not allowed to touch. Show them the live incidents
  // involving their agency instead — that is the situational awareness they are
  // here for (Section 1.3 problem 9).
  const observer = isObserver(user);

  const loadQueue = useCallback(async () => {
    setLoading(true);
    try {
      const rows = observer
        ? await api.incidents({ limit: 100 })
        : await api.incidents({ status: 'pending', limit: 100 });
      setPending(rows);
      setSelectedId((current) =>
        current && rows.some((r) => r.id === current) ? current : rows[0]?.id ?? null,
      );
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [observer]);

  useEffect(() => { loadQueue(); }, [loadQueue]);

  useEffect(() => {
    if (!selectedId) { setDetail(null); setReports([]); return; }
    let cancelled = false;
    (async () => {
      const [d, r] = await Promise.all([
        api.incident(selectedId).catch(() => null),
        api.incidentReports(selectedId).catch(() => []),
      ]);
      if (!cancelled) { setDetail(d); setReports(r); }
    })();
    return () => { cancelled = true; };
  }, [selectedId]);

  async function decide(action) {
    if (!selectedId) return;
    setBusy(true);
    setError(null);
    try {
      if (action === 'verify') await api.incidentVerify(selectedId);
      else await api.incidentReject(selectedId, reason.trim());
      setRejecting(false);
      setReason('');
      await loadQueue();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const band = detail?.confidence_band ? BAND[detail.confidence_band] : null;

  return (
    <div className="vq">
      <div className="vq-head">
        <div>
          <h2 className="vq-title">{observer ? 'Incidents' : 'Verification queue'}</h2>
          <p className="vq-sub">
            {loading
              ? 'Loading…'
              : observer
                ? `${pending.length} active incident${pending.length === 1 ? '' : 's'} involving ${agencyLabel(user?.agency_type)}`
                : `${pending.length} incident${pending.length === 1 ? '' : 's'} awaiting review`}
          </p>
        </div>
        <button className="vq-refresh" onClick={loadQueue} disabled={loading}>Refresh</button>
      </div>

      {observer ? (
        <div className="vq-note">
          You are signed in for <strong>{agencyLabel(user?.agency_type)}</strong>. These
          are the incidents where a reporter asked for your agency, shown so your
          units know what is happening. Verifying, dispatching and resolving are
          handled by Fire Volunteer and BFP coordinators.
        </div>
      ) : !mayVerify ? (
        <div className="vq-note">
          {user?.role === 'admin'
            ? 'Signed in as Admin. Only a Fire Volunteer Sub-Admin may verify an incident (Section 6); you can still reject a false report.'
            : 'Your account cannot verify incidents — this requires a Fire Volunteer Sub-Admin.'}
        </div>
      ) : null}

      {error && <div className="vq-error">{error}</div>}

      <div className="vq-cols">
        <div className="vq-list">
          {!loading && pending.length === 0 && (
            <div className="vq-empty">
              {observer
                ? 'No active incidents have requested your agency.'
                : 'Nothing awaiting verification.'}
            </div>
          )}
          {pending.map((inc) => (
            <button
              key={inc.id}
              className={`vq-item${inc.id === selectedId ? ' is-active' : ''}`}
              onClick={() => { setSelectedId(inc.id); setRejecting(false); }}
            >
              <div className="vq-item-top">
                <span className="vq-item-name">{inc.designation}</span>
                <span
                  className="vq-chip"
                  style={{ color: (BAND[inc.confidence_band] || BAND.low).color }}
                >
                  {Math.round((inc.confidence_score ?? 0) * 100)}%
                </span>
              </div>
              <div className="vq-item-sub">
                {inc.report_count} report{inc.report_count === 1 ? '' : 's'} · {when(inc.reported_at)}
                {observer && inc.status ? ` · ${inc.status.replace(/_/g, ' ')}` : ''}
              </div>
            </button>
          ))}
        </div>

        <div className="vq-detail">
          {!detail && <div className="vq-empty">Select an incident to review.</div>}
          {detail && (
            <>
              <div className="vq-detail-head">
                <div>
                  <h3 className="vq-detail-title">{detail.designation}</h3>
                  <div className="vq-detail-sub">
                    Reported {when(detail.reported_at)} · {detail.centroid_lat?.toFixed(5)}, {detail.centroid_lng?.toFixed(5)}
                  </div>
                </div>
                {band && (
                  <span className="vq-band" style={{ color: band.color, borderColor: band.color }}>
                    {band.label} · {Math.round((detail.confidence_score ?? 0) * 100)}%
                  </span>
                )}
              </div>

              {/* The three confidence inputs, shown separately so a dispatcher can
                  see WHY the score is what it is rather than trusting one number. */}
              <div className="vq-scores">
                <div className="vq-score">
                  <span className="vq-score-v">{detail.report_count}</span>
                  <span className="vq-score-l">reports</span>
                </div>
                <div className="vq-score">
                  <span className="vq-score-v">{Math.round((detail.s_score ?? 0) * 100)}%</span>
                  <span className="vq-score-l">spatial agreement</span>
                </div>
                <div className="vq-score">
                  <span className="vq-score-v">{Math.round((detail.v_score ?? 0) * 100)}%</span>
                  <span className="vq-score-l">reporter credibility</span>
                </div>
              </div>

              <h4 className="vq-section">Evidence ({reports.length})</h4>
              <div className="vq-reports">
                {reports.map((r) => {
                  const b = badgeOf(r.user_verified_percent ?? 0);
                  return (
                    <div key={r.id} className="vq-report">
                      {r.photo_url
                        ? <img className="vq-photo" src={r.photo_url} alt="Reported scene" />
                        : <div className="vq-photo vq-photo-missing">No photo</div>}
                      <div className="vq-report-meta">
                        <div className="vq-reporter">{r.reporter_name || 'Unnamed reporter'}</div>
                        <div className="vq-badge" style={{ color: b.color }}>
                          {r.user_verified_percent ?? 0}% · {b.label}
                        </div>
                        {r.gps_discrepancy_flag && (
                          <div className="vq-flag">
                            Photo GPS disagrees with device GPS — possible spoofing
                          </div>
                        )}
                        {!r.has_exif && (
                          <div className="vq-muted">No photo GPS (gallery upload)</div>
                        )}
                      </div>
                    </div>
                  );
                })}
                {reports.length === 0 && <div className="vq-empty">No member reports.</div>}
              </div>

              {observer ? null : (
              <div className="vq-actions">
                {rejecting ? (
                  <>
                    <input
                      className="vq-reason"
                      placeholder="Why is this being rejected? (required)"
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                      autoFocus
                    />
                    <button
                      className="vq-btn vq-btn-reject"
                      disabled={busy || reason.trim().length === 0}
                      onClick={() => decide('reject')}
                    >
                      {busy ? 'Rejecting…' : 'Confirm reject'}
                    </button>
                    <button className="vq-btn" onClick={() => setRejecting(false)} disabled={busy}>
                      Cancel
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      className="vq-btn vq-btn-verify"
                      disabled={!mayVerify || busy}
                      title={mayVerify ? '' : 'Requires a Fire Volunteer Sub-Admin'}
                      onClick={() => decide('verify')}
                    >
                      {busy ? 'Working…' : 'Verify incident'}
                    </button>
                    <button
                      className="vq-btn vq-btn-reject"
                      disabled={!mayReject || busy}
                      onClick={() => setRejecting(true)}
                    >
                      Reject
                    </button>
                  </>
                )}
              </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
