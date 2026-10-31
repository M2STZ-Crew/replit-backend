import { useCallback, useEffect, useId, useRef, useState } from 'react';

/* A photo, full screen, to look at closely: a report's scene photo, an ID and
 * its selfie. Zoom with the + and − buttons, the mouse wheel, a pinch, the +
 * / − / 0 keys, or a double click; when zoomed in, drag (or use the arrow
 * keys) to move around. Escape or Close returns to the page, and focus goes
 * back to the photo that opened it. */

const MIN = 1;
const MAX = 6;
const STEP = 1.25;

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

export default function ImageViewer({ src, alt, caption = null, onClose }) {
  const dialog = useRef(null);
  const stage = useRef(null);
  const titleId = useId();
  const [view, setView] = useState({ scale: 1, x: 0, y: 0 });
  const pointers = useRef(new Map());
  const pinch = useRef(null);

  // Opened over the page; on the way out, focus goes back to whatever opened
  // it (after close(), which would otherwise leave focus on the page body).
  useEffect(() => {
    const d = dialog.current;
    const opener = document.activeElement;
    d?.showModal();
    return () => {
      if (d?.open) d.close();
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);

  // Keep the picture over the stage: at 1× it is centred; zoomed in, it can
  // move only as far as its edges reach.
  const fitted = useCallback((scale, x, y) => {
    const s = clamp(scale, MIN, MAX);
    if (s === 1) return { scale: 1, x: 0, y: 0 };
    const box = stage.current?.getBoundingClientRect();
    const limitX = box ? (box.width * (s - 1)) / 2 : 0;
    const limitY = box ? (box.height * (s - 1)) / 2 : 0;
    return { scale: s, x: clamp(x, -limitX, limitX), y: clamp(y, -limitY, limitY) };
  }, []);

  /// Zoom to `next(scale)`, toward `focus` (a point on screen) when given, so
  /// what is under the cursor or between the fingers stays put.
  const zoomTo = useCallback((next, focus = null) => {
    setView((v) => {
      const target = clamp(next(v.scale), MIN, MAX);
      if (!focus || !stage.current) return fitted(target, v.x, v.y);
      const box = stage.current.getBoundingClientRect();
      const fx = focus.x - (box.left + box.width / 2);
      const fy = focus.y - (box.top + box.height / 2);
      const k = target / v.scale;
      return fitted(target, fx - (fx - v.x) * k, fy - (fy - v.y) * k);
    });
  }, [fitted]);

  const reset = () => setView({ scale: 1, x: 0, y: 0 });
  const move = (dx, dy) => setView((v) => fitted(v.scale, v.x + dx, v.y + dy));

  function onKeyDown(e) {
    if (e.key === '+' || e.key === '=') { e.preventDefault(); zoomTo((s) => s * STEP); }
    else if (e.key === '-' || e.key === '_') { e.preventDefault(); zoomTo((s) => s / STEP); }
    else if (e.key === '0') { e.preventDefault(); reset(); }
    else if (view.scale > 1 && e.key.startsWith('Arrow')) {
      e.preventDefault();
      const d = 60;
      move(e.key === 'ArrowLeft' ? d : e.key === 'ArrowRight' ? -d : 0, e.key === 'ArrowUp' ? d : e.key === 'ArrowDown' ? -d : 0);
    }
  }

  // Non-passive, so the page does not scroll behind the picture.
  useEffect(() => {
    const el = stage.current;
    if (!el) return undefined;
    const onWheel = (e) => {
      e.preventDefault();
      zoomTo((s) => (e.deltaY < 0 ? s * STEP : s / STEP), { x: e.clientX, y: e.clientY });
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [zoomTo]);

  function onPointerDown(e) {
    stage.current?.setPointerCapture?.(e.pointerId);
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      pinch.current = { distance: Math.hypot(a.x - b.x, a.y - b.y) || 1, scale: view.scale };
    }
  }

  function onPointerMove(e) {
    const last = pointers.current.get(e.pointerId);
    if (!last) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.current.size === 2 && pinch.current) {
      const [a, b] = [...pointers.current.values()];
      const target = pinch.current.scale * (Math.hypot(a.x - b.x, a.y - b.y) / pinch.current.distance);
      zoomTo(() => target, { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
    } else if (pointers.current.size === 1 && view.scale > 1) {
      move(e.clientX - last.x, e.clientY - last.y);
    }
  }

  function onPointerUp(e) {
    pointers.current.delete(e.pointerId);
    if (pointers.current.size < 2) pinch.current = null;
  }

  return (
    <dialog
      ref={dialog}
      className="rpl-viewer"
      aria-labelledby={titleId}
      onCancel={(e) => { e.preventDefault(); onClose(); }}
      onKeyDown={onKeyDown}
    >
      <header className="rpl-viewer-bar">
        <p className="rpl-viewer-title" id={titleId}>{caption || alt}</p>
        <div className="rpl-viewer-tools" role="group" aria-label="Zoom">
          <button type="button" className="rpl-viewer-button" onClick={() => zoomTo((s) => s / STEP)} disabled={view.scale <= MIN} aria-label="Zoom out">−</button>
          <button type="button" className="rpl-viewer-level" onClick={reset} aria-label={`Zoom ${Math.round(view.scale * 100)} percent. Reset to fit`}>
            {Math.round(view.scale * 100)}%
          </button>
          <button type="button" className="rpl-viewer-button" onClick={() => zoomTo((s) => s * STEP)} disabled={view.scale >= MAX} aria-label="Zoom in">+</button>
        </div>
        <button type="button" className="rpl-button rpl-button--secondary rpl-button--compact" onClick={onClose} autoFocus>Close</button>
      </header>
      <div
        ref={stage}
        className={`rpl-viewer-stage${view.scale > 1 ? ' is-zoomed' : ''}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onDoubleClick={(e) => (view.scale > 1 ? reset() : zoomTo(() => 2.5, { x: e.clientX, y: e.clientY }))}
      >
        <img
          className="rpl-viewer-image"
          src={src}
          alt={alt}
          draggable={false}
          style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}
        />
      </div>
      <p className="rpl-viewer-hint">Scroll, pinch or use + and − to zoom. Drag to move around. Double-click to zoom in, or back out.</p>
    </dialog>
  );
}
