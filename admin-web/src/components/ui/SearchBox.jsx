import { useId, useRef } from 'react';

import Icon from './Icon.jsx';
import { t } from '../../i18n/i18n.jsx';

/* The console's one search box (v1.12.48; 22 Nov 2026: "Kapag pinindot yung
 * Search ang weird ng Design niya parang naka Default"): one ring around the
 * whole box, and our own Clear in place of the browser's. */
export default function SearchBox({ label, placeholder, value, onChange }) {
  const id = useId();
  const input = useRef(null);
  return (
    <div className="rpl-search" onClick={() => input.current?.focus()}>
      <Icon name="search" />
      <label className="web-sr-only" htmlFor={id}>{label}</label>
      <input
        id={id}
        ref={input}
        type="search"
        autoComplete="off"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
      {value && (
        <button type="button" className="rpl-search-clear" onClick={() => onChange('')} aria-label={t('Clear search')}>
          <span aria-hidden="true">✕</span>
        </button>
      )}
    </div>
  );
}
