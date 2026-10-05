import { useCallback, useEffect, useState } from 'react';

import { api } from '../api/client.js';
import { agencyLabel, useAuth } from '../auth.jsx';

const EMPTY_FORM = { firstName: '', lastName: '', mobile: '' };

/// Responders (v1.12.4) — where this captain's responders get their accounts.
///
/// A police, medical or barangay captain makes the Response Team accounts of
/// their own agency and team. The server names each one from the account
/// directory's rule — first initial and surname, `.res` and the agency
/// (jdelacruz.respol@replit.com), numbered after the surname when taken — and
/// shows it as the name is typed. The password is generated and shown once,
/// to hand over in person: @replit.com has no mailboxes, so a forgotten
/// password is reset here too. Deactivating stops an account signing in and
/// keeps its history.
export default function RespondersPage() {
  const { user } = useAuth();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [form, setForm] = useState(null);
  const [preview, setPreview] = useState(null);
  const [formError, setFormError] = useState(null);
  const [creds, setCreds] = useState(null);
  const [busy, setBusy] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await api.responders());
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // The address, a moment after the name stops changing.
  const first = form?.firstName.trim() ?? '';
  const last = form?.lastName.trim() ?? '';
  useEffect(() => {
    if (!first || !last) {
      setPreview(null);
      return undefined;
    }
    let live = true;
    const timer = setTimeout(async () => {
      try {
        const res = await api.responderEmailPreview(first, last);
        if (live) {
          setPreview(res.email);
          setFormError(null);
        }
      } catch (e) {
        if (live) setFormError(e.message);
      }
    }, 400);
    return () => { live = false; clearTimeout(timer); };
  }, [first, last]);

  async function create(e) {
    e.preventDefault();
    setBusy('create');
    setFormError(null);
    try {
      const res = await api.createResponder(form);
      setCreds({
        name: res.responder?.full_name ?? 'The responder',
        email: res.email,
        password: res.temporary_password,
        created: true,
      });
      setForm(null);
      setPreview(null);
      load();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setBusy(null);
    }
  }

  async function reset(r) {
    const name = r.full_name || 'this responder';
    if (!window.confirm(
      `Give ${name} a new password? Their current password stops working. ` +
      'You will see the new one once, to hand over.',
    )) return;
    setBusy(r.id);
    try {
      const res = await api.resetResponderPassword(r.id);
      setCreds({ name, email: res.email, password: res.temporary_password, created: false });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  }

  async function toggle(r) {
    const name = r.full_name || 'this responder';
    if (r.is_active) {
      const why = r.responding
        ? 'They are on a response now; it will be released. They will not be able to sign in.'
        : 'They will not be able to sign in. Their history stays, and you can reactivate them later.';
      if (!window.confirm(`Deactivate ${name}? ${why}`)) return;
    }
    setBusy(r.id);
    try {
      await (r.is_active ? api.deactivateResponder(r.id) : api.reactivateResponder(r.id));
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  }

  const active = rows.filter((r) => r.is_active).length;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <span className="os-eyebrow">Your team</span>
          <h1 className="page-title">Responders</h1>
          <p className="page-sub">
            Your {agencyLabel(user.agency_type)} responders sign in to the mobile app with the
            accounts you make here. Each gets a @replit.com address and a password you hand
            over in person.
          </p>
        </div>
        {!form && (
          <button className="btn-accent" onClick={() => { setForm(EMPTY_FORM); setCreds(null); }}>
            New responder
          </button>
        )}
      </header>

      {creds && (
        <section className="panel cred" aria-live="polite">
          <div className="panel-head">
            <span className="panel-title">{creds.created ? 'Account ready' : 'New password'}</span>
            <button className="btn-ghost" onClick={() => setCreds(null)}>Done</button>
          </div>
          <p className="page-sub">
            Give {creds.name} {creds.created ? 'these' : 'this password'} to sign in with. The
            password is shown only this once — it cannot be reset by email; you can give them a
            new one here.
          </p>
          <CopyRow label="Email" value={creds.email} />
          <CopyRow label="Password" value={creds.password} />
        </section>
      )}

      {form && (
        <form className="panel resp-form" onSubmit={create}>
          <div className="panel-head">
            <span className="panel-title">New responder</span>
            <button type="button" className="btn-ghost" onClick={() => setForm(null)}>Cancel</button>
          </div>
          <div className="resp-fields">
            <label className="field">
              <span className="os-eyebrow">First name</span>
              <input
                value={form.firstName}
                onChange={(e) => setForm({ ...form, firstName: e.target.value })}
                placeholder="Juan"
                autoFocus
                required
              />
            </label>
            <label className="field">
              <span className="os-eyebrow">Surname</span>
              <input
                value={form.lastName}
                onChange={(e) => setForm({ ...form, lastName: e.target.value })}
                placeholder="Dela Cruz"
                required
              />
            </label>
            <label className="field">
              <span className="os-eyebrow">Mobile (optional)</span>
              <input
                value={form.mobile}
                onChange={(e) => setForm({ ...form, mobile: e.target.value })}
                placeholder="09XX XXX XXXX"
                inputMode="tel"
              />
            </label>
          </div>
          <div className="resp-preview">
            <span className="os-eyebrow">Their sign-in</span>
            <span className={preview ? 'resp-email' : 'empty'}>
              {preview ?? 'Made from the first initial and surname'}
            </span>
          </div>
          {formError && <div className="note is-error">{formError}</div>}
          <div>
            <button className="btn-accent" disabled={!first || !last || busy === 'create'}>
              {busy === 'create' ? 'Creating…' : 'Create account'}
            </button>
          </div>
        </form>
      )}

      {error && <div className="note is-error">{error}</div>}

      <section className="panel table-panel">
        <div className="panel-head resp-head">
          <span className="panel-title">Your responders</span>
          <span className="os-eyebrow">{active} active</span>
        </div>
        <div className="table-scroll">
          <table className="log resp-table" role="table">
            <thead role="rowgroup">
              <tr role="row">
                <th role="columnheader">Name</th>
                <th role="columnheader">Sign-in</th>
                <th role="columnheader">Status</th>
                <th role="columnheader"><span className="ss-sr">Actions</span></th>
              </tr>
            </thead>
            <tbody role="rowgroup">
              {rows.map((r) => (
                <tr key={r.id} role="row" className={r.is_active ? '' : 'is-off'}>
                  <td role="cell" data-cell="name">{r.full_name || '—'}</td>
                  <td role="cell" data-cell="email">{r.email}</td>
                  <td role="cell" data-cell="status">
                    {!r.is_active ? (
                      <span className="pill resp-off">Deactivated</span>
                    ) : r.responding ? (
                      <span className="pill resp-run">On a run</span>
                    ) : (
                      <span className="pill resp-on">Active</span>
                    )}
                  </td>
                  <td role="cell" data-cell="actions">
                    <div className="resp-actions">
                      {r.is_active && (
                        <button className="btn-ghost" disabled={busy === r.id} onClick={() => reset(r)}>
                          Reset password
                        </button>
                      )}
                      <button
                        className={`btn-ghost${r.is_active ? ' resp-danger' : ''}`}
                        disabled={busy === r.id}
                        onClick={() => toggle(r)}
                      >
                        {r.is_active ? 'Deactivate' : 'Reactivate'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!loading && rows.length === 0 && (
            <p className="empty">No responder accounts yet. Make one for each person on your team.</p>
          )}
          {loading && <p className="empty">Loading…</p>}
        </div>
      </section>
    </div>
  );
}

function CopyRow({ label, value }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* select it by hand */
    }
  }
  return (
    <div className="cred-row">
      <span className="os-eyebrow">{label}</span>
      <code className="cred-value">{value}</code>
      <button className="btn-ghost" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
    </div>
  );
}
