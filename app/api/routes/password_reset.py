"""Setting a password from an emailed link.

Two emails carry a Supabase recovery link: an approved affiliate's "set your
password" and the app's "Forgot password?". Supabase sends the person on to a
redirect URL with the session in the URL fragment. With no redirect given it
used the project's Site URL - the default http://localhost:3000 - so the link
opened a page that does not exist, and nothing anywhere let the person type a
password. This module is that page, and the call it makes.

GET  /auth/reset-password  the page: reads the fragment, drops it from the
                           address bar, asks for the new password.
POST /auth/reset-password  sets it, with the link's session.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.api.deps import AuthClientDep
from app.core.config import get_settings
from app.core.exceptions import AppError, BadRequestError
from app.core.logging import get_logger
from app.integrations.brevo_email import BrevoEmailClient
from app.integrations.supabase_auth import AuthError, SupabaseAuthClient
from app.schemas.common import MessageResponse

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

PAGE_PATH = "/auth/reset-password"


def reset_page_url() -> str:
    """Where a recovery link should land: this backend's own page."""
    return f"{get_settings().public_base_url.rstrip('/')}{PAGE_PATH}"


class PasswordResetRequest(BaseModel):
    """The session from the emailed link, and the password to set."""

    access_token: str = Field(min_length=20, max_length=4096)
    password: str = Field(min_length=8, max_length=128)


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    summary="Set a new password with the session from a recovery link",
)
async def reset_password(payload: PasswordResetRequest, auth: AuthClientDep) -> MessageResponse:
    """Set the password of the account the link was sent to."""
    try:
        user = await auth.update_user(
            access_token=payload.access_token, attributes={"password": payload.password}
        )
    except AuthError as exc:
        # 400: the page shows its "link expired" view.
        raise BadRequestError(
            "This link has expired or has already been used. Open the RepLiT app, "
            "tap Forgot password?, and use the new link we email you.",
            error_code="link_expired",
        ) from exc
    except BadRequestError as exc:
        # GoTrue refused the password itself (too weak, same as before): the link
        # is still good, so say why and let them try another.
        raise AppError(exc.message, status_code=422, error_code="password_rejected") from exc
    log.info("password_set_from_link")
    email = user.get("email") if isinstance(user, dict) else None
    who = f" for {email}" if email else ""
    return MessageResponse(
        message=f"Your password is set{who}. Open the RepLiT app and sign in with it."
    )


# --------------------------------------------------------------------------- #
# "Forgot password?" — sent through Brevo, landing on the page above
# --------------------------------------------------------------------------- #
# Supabase's built-in mailer only delivers to members of the project's team, so
# its own reset email never reached a resident. The link is generated here and
# sent like every other RepLiT email.
_RECOVER_COOLDOWN = timedelta(seconds=60)
_last_sent: dict[str, datetime] = {}


def _reset_email_html(link: str) -> str:
    return (
        '<div style="font-family:Inter,Arial,sans-serif;color:#111;max-width:520px">'
        "<h2 style='margin:0 0 12px'>Reset your RepLiT password</h2>"
        "<p>Someone asked to reset the password for this RepLiT account. If it was "
        "you, choose a new one here (the link works once, for one hour):</p>"
        f'<p><a href="{link}" style="display:inline-block;background:#EB4800;'
        'color:#fff;text-decoration:none;padding:12px 22px;border-radius:8px;'
        'font-weight:bold">Choose a new password</a></p>'
        '<p style="color:#666;font-size:13px">If you did not ask for this, ignore this '
        "email - your password stays as it is.</p>"
        "</div>"
    )


def _reset_email_text(link: str) -> str:
    return (
        "Reset your RepLiT password\n\n"
        "Someone asked to reset the password for this RepLiT account. If it was you, "
        f"choose a new one here (the link works once, for one hour):\n{link}\n\n"
        "If you did not ask for this, ignore this email.\n"
    )


async def send_reset_email(
    auth: SupabaseAuthClient, email_client: BrevoEmailClient, email: str
) -> None:
    """Email a recovery link. Silent on failure: an unknown address lands here too,
    and the caller must not learn which addresses have accounts."""
    try:
        resp = await auth.admin_generate_link(
            link_type="recovery", email=email, redirect_to=reset_page_url()
        )
        link = resp.get("action_link") or (resp.get("properties") or {}).get("action_link")
        if not isinstance(link, str) or not link:
            return
        await email_client.send(
            to=email,
            subject="Reset your RepLiT password",
            html=_reset_email_html(link),
            text=_reset_email_text(link),
        )
        log.info("password_reset_email_sent")
    except AppError:
        log.info("password_recover_failed_silently")


def schedule_reset_email(
    background: BackgroundTasks,
    auth: SupabaseAuthClient,
    email_client: BrevoEmailClient,
    email: str,
) -> None:
    """Queue a reset email after the response, at most one per address a minute."""
    key = email.strip().lower()
    now = datetime.now(UTC)
    last = _last_sent.get(key)
    if last is not None and now - last < _RECOVER_COOLDOWN:
        return
    _last_sent[key] = now
    for stale in [k for k, t in _last_sent.items() if now - t > _RECOVER_COOLDOWN]:
        del _last_sent[stale]
    background.add_task(send_reset_email, auth, email_client, key)


