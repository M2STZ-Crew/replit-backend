import { useId } from 'react';

import Skeleton from './Skeleton.jsx';

const TITLES = {
  loading: 'Loading…',
  empty: 'Nothing here yet',
  error: 'Could not load this view',
  blocked: 'Not available yet',
};

/* A loading panel draws a skeleton in the shape of what is coming
 * (`skeleton`: 'table', 'cards', 'detail' or 'lines'; `rows`), with the title
 * kept as the status line a screen reader announces. */
export default function StatePanel({
  kind = 'empty',
  skeleton = 'table',
  rows,
  title,
  description,
  onRetry,
  retryLabel = 'Try again',
  busy = false,
  children,
  className = '',
}) {
  const titleId = useId();
  const loading = kind === 'loading';

  return (
    <section className={`web-state web-state--${kind} ${className}`.trim()}
             aria-labelledby={titleId}
             aria-busy={busy || undefined}
             role={kind === 'error' ? 'alert' : (loading ? 'status' : undefined)}>
      <h2 className="web-state-title" id={titleId}>{title || TITLES[kind] || TITLES.empty}</h2>
      {description && <p className="web-state-description">{description}</p>}
      {loading && <Skeleton shape={skeleton} rows={rows ?? (skeleton === 'lines' ? 5 : 6)} />}
      {children && <div className="web-state-content">{children}</div>}
      {onRetry && !loading && (
        <button type="button" className="web-button web-button--secondary"
                onClick={onRetry} disabled={busy}>
          {retryLabel}
        </button>
      )}
    </section>
  );
}
