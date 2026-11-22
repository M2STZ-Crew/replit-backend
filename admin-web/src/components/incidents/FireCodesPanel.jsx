import { useEffect, useState } from 'react';

import { api } from '../../api/client.js';
import { fireAt } from '../../lib/place.js';
import { ConfirmDialog } from '../ui/index.js';
import { t } from '../../i18n/i18n.jsx';

/* Fire codes from the console (v1.12.46; 20 Nov 2026: "there's a logical flaw
 * in the fire code in coordinator to admin and vice versa ... if they press
 * the fire code, there's nothing happening"). Answered: "Show it and alert",
 * "By what the code asks", and Admins press on the incident page too.
 *
 * Fire Volunteer, BFP, central-hub and system Admins (`codes.press`) press a
 * code on this live incident; it goes on the incident's timeline here and in
 * the app at once, and alerts whoever the code is for: FC-6 water, the fire
 * service's coordinators; FC-7 more units, every agency on the fire; FC-8 a
 * casualty, medical and the hub; FC-1 to FC-5, the crews and coordinators,
 * quietly. Pressing never changes the incident's status.
 *
 * v1.12.49: FC-2 from here declares the fire under control, so it is open
 * only on an incident routed to this Admin (`declares`), as the server has it. */

// The codes that ask for help ring on phones; the rest only vibrate.
const ASKS = ['FC-6', 'FC-7', 'FC-8'];
const DECLARES = 'FC-2';

export default function FireCodesPanel({ d, declares = true, onPressed }) {
  const [codes, setCodes] = useState(null);
  const [error, setError] = useState(null);
  const [pressing, setPressing] = useState(null);
  const [done, setDone] = useState(null);

  useEffect(() => {
    let alive = true;
    api.fireCodes()
      .then((rows) => {
        if (!alive) return;
        const list = (Array.isArray(rows) ? rows : [])
          .filter((c) => c.is_active !== false)
          .sort((a, b) => (a.display_order ?? 0) - (b.display_order ?? 0));
        setCodes(list);
      })
      .catch((e) => { if (alive) setError(e.message || t('Could not load the fire codes.')); });
    return () => { alive = false; };
  }, []);

  async function press() {
    const code = pressing;
    await api.pressFireCode(code.id, d.id);
    setPressing(null);
    setDone(t('{code} recorded on this incident. The people it is for were alerted.', { code: `${code.code_number} · ${code.name}` }));
    onPressed?.();
  }

  return (
    <section className="rpl-panel rpl-decision" aria-labelledby="rpl-codes-title">
      <div className="rpl-decision-head">
        <h2 className="rpl-decision-title" id="rpl-codes-title">{t('Fire codes')}</h2>
      </div>
      <p className="rpl-decision-body">
        {t('Press a code to record it on this incident and alert whoever it is for. It does not change the incident’s status.')}
      </p>
      {done && <p className="rpl-inline-note" role="status">{done}</p>}
      {error && <p className="rpl-inline-error" role="alert">{error}</p>}
      {codes && (
        <div className="rpl-code-grid">
          {codes.map((c) => (
            <button
              key={c.id}
              type="button"
              className={`rpl-code-button${ASKS.includes(c.code_number) ? ' is-ask' : ''}`}
              onClick={() => { setDone(null); setPressing(c); }}
              disabled={c.code_number === DECLARES && (!declares || d.status === 'reported')}
              title={c.code_number === DECLARES && (!declares || d.status === 'reported')
                ? t('Only on an acknowledged fire routed to your organization.')
                : c.description || c.name}
            >
              <span className="rpl-code-number">{c.code_number}</span>
              <span className="rpl-code-name">{c.name}</span>
            </button>
          ))}
        </div>
      )}
      <ConfirmDialog
        open={Boolean(pressing)}
        eyebrow={pressing ? pressing.code_number : ''}
        title={pressing ? t('Press {name} on {fire}?', { name: pressing.name, fire: fireAt(d.designation) }) : ''}
        description={pressing?.code_number === DECLARES
          ? t('This declares the fire under control: everyone, residents too, will see it. Its crews and coordinators are told quietly.')
          : pressing && ASKS.includes(pressing.code_number)
            ? t('It goes on the incident’s timeline everywhere, and the people it asks for are alerted with the fire alarm.')
            : t('It goes on the incident’s timeline everywhere, and its crews and coordinators are told quietly.')}
        confirmLabel={t('Press code')}
        onClose={() => setPressing(null)}
        onConfirm={press}
      />
    </section>
  );
}

/* The presses, for the incident's timeline: "FC-6 · Water Supply Needed",
 * "Ana Cruz · BFP Pasay". */
export function codeEntries(d) {
  return (d.fire_codes ?? []).map((c) => ({
    at: c.pressed_at,
    title: `${c.code_number} · ${c.name}`,
    sub: [c.pressed_by_name, c.pressed_by_org].filter(Boolean).join(' · ') || null,
    tone: ASKS.includes(c.code_number) ? 'live' : 'neutral',
  }));
}
