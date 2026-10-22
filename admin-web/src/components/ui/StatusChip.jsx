export default function StatusChip({ label, tone = 'neutral', className = '' }) {
  return (
    <span className={`web-chip web-chip--${tone} ${className}`.trim()}>
      {label}
    </span>
  );
}
