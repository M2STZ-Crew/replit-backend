/* The console's on/off switch (REPLIT (MAIN) 10 · A70), in Settings and the
 * header's quick settings. `label` is its name to a screen reader. */
export default function Switch({ checked, onChange, label, disabled = false }) {
  return (
    <label className={`rpl-switch${disabled ? ' is-disabled' : ''}`}>
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="rpl-switch-track" aria-hidden="true" />
      <span className="web-sr-only">{label}</span>
    </label>
  );
}
