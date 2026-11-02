"""The one look of every RepLiT email (v1.12.19).

Each email used to be its own bare ``<div>``: a heading, a paragraph, an
orange button, no header and no footer, and the email-verification one had no
plain-text part at all. Every email is now built here from the same parts:

- a dark header with the app's mark and name, as the app's own ground;
- a white card with the heading, the message, one button with its link written
  out beneath it (for a client that will not draw the button), the facts that
  matter such as how long the link lasts, and a security note;
- a footer that says why the email was sent;

and each comes with the same words as plain text, so a text-only client loses
nothing.

Built for email clients, not browsers. Layout is tables with inline styles;
there are no web fonts, scripts, forms or background images; the button is a
padded link in a coloured cell, which Outlook draws too (square-cornered).
The one ``<style>`` block only adds to that: narrower padding on a phone, and
dark colours where a client asks for them (Apple Mail, iOS Mail, Outlook for
Mac). Clients that recolour on their own (Gmail, Outlook) get a light card
under a dark header, which survives their inversion. Colours are the reset
page's light set (``password_reset._PAGE``), the coral and ground of the app.

Every value a caller passes is escaped here, so a person's name or an
organisation's name can never add markup to an email.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from html import escape

# Served by the Admin console (admin-web/public/assets/logo-mark.png). With
# images blocked, its empty alt text leaves the wordmark beside it to read.
LOGO_URL = "https://replit-backend-5u9u.vercel.app/assets/logo-mark.png"

TAGLINE = "Pasay City's fire reporting and response network"

_FONT = "Inter,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_PAGE = "#F3F1EE"
_CARD = "#FFFFFF"
_EDGE = "#E4E0DA"
_GROUND = "#131313"
_CORAL = "#FF9066"
_HEADING = "#161616"
_BODY = "#333333"
_MUTED = "#5F5F5F"
# Coral as ink: on white, #A63A0A is what reads (6.5:1 under white text).
_ACTION = "#A63A0A"
_PANEL = "#FAF7F3"


@dataclass(frozen=True)
class EmailAction:
    """The one thing the email asks the reader to do."""

    label: str
    url: str


@dataclass(frozen=True)
class RenderedEmail:
    """An email's two bodies, for ``BrevoEmailClient.send(html=..., text=...)``."""

    html: str
    text: str


def render_email(
    *,
    preheader: str,
    heading: str,
    paragraphs: Sequence[str],
    reason: str,
    greeting: str | None = None,
    action: EmailAction | None = None,
    facts: Sequence[str] = (),
    notice: str | None = None,
) -> RenderedEmail:
    """Build an email. Every argument is plain text; this escapes it.

    ``preheader`` is the line an inbox shows after the subject. ``facts`` are
    short sentences set apart in a panel (how long a link lasts). ``notice`` is
    the security note. ``reason`` tells the reader why they got the email.
    """
    return RenderedEmail(
        html=_html(preheader, heading, greeting, paragraphs, action, facts, notice, reason),
        text=_text(heading, greeting, paragraphs, action, facts, notice, reason),
    )


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #
_STYLE = f"""
  body {{ margin:0; padding:0; width:100% !important;
         -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%; }}
  table {{ border-collapse:collapse; mso-table-lspace:0pt; mso-table-rspace:0pt; }}
  img {{ border:0; outline:none; text-decoration:none; -ms-interpolation-mode:bicubic; }}
  a {{ color:{_ACTION}; }}
  @media only screen and (max-width:620px) {{
    .rpl-outer {{ padding:12px 8px !important; }}
    .rpl-head {{ padding:18px 20px !important; }}
    .rpl-card {{ padding:28px 20px !important; }}
    .rpl-foot {{ padding:18px 20px 8px !important; }}
    .rpl-h1 {{ font-size:22px !important; line-height:28px !important; }}
  }}
  @media (prefers-color-scheme: dark) {{
    .rpl-page {{ background:#131313 !important; }}
    .rpl-card {{ background:#1C1C1C !important; border-color:#333333 !important; }}
    .rpl-panel {{ background:#262626 !important; border-color:#333333 !important; }}
    .rpl-h1 {{ color:#F3F3F3 !important; }}
    .rpl-text {{ color:#E2E2E2 !important; }}
    .rpl-muted {{ color:#A8A8A8 !important; }}
    .rpl-link {{ color:#FF9066 !important; }}
  }}
"""


def _p(
    text: str,
    *,
    size: int = 16,
    line: int = 24,
    color: str = _BODY,
    css_class: str = "rpl-text",
    bottom: int = 16,
) -> str:
    return (
        f'<p class="{css_class}" style="margin:0 0 {bottom}px;font-family:{_FONT};'
        f'font-size:{size}px;line-height:{line}px;color:{color};">{text}</p>'
    )


