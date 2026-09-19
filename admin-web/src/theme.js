/* Which ground the console draws on.
 *
 * The same choice the mobile app makes, made the same way: in the app, not
 * from the operating system. A coordinator working a night shift under
 * fluorescent lights wants the dark ground whatever their laptop is set to.
 *
 * Dark is the default — it is what the console was designed on. The choice is
 * kept in localStorage and applied to <html> before React mounts, so a reload
 * never flashes the wrong ground. */
const KEY = 'replit.theme';

export const THEMES = ['dark', 'light'];

export function storedTheme() {
  try {
    const saved = localStorage.getItem(KEY);
    return THEMES.includes(saved) ? saved : 'dark';
  } catch {
    return 'dark';
  }
}

export function applyTheme(theme) {
  const value = THEMES.includes(theme) ? theme : 'dark';
  document.documentElement.dataset.theme = value;
  document.documentElement.style.colorScheme = value;
  try {
    localStorage.setItem(KEY, value);
  } catch {
    /* Private window, or storage blocked: the choice still holds for now. */
  }
  return value;
}

/* Called once from main.jsx, before the first paint. */
export function initTheme() {
  return applyTheme(storedTheme());
}
