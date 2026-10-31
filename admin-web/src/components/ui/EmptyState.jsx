import Icon from './Icon.jsx';

/* An empty list (REPLIT (MAIN) 10 · A80; 04 · Empty state): what is not
 * here, in words that name it, and where it will appear or where else to
 * look — an invitation, not an apology. */
export default function EmptyState({ icon = 'requests', title, children }) {
  return (
    <section className="rpl-empty" aria-label={title}>
      <div className="rpl-empty-card">
        <span className="rpl-empty-icon" aria-hidden="true"><Icon name={icon} /></span>
        <h2 className="rpl-empty-title">{title}</h2>
        {children && <p className="rpl-empty-body">{children}</p>}
      </div>
    </section>
  );
}
