import { useCallback, useEffect, useState } from 'react';

import { api } from '../api/client.js';
import { useConsole } from '../components/ConsoleShell.jsx';
import Place from '../components/Place.jsx';
import {
  ConfirmDialog, EmptyState, PageHeader, Pager, StatePanel, StatusChip, usePager,
} from '../components/ui/index.js';
import { t } from '../i18n/i18n.jsx';
import { stepText } from '../lib/strikes.js';

/* Prank reports (v1.12.41; the ladder is app/services/report_strikes.py).
 *
 * 19 Nov 2026: "a false alarm or prank report can be temporarily cannot report
 * and has a progressive penalty". A coordinator gives the everyday strike while
 * rejecting a fire in the app. Here the central hub checks a 3rd or 4th step
 * (never the one who gave it), decides residents' appeals, and keeps the record
 * BFP or the LGU can act on: RA 9514 §8(i) makes a false or malicious fire
 * alarm a prohibited act. 911 and fire alerts are never blocked. */

const DAY = new Intl.DateTimeFormat('en-PH', {
  timeZone: 'Asia/Manila', day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit',
});
const at = (iso) => (iso ? DAY.format(new Date(iso)) : '—');

function chipOf(s) {
  if (s.status === 'awaiting_confirmation') return { label: t('Waiting for a second check'), tone: 'warn' };
  if (s.status === 'overturned') return { label: t('Removed'), tone: 'neutral' };
  if (s.appeal_state === 'pending') return { label: t('Appealed'), tone: 'info' };
  if (s.appeal_state === 'upheld') return { label: t('Appeal not accepted'), tone: 'danger' };
  return { label: t('In effect'), tone: 'danger' };
}

const VIEWS = [
  { key: 'to_check', get label() { return t('To check'); } },
  { key: 'appeals', get label() { return t('Appeals'); } },
  { key: 'all', get label() { return t('All strikes'); } },
];

const nameOf = (s) => s.resident_name || t('Unnamed resident');

/* Each action: its dialog, what the resident is told, and whether a note is required. */
const ACTIONS = {
  confirm: {
    get label() { return t('Confirm'); },
    title: (s) => t('Confirm {name}’s strike?', { name: nameOf(s) }),
    description: (s) => t('{step}. It takes effect now, and they are told at once.', { step: stepText(s.step) }),
    get noteLabel() { return t('Note for the record (optional)'); },
    noteRequired: false,
    destructive: true,
    run: (s, note) => api.confirmStrike(s.id, note),
    get done() { return t('Strike confirmed. The resident was told.'); },
  },
  decline: {
    get label() { return t('Decline'); },
    title: (s) => t('Decline {name}’s strike?', { name: nameOf(s) }),
    description: () => t('The strike is removed and its 24-hour pause ends. The resident is told it was removed.'),
    get noteLabel() { return t('Why (for the record)'); },
    noteRequired: true,
    destructive: false,
    run: (s, note) => api.declineStrike(s.id, note),
    get done() { return t('Strike declined and removed. The resident was told.'); },
  },
  overturned: {
    get label() { return t('Overturn'); },
    title: (s) => t('Overturn {name}’s strike?', { name: nameOf(s) }),
    description: () => t('The strike is removed. They can report again unless another strike pauses them.'),
    get noteLabel() { return t('Your answer (they read it)'); },
    noteRequired: false,
    destructive: false,
    run: (s, note) => api.decideStrikeAppeal(s.id, 'overturned', note),
    get done() { return t('Appeal accepted. The strike was removed.'); },
  },
  upheld: {
    get label() { return t('Uphold'); },
    title: (s) => t('Uphold {name}’s strike?', { name: nameOf(s) }),
    description: () => t('The strike stays. They read your answer in the app.'),
    get noteLabel() { return t('Your answer (they read it)'); },
    noteRequired: true,
    destructive: true,
    run: (s, note) => api.decideStrikeAppeal(s.id, 'upheld', note),
    get done() { return t('Appeal not accepted. The resident was told.'); },
  },
};

