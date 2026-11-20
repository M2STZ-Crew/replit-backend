import { useEffect, useMemo, useState } from 'react';

import { useMedia } from '../../lib/useMedia.js';
import { t } from '../../i18n/i18n.jsx';

/* One pager for every list in the console (v1.12.47; 20 Nov 2026: "fix the
 * pagination bar in admin, it is a UI flaw"; answered "One pager
 * everywhere"). "Showing 11–20 of 134", then the first page, the pages around
 * this one and the last (1 … 4 5 6 … 14) rather than a button for every page,
 * then Rows per page (10, 25 or 50). On a narrow screen it wraps onto more
 * lines and keeps only this page between the first and last, so it never runs
 * off the side. */

export const PAGE_SIZES = [10, 25, 50];

/* The page numbers to show, 0-based, with null for a gap: the first and last
 * page, this page with `siblings` on each side, and a gap only where it hides
 * two pages or more (as Material UI's usePagination does). Always the same
 * number of items once there are more pages than fit. */
export function pageWindow(page, pages, siblings = 1) {
  if (pages <= 0) return [];
  const count = pages;
  const p = Math.min(Math.max(page, 0), count - 1) + 1; // 1-based inside
  const range = (a, b) => (b < a ? [] : Array.from({ length: b - a + 1 }, (_, i) => a + i));
  const start = Math.max(Math.min(p - siblings, count - siblings * 2 - 2), 3);
  const end = Math.min(Math.max(p + siblings, siblings * 2 + 3), count - 2);
  const items = [
    1,
    ...(start > 3 ? [null] : 2 < count - 1 ? [2] : []),
    ...range(start, end),
    ...(end < count - 2 ? [null] : count - 1 > 1 ? [count - 1] : []),
    ...(count > 1 ? [count] : []),
  ];
  return items.map((i) => (i == null ? null : i - 1));
}

const SIZE_STORE = 'replit.pageSize.';

function savedSize(key) {
  if (!key) return PAGE_SIZES[0];
  try {
    const n = Number(localStorage.getItem(SIZE_STORE + key));
    return PAGE_SIZES.includes(n) ? n : PAGE_SIZES[0];
  } catch {
    return PAGE_SIZES[0];
  }
}

function saveSize(key, n) {
  if (!key) return;
  try {
    localStorage.setItem(SIZE_STORE + key, String(n));
  } catch {
    /* blocked storage: the size holds for this visit */
  }
}

/* A list's page: the rows on it, and the pager's props. Back to the first page
 * when `reset` changes (a filter or a tab); a page that no longer exists
 * shows the last one. Rows per page is remembered per list (`key`). */
export function usePager(rows, { key, reset = [] } = {}) {
  const [pageSize, setPageSize] = useState(() => savedSize(key));
  const [page, setPage] = useState(0);
  const resetKey = JSON.stringify(reset);
  useEffect(() => { setPage(0); }, [resetKey]);
  const total = rows.length;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const current = Math.min(page, pages - 1);
  const shown = useMemo(
    () => rows.slice(current * pageSize, current * pageSize + pageSize),
    [rows, current, pageSize],
  );
  const changeSize = (n) => {
    // Keep the first row in view on its new page.
    setPage(Math.floor((current * pageSize) / n));
    setPageSize(n);
    saveSize(key, n);
  };
  return {
    shown,
    page: current,
    setPage,
    pager: { total, page: current, pageSize, onPage: setPage, onPageSize: changeSize },
  };
}

/* `compact`: in a narrow column (the map editor's list, a queue beside its
 * detail), only this page between the first and last, at any screen width. */
export default function Pager({ total, page, pageSize, onPage, onPageSize, label, compact = false }) {
  const phone = useMedia('(max-width: 479px)');
  const narrow = compact || phone;
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : page * pageSize + 1;
  const to = Math.min(total, (page + 1) * pageSize);
  return (
    <div className="rpl-pager">
      <span className="rpl-pager-range">
        {total === 0 ? t('Showing 0 of 0') : t('Showing {from}–{to} of {count}', { from, to, count: total })}
      </span>
      {pages > 1 && (
        <nav className="rpl-pager-pages" aria-label={label ?? t('Pages')}>
          <button type="button" className="rpl-page-button" onClick={() => onPage(page - 1)} disabled={page === 0} aria-label={t('Previous page')}>‹</button>
          {pageWindow(page, pages, narrow ? 0 : 1).map((i, k) => (i == null ? (
            <span key={`gap-${k}`} className="rpl-page-gap" aria-hidden="true">…</span>
          ) : (
            <button
              key={i}
              type="button"
              className={`rpl-page-button${i === page ? ' is-current' : ''}`}
              onClick={() => onPage(i)}
              aria-current={i === page ? 'page' : undefined}
              aria-label={t('Page {page}', { page: i + 1 })}
            >
              {i + 1}
            </button>
          )))}
          <button type="button" className="rpl-page-button" onClick={() => onPage(page + 1)} disabled={page >= pages - 1} aria-label={t('Next page')}>›</button>
        </nav>
      )}
      {onPageSize && total > PAGE_SIZES[0] && (
        <label className="rpl-select rpl-pager-size">
          <span className="rpl-select-label">{t('Rows per page')}</span>
          <select value={pageSize} onChange={(e) => onPageSize(Number(e.target.value))}>
            {PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
      )}
    </div>
  );
}
