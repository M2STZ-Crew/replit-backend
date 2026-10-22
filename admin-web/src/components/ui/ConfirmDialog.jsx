import { useEffect, useId, useRef, useState } from 'react';

export default function ConfirmDialog({
  open,
  eyebrow,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  busyDismissLabel = 'Close',
  onConfirm,
  onClose,
  busy = false,
  destructive = false,
  closeOnBackdrop = true,
  initialFocus = 'cancel',
  children,
  className = '',
}) {
  const dialog = useRef(null);
  const cancelButton = useRef(null);
  const confirmButton = useRef(null);
  const opener = useRef(null);
  const closeReason = useRef('dismiss');
  const ignoredCloseEvents = useRef(0);
  const actionVersion = useRef(0);
  const closeCallback = useRef(onClose);
  closeCallback.current = onClose;
  const mounted = useRef(false);
  const confirming = useRef(false);
  const pressedBackdrop = useRef(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  const titleId = useId();
  const descriptionId = useId();
  const errorId = useId();
  const working = busy || pending;

  function restoreFocus() {
    const target = opener.current;
    opener.current = null;
    if (target?.isConnected && typeof target.focus === 'function') target.focus();
  }

  useEffect(() => {
    mounted.current = true;
    const node = dialog.current;
    return () => {
      mounted.current = false;
      actionVersion.current += 1;
      if (node?.open) {
        ignoredCloseEvents.current += 1;
        node.close();
      }
      restoreFocus();
    };
  }, []);

  useEffect(() => {
    const node = dialog.current;
    if (!node) return;
    if (open && !node.open) {
      actionVersion.current += 1;
      setError(null);
      opener.current = document.activeElement;
      closeReason.current = 'dismiss';
      node.showModal();
      const first = initialFocus === 'confirm' ? confirmButton.current : cancelButton.current;
      first?.focus();
    } else if (!open && node.open) {
      actionVersion.current += 1;
      ignoredCloseEvents.current += 1;
      node.close();
      restoreFocus();
    }
  }, [open, initialFocus]);

  function requestClose(reason) {
    if (!dialog.current?.open) return;
    actionVersion.current += 1;
    closeReason.current = reason;
    ignoredCloseEvents.current += 1;
    dialog.current.close(reason);
    restoreFocus();
    closeCallback.current?.(reason);
  }

  function handleClose() {
    if (ignoredCloseEvents.current > 0) {
      ignoredCloseEvents.current -= 1;
      return;
    }
    actionVersion.current += 1;
    restoreFocus();
    closeCallback.current?.(closeReason.current);
  }

  async function confirm() {
    if (busy || confirming.current || !onConfirm) return;
    const version = actionVersion.current;
    confirming.current = true;
    setPending(true);
    setError(null);
    try {
      await onConfirm();
    } catch (failure) {
      if (mounted.current && actionVersion.current === version) {
        setError(failure instanceof Error ? failure.message : 'Could not complete this action. Try again.');
      }
    } finally {
      confirming.current = false;
      if (mounted.current) setPending(false);
    }
  }

  function outsideDialog(event) {
    if (event.target !== event.currentTarget) return false;
    const bounds = event.currentTarget.getBoundingClientRect();
    return event.clientX < bounds.left || event.clientX > bounds.right
      || event.clientY < bounds.top || event.clientY > bounds.bottom;
  }

  function backdropClick(event) {
    if (closeOnBackdrop && pressedBackdrop.current && outsideDialog(event)) {
      requestClose('backdrop');
    }
    pressedBackdrop.current = false;
  }

  function containTab(event) {
    if (event.key !== 'Tab') return;
    const targets = Array.from(event.currentTarget.querySelectorAll(
      'button, a[href], input, select, textarea, [tabindex], [contenteditable="true"]',
    )).filter((node) => node.tabIndex >= 0 && !node.matches(':disabled') && node.getClientRects().length);
    const first = targets[0];
    const last = targets[targets.length - 1];
    if (!first) {
      event.preventDefault();
      return;
    }
    if (event.shiftKey && (document.activeElement === first || document.activeElement === event.currentTarget)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  const describedBy = [
    description ? descriptionId : null,
    error ? errorId : null,
  ].filter(Boolean).join(' ') || undefined;

  return (
    <dialog ref={dialog} className={`web-dialog ${className}`.trim()}
            aria-labelledby={titleId} aria-describedby={describedBy} aria-busy={working}
            onClose={handleClose}
            onCancel={(event) => {
              event.preventDefault();
              requestClose('escape');
            }}
            onPointerDown={(event) => { pressedBackdrop.current = outsideDialog(event); }}
            onPointerCancel={() => { pressedBackdrop.current = false; }}
            onKeyDown={containTab}
            onClick={backdropClick}>
      <div className="web-dialog-panel">
        <header className="web-dialog-header">
          {eyebrow && <p className="web-dialog-eyebrow">{eyebrow}</p>}
          <h2 className="web-dialog-title" id={titleId}>{title}</h2>
          {description && <p className="web-dialog-description" id={descriptionId}>{description}</p>}
        </header>
        {children && <div className="web-dialog-content">{children}</div>}
        {error && <p className="web-dialog-error" id={errorId} role="alert">{error}</p>}
        <footer className="web-dialog-actions">
          <button ref={cancelButton} type="button" className="web-button web-button--secondary"
                  onClick={() => requestClose('cancel')}>
            {working ? busyDismissLabel : cancelLabel}
          </button>
          <button ref={confirmButton} type="button"
                  className={`web-button web-button--${destructive ? 'danger' : 'primary'}`}
                  disabled={working || !onConfirm} onClick={confirm}>
            {confirmLabel}
          </button>
        </footer>
      </div>
    </dialog>
  );
}
