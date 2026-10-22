export default function CountBadge({
  count,
  label,
  max = 99,
  showZero = false,
  tone = 'danger',
  className = '',
}) {
  if (count === null || count === undefined) return null;
  const value = Number(count);
  if (!Number.isFinite(value) || value < 0) return null;
  const total = Math.floor(value);
  if (!showZero && total === 0) return null;
  const limit = Number.isFinite(max) && max >= 1 ? Math.floor(max) : 99;
  const text = total > limit ? `${limit}+` : total;
  const accessibleLabel = typeof label === 'function'
    ? label(total)
    : (label || `${total} items`);

  return (
    <span className={`web-count-badge web-count-badge--${tone} ${className}`.trim()}>
      <span aria-hidden="true">{text}</span>
      <span className="web-sr-only">{accessibleLabel}</span>
    </span>
  );
}
