"""The small page an emailed link lands on.

A link in an email opens in the phone's browser, or in Gmail's own: what it
shows has to read well on a phone, in light and dark, and never be raw JSON.
Used by the staff links (routes/staff_email.py) and a resident's email
confirmation (routes/verification.py).
"""

from __future__ import annotations

import html

from fastapi.responses import HTMLResponse

# The app answers links in this scheme (AndroidManifest.xml's intent filter,
# Info.plist's CFBundleURLTypes; app v1.12.34). "replit" itself belongs to
# another company's app, so the scheme is the product's full name.
APP_SCHEME = "reportwhatslit"


def open_app_href(user_agent: str | None, path: str = "email-confirmed") -> str:
    """A link that opens the RepLiT app from a phone's browser.

    Android's Chrome, and the Gmail app's browser built on it, open an app
    through an ``intent:`` link; without a package it does nothing when the app
    is not installed, rather than sending the person to a store RepLiT is not
    in. iPhones take the scheme as it is, and Safari asks before opening.
    """
    if "android" in (user_agent or "").lower():
        return f"intent://{path}#Intent;scheme={APP_SCHEME};end"
    return f"{APP_SCHEME}://{path}"


def link_page(
    title: str,
    heading: str,
    message: str,
    *,
    status_code: int = 200,
    action: tuple[str, str] | None = None,
) -> HTMLResponse:
    """A one-card page: ``heading`` over ``message``, and a button when
    ``action`` is (label, href) — "Open RepLiT" after an email is confirmed.
    Not cached, no referrer: the URL that opened it carries a token."""
    button = ""
    if action is not None:
        label, href = action
        button = (
            f'<a class="action" href="{html.escape(href, quote=True)}">'
            f"{html.escape(label)}</a>"
        )
    body = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>{html.escape(title)} · RepLiT</title>
<style>
  :root {{ --bg:#131313; --card:#1c1c1c; --line:#333; --text:#f4f4f4; --muted:#a8a8a8; }}
  @media (prefers-color-scheme: light) {{
    :root {{ --bg:#f3f1ee; --card:#fff; --line:#ddd; --text:#161616; --muted:#5f5f5f; }}
  }}
  body {{ margin:0; min-height:100vh; display:grid; place-items:center; padding:24px 16px;
         background:var(--bg); color:var(--text);
         font:16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; }}
  main {{ width:100%; max-width:400px; background:var(--card); border:1px solid var(--line);
         border-radius:16px; padding:28px 24px; box-sizing:border-box; }}
  h1 {{ font-size:22px; margin:0 0 12px; }}
  p {{ margin:0; color:var(--muted); }}
  .action {{ display:block; margin-top:24px; padding:16px; border-radius:12px; text-align:center;
            background:linear-gradient(#ff9066, #ff7943); color:#581a00; text-decoration:none;
            font-weight:900; font-size:15px; letter-spacing:1px; text-transform:uppercase; }}
  .action:focus-visible {{ outline:2px solid #ff9066; outline-offset:3px; }}
</style>
</head>
<body><main><h1>{html.escape(heading)}</h1><p>{html.escape(message)}</p>{button}</main></body>
</html>"""
    return HTMLResponse(body, status_code=status_code, headers={"Cache-Control": "no-store"})