export default function PrankReports() {
  const { refreshQueues } = useConsole();
  const [view, setView] = useState('to_check');
  const [items, setItems] = useState([]);
  const [counts, setCounts] = useState({ to_check: 0, appeals: 0 });
  const [phase, setPhase] = useState('loading');
  const [error, setError] = useState(null);
  const [acting, setActing] = useState(null);
  const [note, setNote] = useState('');
  const [notice, setNotice] = useState(null);
  const { shown, pager } = usePager(items, { key: 'prank-reports', reset: [view] });

  const load = useCallback(async (which) => {
    setPhase('loading');
    setError(null);
    try {
      const [rows, toCheck, appeals] = await Promise.all([
        api.reportStrikes(which),
        api.reportStrikes('to_check').catch(() => null),
        api.reportStrikes('appeals').catch(() => null),
      ]);
      setItems(Array.isArray(rows) ? rows : []);
      setCounts({
        to_check: Array.isArray(toCheck) ? toCheck.length : 0,
        appeals: Array.isArray(appeals) ? appeals.length : 0,
      });
      setPhase('ready');
    } catch (e) {
      setError(e.message || t('The prank reports could not be loaded.'));
      setPhase('error');
    }
  }, []);
  useEffect(() => { load(view); }, [load, view]);

  useEffect(() => {
    if (!notice) return undefined;
    const timer = setTimeout(() => setNotice(null), 6000);
    return () => clearTimeout(timer);
  }, [notice]);

  function startAction(item, kind) {
    setNote('');
    setActing({ item, kind });
  }

  async function runAction() {
    const action = ACTIONS[acting.kind];
    const text = note.trim();
    if (action.noteRequired && !text) throw new Error(t('Write a short note first.'));
    await action.run(acting.item, text || null);
    setActing(null);
    setNotice(action.done);
    refreshQueues?.();
    await load(view);
  }

  const empty = {
    to_check: t('A 3rd or 4th strike waits here for a second staff member, who is never the one who gave it.'),
    appeals: t('A resident’s appeal of a strike waits here. Whoever gave the strike can’t decide it.'),
    all: t('Strikes appear here once a report is marked a prank. Each is deleted 12 months after it took effect.'),
  }[view];

  const action = acting ? ACTIONS[acting.kind] : null;

  return (
    <div className="rpl-page rpl-strikes-page">
      <PageHeader
        eyebrow={t('Central hub · False and prank reports')}
        title={t('Prank reports')}
        description={t('Only a report marked “Prank or malicious” gives a strike, never an honest mistake. Strikes count over 12 months: 24 hours, then 7 days, then 30 days, then no reporting until an appeal. Calling 911 and fire alerts are never blocked.')}
        actions={(
          <>
            {view === 'all' && items.length > 0 && (
              <button type="button" className="rpl-button rpl-button--secondary" onClick={() => window.print()}>{t('Print record')}</button>
            )}
            <button type="button" className="rpl-button rpl-button--secondary" onClick={() => load(view)} disabled={phase === 'loading'}>{t('Refresh')}</button>
          </>
        )}
      />

      <div className="rpl-toolbar">
        <div className="rpl-tabs" role="tablist" aria-label={t('Prank reports')}>
          {VIEWS.map((v) => (
            <button
              key={v.key}
              type="button"
              role="tab"
              aria-selected={view === v.key}
              className={`rpl-tab${view === v.key ? ' is-active' : ''}`}
              onClick={() => setView(v.key)}
            >
              {v.label}
              {counts[v.key] > 0 && <span className="web-count-badge" aria-label={t('{count} waiting', { count: counts[v.key] })}>{counts[v.key]}</span>}
            </button>
          ))}
        </div>
      </div>

      {phase === 'loading' ? (
        <StatePanel kind="loading" skeleton="cards" rows={3} title={t('Loading prank reports…')} busy />
      ) : phase === 'error' ? (
        <StatePanel kind="error" title={t('The prank reports couldn’t load')} description={error} onRetry={() => load(view)} />
      ) : items.length === 0 ? (
        <EmptyState icon="escalate" title={t('Nothing here')}>{empty}</EmptyState>
      ) : (
        <>
          <ul className="rpl-strike-list">
            {shown.map((s) => (
              <Strike key={s.id} s={s} view={view} onAct={startAction} />
            ))}
          </ul>
          <Pager {...pager} />
        </>
      )}

      <ConfirmDialog
        open={Boolean(acting)}
        eyebrow={acting ? stepText(acting.item.step) : ''}
        title={acting ? action.title(acting.item) : ''}
        description={acting ? action.description(acting.item) : ''}
        confirmLabel={action?.label}
        destructive={action?.destructive}
        onClose={() => setActing(null)}
        onConfirm={runAction}
      >
        {acting && (
          <label className="rpl-field">
            <span className="rpl-field-label">{action.noteLabel}</span>
            <textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} rows={3} />
          </label>
        )}
      </ConfirmDialog>

      {notice && <div className="rpl-toast" role="status"><span aria-hidden="true">✓</span>{notice}</div>}
    </div>
  );
}

