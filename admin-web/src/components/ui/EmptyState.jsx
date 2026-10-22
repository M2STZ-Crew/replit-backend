import Icon from './Icon.jsx';

/* An empty list (REPLIT (MAIN) 10 · A80; 04 · Empty state): what is not
 * here, in words that name it, and where it will appear or where else to
 * look — an invitation, not an apology. */
export default function EmptyState({ icon = 'requests', title, children }) {
  return (
    <section className="ad-empty" aria-label={title}>
      <div className="ad-empty-card">
        <span className="ad-empty-icon" aria-hidden="true"><Icon name={icon} /></span>
        <h2 className="ad-empty-title">{title}</h2>
        {children && <p className="ad-empty-body">{children}</p>}
      </div>
    </section>
  );
}
