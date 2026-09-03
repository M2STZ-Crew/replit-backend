import { useCallback, useEffect, useState } from 'react';

import { api } from '../api/client.js';

function when(ts) {
  if (!ts) return '—';
  return new Date(ts).toLocaleString(undefined, {
    day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit',
  });
}

/// How long a submission has been waiting. A queue that quietly grows is the
/// failure mode here: nobody chases their own verification, they just stay on a
/// yellow badge and every report they file looks less credible.
function waitingFor(ts) {
  if (!ts) return null;
  const hours = (Date.now() - new Date(ts).getTime()) / 36e5;
  if (hours < 1) return { text: 'just now', stale: false };
  if (hours < 24) return { text: `${Math.floor(hours)}h waiting`, stale: hours >= 12 };
  return { text: `${Math.floor(hours / 24)}d waiting`, stale: true };
}

/// Admin: National ID manual review (Section 2.1 Tier 2, Section 2.6).
///
/// Approving awards +50%, the largest single step and the only route past a
/// light-green badge to green. Rejecting awards nothing and is recorded with the
/// reviewer and their notes, because refusing someone's government ID is a
/// decision that needs an audit trail.
export default function IdReview() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [rejectingId, setRejectingId] = useState(null);
  const [notes, setNotes] = useState('');
  const [zoom, setZoom] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await api.pendingVerifications());
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function decide(id, action) {
    setBusyId(id);
    setError(null);
    try {
      if (action === 'approve') await api.approveVerification(id);
      else await api.rejectVerification(id, notes.trim());
      setRejectingId(null);
      setNotes('');
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="idr">
      <div className="idr-head">
        <div>
          <h2 className="idr-title">National ID review</h2>
          <p className="idr-sub">
            {loading
              ? 'Loading…'
              : `${items.length} submission${items.length === 1 ? '' : 's'} awaiting review`}
          </p>
        </div>
        <button className="idr-refresh" onClick={load} disabled={loading}>Refresh</button>
      </div>

      {error && <div className="idr-error">{error}</div>}

      {!loading && items.length === 0 && (
        <div className="idr-empty">
          Nothing awaiting review. Submissions appear here when someone uploads a
          National ID and selfie from the mobile app.
        </div>
      )}

      <div className="idr-list">
        {items.map((item) => {
          const wait = waitingFor(item.submitted_at);
          const isRejecting = rejectingId === item.id;
          const busy = busyId === item.id;

          return (
            <div key={item.id} className="idr-card">
              <div className="idr-card-head">
                <div>
                  <div className="idr-name">{item.full_name || 'Unnamed applicant'}</div>
                  <div className="idr-meta">
                    {item.email || 'no email'} · submitted {when(item.submitted_at)}
                  </div>
                </div>
                {wait && (
                  <span className={`idr-wait${wait.stale ? ' is-stale' : ''}`}>
                    {wait.text}
                  </span>
                )}
              </div>

              <div className="idr-images">
                <figure className="idr-fig">
                  <figcaption className="idr-cap">Government ID</figcaption>
                  {item.id_image_url ? (
                    <img
                      className="idr-img"
                      src={item.id_image_url}
                      alt="Submitted government ID"
                      onClick={() => setZoom(item.id_image_url)}
                    />
                  ) : (
                    <div className="idr-img idr-img-missing">Not provided</div>
                  )}
                </figure>
                <figure className="idr-fig">
                  <figcaption className="idr-cap">Selfie</figcaption>
                  {item.selfie_image_url ? (
                    <img
                      className="idr-img"
                      src={item.selfie_image_url}
                      alt="Submitted selfie"
                      onClick={() => setZoom(item.selfie_image_url)}
                    />
                  ) : (
                    <div className="idr-img idr-img-missing">Not provided</div>
                  )}
                </figure>
              </div>

              <p className="idr-hint">
                Check the selfie is the same person as the ID photo, and that the
                name on the ID matches the account.
              </p>

              <div className="idr-actions">
                {isRejecting ? (
                  <>
                    <input
                      className="idr-notes"
                      placeholder="Reason for rejection (recorded on the review)"
                      value={notes}
                      onChange={(e) => setNotes(e.target.value)}
                      autoFocus
                    />
                    <button
                      className="idr-btn idr-btn-reject"
                      disabled={busy || notes.trim().length === 0}
                      onClick={() => decide(item.id, 'reject')}
                    >
                      {busy ? 'Rejecting…' : 'Confirm reject'}
                    </button>
                    <button
                      className="idr-btn"
                      disabled={busy}
                      onClick={() => { setRejectingId(null); setNotes(''); }}
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      className="idr-btn idr-btn-approve"
                      disabled={busy}
                      onClick={() => decide(item.id, 'approve')}
                    >
                      {busy ? 'Working…' : 'Approve (+50%)'}
                    </button>
                    <button
                      className="idr-btn idr-btn-reject"
                      disabled={busy}
                      onClick={() => { setRejectingId(item.id); setNotes(''); }}
                    >
                      Reject
                    </button>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Identity documents are small and detailed; a thumbnail is not enough to
          judge one against a selfie. */}
      {zoom && (
        <div className="idr-lightbox" onClick={() => setZoom(null)}>
          <img src={zoom} alt="Enlarged submission" />
          <button className="idr-close" onClick={() => setZoom(null)}>Close</button>
        </div>
      )}
    </div>
  );
}
