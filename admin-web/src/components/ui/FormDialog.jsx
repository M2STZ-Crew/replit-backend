import { useEffect, useId, useRef } from 'react';

/* A modal form (REPLIT (MAIN) 10 · A43, A49, A65): an eyebrow and title with
 * a close button, the fields, then a note beside Cancel and the submit
 * button. Escape closes it unless it is working. The caller owns the
 * fields' state and validation; `onSubmit` runs on submit. */
export default function FormDialog({
  open,
  eyebrow,
  title,
  onClose,
  onSubmit,
  busy = false,
  error = null,
  note = null,
  submitLabel,
  busyLabel = 'Working…',
  children,
}) {
  const dialog = useRef(null);
  const titleId = useId();

  useEffect(() => {
    const d = dialog.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    else if (!open && d.open) d.close();
  }, [open]);

  return (
    <dialog
      ref={dialog}
      className="web-dialog ad-form-dialog"
      aria-labelledby={titleId}
      onCancel={(e) => { e.preventDefault(); if (!busy) onClose(); }}
    >
      <form
        className="web-dialog-panel"
        noValidate
        onSubmit={(e) => { e.preventDefault(); if (!busy) onSubmit(); }}
      >
        <header className="ad-form-dialog-head">
          <div>
            {eyebrow && <p className="web-dialog-eyebrow">{eyebrow}</p>}
            <h2 className="web-dialog-title" id={titleId}>{title}</h2>
          </div>
          <button type="button" className="ad-icon-button" onClick={onClose} aria-label="Close" disabled={busy}>
            <span aria-hidden="true">✕</span>
          </button>
        </header>

        {children}

        {error && <p className="web-dialog-error" role="alert">{error}</p>}

        <footer className="ad-form-dialog-foot">
          {note && <p className="ad-field-help">{note}</p>}
          <button type="button" className="web-button web-button--secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="web-button web-button--primary" disabled={busy}>
            {busy ? busyLabel : submitLabel}
          </button>
        </footer>
      </form>
    </dialog>
  );
}