function Strike({ s, view, onAct }) {
  const chip = chipOf(s);
  const facts = [
    [t('Given'), `${at(s.given_at)}${s.given_by_name ? ` · ${s.given_by_name}` : ''}${s.given_by_me ? ` · ${t('you')}` : ''}`],
    [t('The report'), s.report_created_at
      ? <>{at(s.report_created_at)}{s.report_lat != null && <> · <Place lat={s.report_lat} lng={s.report_lng} /></>}</>
      : t('No longer on record')],
    ...(s.report_notes ? [[t('It said'), `“${s.report_notes}”`]] : []),
    ...(s.checked_at ? [[t('Second check'), `${at(s.checked_at)}${s.checked_by_name ? ` · ${s.checked_by_name}` : ''}${s.check_note ? ` · “${s.check_note}”` : ''}`]] : []),
    ...(s.pause_ends_at ? [[t('Pause ends'), at(s.pause_ends_at)]] : []),
    ...(s.expires_at ? [[t('Strike ends'), at(s.expires_at)]] : []),
    ...(s.appeal_text ? [[t('Appeal'), `${at(s.appealed_at)} · “${s.appeal_text}”`]] : []),
    ...(s.appeal_decided_at ? [[t('Answer'), `${at(s.appeal_decided_at)}${s.appeal_decided_by_name ? ` · ${s.appeal_decided_by_name}` : ''}${s.appeal_note ? ` · “${s.appeal_note}”` : ''}`]] : []),
  ];
  const mine = s.given_by_me;
  return (
    <li className="rpl-strike">
      <div className="rpl-strike-head">
        <span className="rpl-cell-text">
          <span className="rpl-cell-title">{nameOf(s)}</span>
          <span className="rpl-cell-meta">
            {[s.resident_phone, s.resident_strikes === 1
              ? t('{count} strike in effect', { count: s.resident_strikes })
              : t('{count} strikes in effect', { count: s.resident_strikes })].filter(Boolean).join(' · ')}
          </span>
        </span>
        <StatusChip label={chip.label} tone={chip.tone} />
      </div>
      <p className="rpl-strike-step">{stepText(s.step)}{s.serious ? ` · ${t('serious case')}` : ''}</p>
      <p className="rpl-strike-reason">“{s.reason}”</p>
      <dl className="rpl-facts rpl-facts--wide">
        {facts.map(([label, value]) => (
          <div className="rpl-fact" key={label}><dt>{label}</dt><dd>{value}</dd></div>
        ))}
      </dl>
      {view === 'to_check' && s.status === 'awaiting_confirmation' && (
        <div className="rpl-strike-actions">
          {mine && <p className="rpl-field-help">{t('You gave this strike, so another reviewer checks it.')}</p>}
          <button type="button" className="rpl-button rpl-button--secondary" onClick={() => onAct(s, 'decline')} disabled={mine}>{t('Decline')}</button>
          <button type="button" className="rpl-button rpl-button--primary" onClick={() => onAct(s, 'confirm')} disabled={mine}>{t('Confirm')}</button>
        </div>
      )}
      {view === 'appeals' && s.appeal_state === 'pending' && (
        <div className="rpl-strike-actions">
          {mine && <p className="rpl-field-help">{t('You gave this strike, so another reviewer decides its appeal.')}</p>}
          <button type="button" className="rpl-button rpl-button--secondary" onClick={() => onAct(s, 'upheld')} disabled={mine}>{t('Uphold')}</button>
          <button type="button" className="rpl-button rpl-button--primary" onClick={() => onAct(s, 'overturned')} disabled={mine}>{t('Overturn')}</button>
        </div>
      )}
    </li>
  );
}
