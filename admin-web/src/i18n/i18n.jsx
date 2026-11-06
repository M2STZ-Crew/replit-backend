import {
  Fragment,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import { TAGALOG } from './tagalog.js';

/* The Admin console in English or in Tagalog at CEFR B1 (Tagalog everywhere,
 * 1.3), the same two languages as the app, with the same rule: the English
 * line is the key, and a line with no Tagalog yet stays English rather than
 * going blank.
 *
 * The choice belongs to the account (users.language, PUT /auth/me/language),
 * so it follows an Admin from browser to browser and to the app; this browser
 * also keeps it, so the sign-in page opens in it before anyone has signed in.
 *
 * t() reads the language of the moment. Switching remounts everything under
 * the provider, so every line is read again — the Settings switch is the only
 * place it changes, and a remount there costs nothing. Display labels kept at
 * module level are getters for the same reason (get label() { return t(…) }). */

const STORE = 'rpl-language';

function stored() {
  try {
    return localStorage.getItem(STORE) === 'tl' ? 'tl' : 'en';
  } catch {
    return 'en';
  }
}

let current = stored();

/** The line in the language of the moment, its {blanks} filled from [args]. */
export function t(en, args) {
  const text = current === 'tl' ? TAGALOG[en] ?? en : en;
  if (!args) return text;
  return text.replace(/\{(\w+)\}/g, (whole, name) =>
    name in args && args[name] != null ? String(args[name]) : whole,
  );
}

export const currentLanguage = () => current;

const LanguageContext = createContext({ language: 'en', setLanguage: () => {} });

/* [accountLanguage]: the signed-in account's choice, which wins when it
 * arrives (another browser may have changed it) — unless a language was
 * picked on the sign-in page just before, which is then saved to the account
 * instead. [onSave]: stores a choice on the account, or returns nothing when
 * no one is signed in; a failure there keeps the choice in this browser. */
export function LanguageProvider({ accountLanguage, onSave, children }) {
  const [language, setState] = useState(current);
  // Picked before signing in: the account takes it, rather than overruling it.
  const pickedSignedOut = useRef(false);

  const apply = useCallback((next) => {
    const lang = next === 'tl' ? 'tl' : 'en';
    current = lang;
    try {
      localStorage.setItem(STORE, lang);
    } catch {
      // Private mode: the choice lasts this visit, and the account keeps it.
    }
    document.documentElement.lang = lang;
    setState(lang);
  }, []);

  useEffect(() => {
    document.documentElement.lang = current;
  }, []);

  useEffect(() => {
    if (accountLanguage !== 'en' && accountLanguage !== 'tl') return;
    if (pickedSignedOut.current) {
      pickedSignedOut.current = false;
      if (accountLanguage !== current) Promise.resolve(onSave?.(current)).catch(() => {});
      return;
    }
    if (accountLanguage !== current) apply(accountLanguage);
  }, [accountLanguage, apply, onSave]);

  const setLanguage = useCallback(
    async (next) => {
      const lang = next === 'tl' ? 'tl' : 'en';
      apply(lang);
      const saving = onSave?.(lang);
      if (!saving) {
        pickedSignedOut.current = true;
        return;
      }
      try {
        await saving;
      } catch {
        // Kept in this browser; the account catches up the next time.
      }
    },
    [apply, onSave],
  );

  const value = useMemo(() => ({ language, setLanguage }), [language, setLanguage]);
  return (
    <LanguageContext.Provider value={value}>
      <Fragment key={language}>{children}</Fragment>
    </LanguageContext.Provider>
  );
}

export const useLanguage = () => useContext(LanguageContext);

/* "English | Tagalog": each name in its own language, so either reader finds
 * theirs, as in the app's onboarding. */
export function LanguageSwitch({ className = '' }) {
  const { language, setLanguage } = useLanguage();
  return (
    <div className={`rpl-segment ${className}`.trim()} role="radiogroup" aria-label="Language · Wika">
      {[
        ['en', 'English'],
        ['tl', 'Tagalog'],
      ].map(([code, name]) => (
        <button
          key={code}
          type="button"
          role="radio"
          aria-checked={language === code}
          className={`rpl-chip${language === code ? ' is-selected' : ''}`}
          onClick={() => setLanguage(code)}
        >
          {language === code && <span aria-hidden="true">✓</span>}
          {name}
        </button>
      ))}
    </div>
  );
}
