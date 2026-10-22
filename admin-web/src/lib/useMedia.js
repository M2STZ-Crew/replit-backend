import { useEffect, useState } from 'react';

/* The console's widths (REPLIT (MAIN) 10 · A83–A85): 1280 px and up has the
 * full sidebar and tables; 1024–1279 px has the 72 px rail and stacked
 * cards; under 900 px is the phone layout. */
export const RAIL_BELOW = '(max-width: 1279px)';
export const PHONE_BELOW = '(max-width: 899px)';

export function useMedia(query) {
  const [match, setMatch] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const list = window.matchMedia(query);
    const update = () => setMatch(list.matches);
    update();
    list.addEventListener('change', update);
    return () => list.removeEventListener('change', update);
  }, [query]);
  return match;
}
