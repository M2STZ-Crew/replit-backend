import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';

import { t } from '../../i18n/i18n.jsx';

/* The console's one dropdown (v1.12.50; 22 Nov 2026: "kapag pinindot yung
 * filter tapos lumabas na yung mga choices default design yung lumalabas";
 * answered "Custom, every page": works with a keyboard, screen readers and
 * touch).
 *
 * A select-only combobox (WAI-ARIA APG): focus stays on the field and
 * aria-activedescendant moves through the choices. Arrows, Home, End, Page Up
 * and Down, typing a choice's first letters, Enter, Space and Escape work as
 * in the browser's own. The list is in the top layer (popover), so no dialog,
 * table or map clips it.
 *
 * `options`: [{ key, label, count?, disabled? }]. `variant`: 'filter' says its
 * label inside the box; 'field' is a form's field, with the label above and
 * `error` or `help` below. */

const ROOM = 8; // clear of the window's edge
const TALLEST = 352; // eight choices
const SMALLEST = 88; // two choices
const PAGE = 8;
const TYPING_MS = 600;

function firstEnabled(options, from, step) {
  for (let i = from; i >= 0 && i < options.length; i += step) {
    if (!options[i].disabled) return i;
  }
  return -1;
}

export default function Select({
  label,
  value,
  onChange,
  options,
  variant = 'filter',
  placeholder,
  error = null,
  help = null,
  disabled = false,
  className = '',
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const trigger = useRef(null);
  const list = useRef(null);
  const typed = useRef({ text: '', at: 0 });

  const field = variant === 'field';
  const at = options.findIndex((o) => o.key === value);
  const chosen = options[at];
  const optionId = (i) => `${id}-option-${i}`;

  function show(index = at) {
    if (disabled || !options.length) return;
    setActive(index >= 0 && !options[index].disabled ? index : firstEnabled(options, 0, 1));
    setOpen(true);
  }

  function hide() {
    setOpen(false);
  }

  function pick(index) {
    const option = options[index];
    if (!option || option.disabled) return;
    setOpen(false);
    if (option.key !== value) onChange(option.key);
  }

  function move(to, step) {
    const inside = Math.min(options.length - 1, Math.max(0, to));
    let next = firstEnabled(options, inside, step);
    if (next < 0) next = firstEnabled(options, inside, -step);
    if (next >= 0) setActive(next);
  }

  // The first letters typed; the same letter again steps through its choices.
  function typeTo(char) {
    const now = Date.now();
    const kept = now - typed.current.at < TYPING_MS ? typed.current.text : '';
    const text = kept + char.toLowerCase();
    typed.current = { text, at: now };
    const repeated = [...text].every((c) => c === text[0]);
    const term = repeated ? text[0] : text;
    const base = Math.max(0, open ? active : at);
    const start = repeated ? base + 1 : base;
    for (let n = 0; n < options.length; n += 1) {
      const i = (start + n) % options.length;
      if (!options[i].disabled && String(options[i].label).toLowerCase().startsWith(term)) {
        if (open) setActive(i);
        else show(i);
        return;
      }
    }
  }

  function onKeyDown(event) {
    const { key } = event;
    if (disabled || event.ctrlKey || event.metaKey) return;
    const typing = key.length === 1 && !event.altKey
      && (key !== ' ' || (Date.now() - typed.current.at < TYPING_MS && typed.current.text !== ''));
    if (typing) {
      event.preventDefault();
      typeTo(key);
      return;
    }
    if (!open) {
      if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(key)) {
        event.preventDefault();
        show();
      } else if (key === 'Home' || key === 'End') {
        event.preventDefault();
        show(key === 'Home' ? firstEnabled(options, 0, 1) : firstEnabled(options, options.length - 1, -1));
      }
      return;
    }
    if (key === 'Tab') {
      pick(active);
      hide();
      return;
    }
    const act = {
      ArrowDown: () => move(active + 1, 1),
      ArrowUp: () => (event.altKey ? pick(active) : move(active - 1, -1)),
      Home: () => move(0, 1),
      End: () => move(options.length - 1, -1),
      PageDown: () => move(active + PAGE, -1),
      PageUp: () => move(active - PAGE, 1),
      Enter: () => pick(active),
      ' ': () => pick(active),
      Escape: hide,
    }[key];
    if (!act) return;
    // Escape closes the list alone, not the dialog it is in.
    event.preventDefault();
    event.stopPropagation();
    act();
  }

  // Under the field, or over it without the room; it follows a scroll.
  useLayoutEffect(() => {
    if (!open) return undefined;
    const box = trigger.current;
    const menu = list.current;
    if (!box || !menu) return undefined;
    try {
      if (menu.showPopover && !menu.matches(':popover-open')) menu.showPopover();
    } catch {
      /* no popovers here: it is drawn fixed in place */
    }
    const place = () => {
      const r = box.getBoundingClientRect();
      const width = document.documentElement.clientWidth;
      const height = window.innerHeight;
      if (r.bottom < 0 || r.top > height) {
        setOpen(false);
        return;
      }
      const below = height - r.bottom - ROOM - 4;
      const above = r.top - ROOM - 4;
      const wanted = Math.min(TALLEST, menu.scrollHeight + 2);
      const up = below < wanted && above > below;
      menu.style.minWidth = `${Math.min(r.width, width - 2 * ROOM)}px`;
      menu.style.maxHeight = `${Math.max(SMALLEST, Math.min(TALLEST, up ? above : below))}px`;
      menu.style.left = `${Math.max(ROOM, Math.min(r.left, width - menu.offsetWidth - ROOM))}px`;
      menu.style.top = up ? 'auto' : `${r.bottom + 4}px`;
      menu.style.bottom = up ? `${height - r.top + 4}px` : 'auto';
    };
    place();
    const follow = (event) => {
      if (event.target !== menu) place();
    };
    window.addEventListener('resize', place);
    document.addEventListener('scroll', follow, true);
    return () => {
      window.removeEventListener('resize', place);
      document.removeEventListener('scroll', follow, true);
    };
  }, [open, options]);

  useEffect(() => {
    if (!open) return;
    list.current?.children[active]?.scrollIntoView({ block: 'nearest' });
  }, [open, active]);

  // A press anywhere else closes it (Safari does not move focus for one).
  useEffect(() => {
    if (!open) return undefined;
    const away = (event) => {
      if (trigger.current?.contains(event.target) || list.current?.contains(event.target)) return;
      setOpen(false);
    };
    document.addEventListener('pointerdown', away, true);
    return () => document.removeEventListener('pointerdown', away, true);
  }, [open]);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  const labelId = `${id}-label`;
  const noteId = `${id}-note`;
  const box = (
    <button
      ref={trigger}
      type="button"
      role="combobox"
      className={`rpl-pick rpl-pick--${variant}${open ? ' is-open' : ''}${field ? '' : ` ${className}`}`.trim()}
      aria-label={field ? undefined : label}
      aria-labelledby={field ? labelId : undefined}
      aria-describedby={field && (error || help) ? noteId : undefined}
      aria-haspopup="listbox"
      aria-expanded={open}
      aria-controls={open ? `${id}-list` : undefined}
      aria-activedescendant={open && active >= 0 ? optionId(active) : undefined}
      aria-invalid={error ? true : undefined}
      disabled={disabled}
      onClick={(event) => {
        event.currentTarget.focus();
        if (open) hide();
        else show();
      }}
      onKeyDown={onKeyDown}
      // Space has acted on the way down; let go, it would press the button again.
      onKeyUp={(event) => { if (event.key === ' ') event.preventDefault(); }}
      onBlur={hide}
    >
      {!field && <span className="rpl-pick-label" aria-hidden="true">{label}</span>}
      <span className={`rpl-pick-value${chosen ? '' : ' is-empty'}`}>
        {chosen?.label ?? placeholder ?? t('Choose…')}
      </span>
      <span className="rpl-pick-chevron" aria-hidden="true" />
    </button>
  );

  const menu = open && (
    <ul
      ref={list}
      id={`${id}-list`}
      popover="manual"
      role="listbox"
      className="rpl-pick-list"
      aria-label={label}
      // Focus stays on the field.
      onMouseDown={(event) => event.preventDefault()}
    >
      {options.map((option, i) => (
        <li
          key={String(option.key)}
          id={optionId(i)}
          role="option"
          aria-selected={option.key === value}
          aria-disabled={option.disabled || undefined}
          className={`rpl-pick-option${i === active ? ' is-active' : ''}`}
          onPointerMove={() => { if (i !== active && !option.disabled) setActive(i); }}
          onClick={() => pick(i)}
        >
          <span className="rpl-pick-check" aria-hidden="true" />
          <span className="rpl-pick-text">{option.label}</span>
          {option.count != null && <span className="rpl-pick-count">{option.count}</span>}
        </li>
      ))}
    </ul>
  );

  if (!field) {
    return (
      <>
        {box}
        {menu}
      </>
    );
  }
  return (
    <div className={`rpl-field ${className}`.trim()}>
      <span className="rpl-field-label" id={labelId} onClick={() => trigger.current?.focus()}>{label}</span>
      {box}
      {error
        ? <span className="rpl-field-error" id={noteId}>{error}</span>
        : help && <span className="rpl-field-help" id={noteId}>{help}</span>}
      {menu}
    </div>
  );
}
