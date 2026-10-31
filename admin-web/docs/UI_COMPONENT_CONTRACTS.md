# Admin UI component contracts

The shared components every Admin console page is built from. They carry the
pass 6 styling (REPLIT (MAIN) 03–04 tokens and components) through `web-*` and
`rpl-*` classes in `src/index.css` and `src/styles/pass6*.css`. They add no API
calls; pages pass data and callbacks in.

Import from `src/components/ui/index.js`. The development fixture at
`/docs/foundations.html` on the Vite server shows them in both themes.

## Shared styling hooks

Every component uses `web-*` classes. Supply styles through the existing stylesheet
and its existing CSS variables; no inline color, size, spacing or shadow values
are introduced here. Tone names are presentation inputs: `neutral`, `accent`,
`danger`, `warn`, `ok`, and `info` are the intended shared vocabulary.

Provide the `web-sr-only` utility so hidden count descriptions remain available
to assistive technology without becoming duplicate visible text. Provide a
visible focus indicator for all `web-button` and table row-action buttons.
Use `web-dialog::backdrop` to style the native modal backdrop. The browser's
native dialog handles modal containment; do not override its display while
closed or replace its native open state using CSS.

## PageHeader

Props: `title` (required), `eyebrow`, `description`, `actions`,
`children`, `titleId`, `className`.

Renders a semantic header with one h1. Actions are caller-owned buttons/links;
children provide an optional filter or secondary content slot. Use only one
page-level h1 after removing the previous page heading during integration.

Hooks: `web-page-header`, `web-page-header-copy`, `web-eyebrow`,
`web-page-title`, `web-page-description`, `web-page-header-actions`,
`web-page-header-content`.

## StatusChip

Props: `label` (required), `tone` (default neutral), `className`.

Renders the supplied wording visibly. It does not accept or reinterpret a backend
status. The caller chooses both the label and tone without changing API values.

Hooks: `web-chip`, `web-chip--{tone}`.

## CountBadge

Props: `count`, `label` (string or function of full count), `max`
(default 99), `showZero` (default false), `tone` (default danger),
`className`.

Missing, invalid and negative counts render nothing. Counts above max show “99+”
(or the supplied limit), while the screen-reader description contains the full
count. Supply a useful label such as “7 incidents since your last visit”.
No live region is created, so polling counters do not repeatedly interrupt a
screen reader.

Hooks: `web-count-badge`, `web-count-badge--{tone}`, `web-sr-only`.

## ConfirmDialog

Controlled props: `open`, `title`, `onClose(reason)`, `onConfirm()`.
Pass a specific `confirmLabel` repeating the intended action verb; the generic
default is “Confirm”. Other props: `description`, `cancelLabel` (Cancel),
`busyDismissLabel` (Close), `busy`, `destructive`,
`closeOnBackdrop` (true), `initialFocus` (cancel or confirm), `children`,
`className`.

Behavior:
- Uses native dialog.showModal, native modal focus containment, labeled heading
  and optional description, with explicit forward/backward Tab wrapping.
- Opening saves the invoking element and focuses Cancel by default.
- Escape, Cancel/Close and a press/release on the outside backdrop close it and invoke onClose
  with escape, cancel or backdrop. The caller must set open=false.
- Programmatically setting open=false closes it without notifying onClose again.
- Focus returns to the connected invoking element on dismissal or unmount.
- Duplicate confirmation is blocked synchronously. A returned promise controls
  internal pending state; external busy also disables confirmation.
- Dismissal remains available while pending, and its button reads “Close”.
  Dismissing does not cancel a running request; callers must own operation state
  outside the dialog. Errors from a dismissed action do not appear in a later
  opening.
- A rejected confirmation promise shows its Error.message (or a generic fallback)
  in an alert. Successful confirmation does not auto-close: the caller decides
  when its existing mutation/refresh sequence has completed.
- Unmounting does not cancel an operation. Do not put a form with method=dialog
  inside children if it could bypass confirmation logic.

Example:

```jsx
<ConfirmDialog
  open={confirming}
  title={`Acknowledge ${incident.designation}?`}
  confirmLabel="Acknowledge"
  description="The incident will be acknowledged."
  onClose={() => setConfirming(false)}
  onConfirm={async () => {
    await existingAcknowledgeAction(incident.id);
    setConfirming(false);
  }}
/>
```

The wording above is illustrative, not Figma-approved copy. Local alarm
acknowledgement and incident lifecycle acknowledgement remain separate operations.

Hooks: `web-dialog`, `web-dialog-panel`, `web-dialog-header`,
`web-dialog-title`, `web-dialog-description`, `web-dialog-content`,
`web-dialog-error`, `web-dialog-actions`, `web-button`,
`web-button--secondary`, `web-button--primary`, `web-button--danger`.

## StatePanel

Props: `kind` (loading, empty, error, blocked; default empty), `title`,
`description`, `onRetry`, `retryLabel` (Try again), `busy`,
`children`, `className`.

Loading gets role=status; errors get role=alert. Empty and blocked states do not
interrupt the user. A supplied retry handler renders a disabled-while-busy button,
except during initial loading. “Blocked” describes unavailable capabilities; it
does not create a disabled mutation button or simulate backend data. Caller copy
and content should match the inspected design and actual capability.

Hooks: `web-state`, `web-state--{kind}`, `web-state-title`,
`web-state-description`, `web-state-content`, and shared button classes.

## EmptyState

Props: `icon` (an `/icons/*.svg` name; default `requests`), `title`, `children`.
An empty list (10 · A80): what is missing, in words that name it, and where it
will appear. It is not an error and never stands in for a failed load; use
`StatePanel kind="error"` for that.

## FormDialog

Props: `open`, `eyebrow`, `title`, `onClose`, `onSubmit`, `busy`, `error`,
`note`, `submitLabel`, `busyLabel`, `children`.

A native modal form (10 · A43, A49, A65): header with a close button, the
caller's fields, then a note beside Cancel and submit. Escape and Cancel close
it unless `busy`. The caller owns field state, validation and the call; a
caller shows a rejected call by passing `error`. Field markup: `rpl-field`,
`rpl-field-label`, `rpl-field-help`, `rpl-field-error`, `rpl-select`,
`rpl-form-row`, `rpl-choice`.

## Icon

Props: `name`, `size` (default 20), `label`.

Draws `/icons/{name}.svg` (Figma exports) as a CSS mask, so it takes
`currentColor`. Without `label` it is decorative (`aria-hidden`); with one it
is `role="img"`.

## Checks

Exercised in the console preview (`/docs/console-preview.html`): Tab and
Shift+Tab wrap inside dialogs, Escape closes them, focus returns to the opener,
duplicate submits are ignored while busy, and failed calls show their message.