def _button(action: EmailAction) -> str:
    url, label = escape(action.url), escape(action.label)
    return (
        '<table role="presentation" cellspacing="0" cellpadding="0" border="0" '
        'style="margin:8px 0 20px;">'
        f'<tr><td align="center" bgcolor="{_ACTION}" style="border-radius:8px;">'
        f'<a href="{url}" target="_blank" rel="noopener" style="display:inline-block;'
        f"padding:14px 28px;font-family:{_FONT};font-size:16px;line-height:20px;"
        f'font-weight:700;color:#FFFFFF;text-decoration:none;border-radius:8px;">'
        f"{label}</a></td></tr></table>"
        + _p(
            "If the button does not work, copy this link into your browser:",
            size=13,
            line=20,
            color=_MUTED,
            css_class="rpl-muted",
            bottom=4,
        )
        + f'<p style="margin:0 0 20px;font-family:{_FONT};font-size:13px;line-height:20px;'
        f'word-break:break-all;"><a class="rpl-link" href="{url}" target="_blank" '
        f'rel="noopener" style="color:{_ACTION};text-decoration:underline;">{url}</a></p>'
    )


def _panel(lines: Sequence[str], *, accent: str) -> str:
    rows = "".join(
        _p(escape(line), size=14, line=21, bottom=0 if i == len(lines) - 1 else 8)
        for i, line in enumerate(lines)
    )
    return (
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        'border="0" style="margin:0 0 16px;">'
        f'<tr><td class="rpl-panel" style="background:{_PANEL};border:1px solid {_EDGE};'
        f'border-left:4px solid {accent};border-radius:8px;padding:14px 16px;">'
        f"{rows}</td></tr></table>"
    )


def _html(
    preheader: str,
    heading: str,
    greeting: str | None,
    paragraphs: Sequence[str],
    action: EmailAction | None,
    facts: Sequence[str],
    notice: str | None,
    reason: str,
) -> str:
    body = ""
    if greeting:
        body += _p(escape(greeting))
    body += "".join(_p(escape(p)) for p in paragraphs)
    if action is not None:
        body += _button(action)
    if facts:
        body += _panel(facts, accent=_CORAL)
    if notice:
        body += _panel([notice], accent=_MUTED)

    # The preheader, then filler so the inbox preview stops there and does not
    # run on into the body.
    hidden = escape(preheader) + "&#8199;&#847;" * 60
    footer = _p(
        escape(reason), size=12, line=18, color=_MUTED, css_class="rpl-muted", bottom=8
    ) + _p(
        f"RepLiT, {escape(TAGLINE)}",
        size=12,
        line=18,
        color=_MUTED,
        css_class="rpl-muted",
        bottom=0,
    )
    table = 'role="presentation" cellspacing="0" cellpadding="0" border="0"'
    return f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<meta name="x-apple-disable-message-reformatting">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>{escape(heading)}</title>
<style>{_STYLE}</style>
</head>
<body class="rpl-page" style="margin:0;padding:0;background:{_PAGE};">
<div style="display:none;font-size:1px;line-height:1px;max-height:0;max-width:0;
 opacity:0;overflow:hidden;mso-hide:all;">{hidden}</div>
<table {table} class="rpl-page" width="100%" style="background:{_PAGE};">
<tr><td class="rpl-outer" align="center" style="padding:24px 12px;">
<!--[if mso]><table {table} width="600"><tr><td><![endif]-->
<table {table} width="100%" style="max-width:600px;">
<tr><td class="rpl-head"
 style="background:{_GROUND};border-radius:12px 12px 0 0;padding:20px 32px;">
<table {table}><tr>
<td style="padding-right:10px;vertical-align:middle;"><img src="{LOGO_URL}" width="36"
 height="36" alt="" style="display:block;width:36px;height:36px;"></td>
<td style="vertical-align:middle;font-family:{_FONT};font-size:20px;line-height:24px;
 font-weight:800;color:{_CORAL};">RepLiT</td>
</tr></table>
</td></tr>
<tr><td class="rpl-card" style="background:{_CARD};border:1px solid {_EDGE};border-top:0;
 border-radius:0 0 12px 12px;padding:36px 32px 24px;">
<h1 class="rpl-h1" style="margin:0 0 20px;font-family:{_FONT};font-size:24px;
 line-height:30px;font-weight:700;color:{_HEADING};">{escape(heading)}</h1>
{body}
</td></tr>
<tr><td class="rpl-foot" align="center" style="padding:20px 32px 8px;">
{footer}
</td></tr>
</table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr>
</table>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# Plain text
# --------------------------------------------------------------------------- #
def _text(
    heading: str,
    greeting: str | None,
    paragraphs: Sequence[str],
    action: EmailAction | None,
    facts: Sequence[str],
    notice: str | None,
    reason: str,
) -> str:
    parts = ["RepLiT", heading]
    if greeting:
        parts.append(greeting)
    parts.extend(paragraphs)
    if action is not None:
        parts.append(f"{action.label}:\n{action.url}")
    parts.extend(facts)
    if notice:
        parts.append(notice)
    parts.append(f"--\n{reason}\nRepLiT, {TAGLINE}")
    return "\n\n".join(parts) + "\n"
