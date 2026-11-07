"""The small page an emailed link lands on.

A link in an email opens in the phone's browser, or in Gmail's own: what it
shows has to read well on a phone, in light and dark, and never be raw JSON.
Used by the staff links (routes/staff_email.py) and a resident's email
confirmation (routes/verification.py).
"""

from __future__ import annotations

import html

from fastapi.responses import HTMLResponse


def link_page(title: str, heading: str, message: str, *, status_code: int = 200) -> HTMLResponse:
    """A one-card page: ``heading`` over ``message``. Not cached, no referrer:
    the URL that opened it carries a token."""
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
</style>
</head>
<body><main><h1>{html.escape(heading)}</h1><p>{html.escape(message)}</p></main></body>
</html>"""
    return HTMLResponse(body, status_code=status_code, headers={"Cache-Control": "no-store"})