# --------------------------------------------------------------------------- #
# The page
# --------------------------------------------------------------------------- #
_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Set your password · RepLiT</title>
<style>
  :root { --bg:#131313; --card:#1c1c1c; --line:#333; --text:#f4f4f4; --muted:#a8a8a8;
          --accent:#ff9066; --accent-ink:#eb4800; --bad:#ff6b5e; --ok:#35c46a; }
  @media (prefers-color-scheme: light) {
    :root { --bg:#f3f1ee; --card:#fff; --line:#ddd; --text:#161616; --muted:#5f5f5f;
            --accent:#eb4800; --accent-ink:#a63a0a; --bad:#c62c1f; --ok:#1f7a45; }
  }
  * { box-sizing: border-box; }
  body { margin:0; min-height:100vh; display:grid; place-items:center; padding:24px 16px;
         background:var(--bg); color:var(--text);
         font:16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; }
  main { width:100%; max-width:400px; background:var(--card); border:1px solid var(--line);
         border-radius:16px; padding:28px 24px; }
  .brand { font-weight:800; letter-spacing:.14em; font-size:12px; color:var(--accent); }
  h1 { font-size:24px; line-height:1.2; margin:8px 0 8px; }
  p { margin:0 0 16px; color:var(--muted); }
  label { display:block; font-size:13px; font-weight:600; margin:14px 0 6px; }
  input { width:100%; padding:12px 14px; border-radius:10px; border:1px solid var(--line);
          background:transparent; color:var(--text); font-size:16px; }
  input:focus-visible, button:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
  button { width:100%; margin-top:20px; padding:13px; border:0; border-radius:10px;
           background:var(--accent-ink); color:#fff; font-weight:700; font-size:16px;
           cursor:pointer; }
  button[disabled] { opacity:.6; cursor:wait; }
  .msg { margin-top:14px; font-size:14px; min-height:1.5em; }
  .msg.bad { color:var(--bad); } .msg.ok { color:var(--ok); }
  [hidden] { display:none !important; }
</style>
</head>
<body>
<main>
  <div class="brand">REPLIT</div>

  <section id="form-view" hidden>
    <h1>Set your password</h1>
    <p>Choose the password you will sign in to the RepLiT app with.</p>
    <form id="form" novalidate>
      <label for="pw">New password</label>
      <input id="pw" type="password" autocomplete="new-password" minlength="8" required>
      <label for="pw2">Type it again</label>
      <input id="pw2" type="password" autocomplete="new-password" minlength="8" required>
      <button id="go" type="submit">Set password</button>
      <div id="msg" class="msg" role="status" aria-live="polite"></div>
    </form>
  </section>

  <section id="done-view" hidden>
    <h1>Password set</h1>
    <p id="done-text"></p>
    <p>You can close this page.</p>
  </section>

  <section id="dead-view" hidden>
    <h1>This link has expired</h1>
    <p id="dead-text">Reset links work once, for one hour. Open the RepLiT app, tap
      <strong>Forgot password?</strong>, and use the new link we email you.</p>
  </section>

  <section id="info-view" hidden>
    <h1>You're all set</h1>
    <p>Your email is confirmed. You can go back to the RepLiT app.</p>
  </section>
</main>
<script>
(function () {
  var loc = window.location;
  var raw = loc.hash ? loc.hash.slice(1) : loc.search.slice(1);
  var params = new URLSearchParams(raw);
  // The fragment holds a live session: keep it out of the address bar and history.
  if (window.location.hash || window.location.search) {
    history.replaceState(null, "", window.location.pathname);
  }
  var token = params.get("access_token");
  var type = params.get("type");
  var error = params.get("error_description");

  function show(id) {
    ["form-view", "done-view", "dead-view", "info-view"].forEach(function (v) {
      document.getElementById(v).hidden = v !== id;
    });
  }

  if (error || !token) { show("dead-view"); return; }
  if (type !== "recovery" && type !== "invite") { show("info-view"); return; }
  show("form-view");

  var form = document.getElementById("form");
  var msg = document.getElementById("msg");
  var go = document.getElementById("go");
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var pw = document.getElementById("pw").value;
    var pw2 = document.getElementById("pw2").value;
    msg.className = "msg bad";
    if (pw.length < 8) { msg.textContent = "Use at least 8 characters."; return; }
    if (pw !== pw2) { msg.textContent = "The two passwords do not match."; return; }
    go.disabled = true; msg.className = "msg"; msg.textContent = "Saving...";
    fetch("__POST_PATH__", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ access_token: token, password: pw })
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (body) {
        if (r.ok) {
          var done = body.message || "Your password is set.";
          document.getElementById("done-text").textContent = done;
          token = null;
          show("done-view");
          return;
        }
        if (r.status === 400) {
          document.getElementById("dead-text").textContent = body.message || "";
          show("dead-view");
          return;
        }
        go.disabled = false; msg.className = "msg bad";
        msg.textContent = (body && body.message) || "That did not work. Please try again.";
      });
    }).catch(function () {
      go.disabled = false; msg.className = "msg bad";
      msg.textContent = "Could not reach RepLiT. Check your connection and try again.";
    });
  });
})();
</script>
</body>
</html>
""".replace("__POST_PATH__", PAGE_PATH)


@router.get(
    "/reset-password",
    response_class=HTMLResponse,
    summary="Page a recovery link lands on: set a new password",
    include_in_schema=False,
)
async def reset_password_page() -> HTMLResponse:
    """Serve the set-password page (static; the session is read in the browser)."""
    return HTMLResponse(
        _PAGE,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
        },
    )
