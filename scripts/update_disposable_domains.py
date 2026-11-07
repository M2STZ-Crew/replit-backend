"""Refresh app/data/disposable_email_domains.txt from the community list.

    python scripts/update_disposable_domains.py
    python scripts/update_disposable_domains.py --from-file blocklist.conf \\
        --commit <sha> --date 2026-11-04

The list is disposable_email_blocklist.conf from
https://github.com/disposable-email-domains/disposable-email-domains, CC0 1.0
Universal (public domain). Without --from-file the newest one is fetched from
GitHub, with the commit it came from. Every line has to be a lowercase domain
and there have to be thousands, or nothing is written: a cut-off download
must not quietly let burner addresses through. It says what changed, and any
domain RepLiT never refuses (ALWAYS_ALLOWED) that the list has picked up;
those stay allowed whatever the list says.

Review the change and commit it; the backend reads the file at start.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.disposable_email import ALWAYS_ALLOWED, LIST_PATH  # noqa: E402

REPO = "disposable-email-domains/disposable-email-domains"
RAW = f"https://raw.githubusercontent.com/{REPO}/{{ref}}/disposable_email_blocklist.conf"
COMMITS = f"https://api.github.com/repos/{REPO}/commits/main"
DOMAIN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
AT_LEAST = 5000


def _get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "replit-backend list refresh"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return bytes(response.read())


def render(domains: list[str], commit: str, date: str) -> str:
    """The data file: a header saying where it came from, then the domains."""
    header = [
        "# Disposable (burner) email domains, one per line, refused by",
        "# app/services/disposable_email.py together with their subdomains.",
        "#",
        f"# Source: https://github.com/{REPO}",
        f"#   disposable_email_blocklist.conf at {commit}",
        f"#   ({date}), {len(domains):,} domains. CC0 1.0 Universal: public domain.",
        "# Refresh: python scripts/update_disposable_domains.py",
    ]
    return "\n".join([*header, *domains]) + "\n"


def parse(text: str) -> list[str]:
    """The domains of a blocklist, checked, sorted, without duplicates."""
    domains = {line.strip().lower() for line in text.splitlines() if line.strip()}
    domains = {d for d in domains if not d.startswith("#")}
    bad = sorted(d for d in domains if not DOMAIN.match(d))
    if bad:
        raise SystemExit(f"Not domains: {', '.join(bad[:10])}")
    if len(domains) < AT_LEAST:
        raise SystemExit(f"Only {len(domains)} domains: a cut-off download? Nothing written.")
    return sorted(domains)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from-file", type=Path, help="a blocklist already downloaded")
    parser.add_argument("--commit", help="the upstream commit it came from")
    parser.add_argument("--date", help="that commit's date, YYYY-MM-DD")
    args = parser.parse_args()

    if args.from_file:
        if not (args.commit and args.date):
            raise SystemExit("--from-file needs --commit and --date.")
        text = args.from_file.read_text(encoding="utf-8")
        commit, date = args.commit, args.date
    else:
        latest = json.loads(_get(COMMITS))
        commit = str(latest["sha"])
        date = str(latest["commit"]["committer"]["date"])[:10]
        text = _get(RAW.format(ref=commit)).decode("utf-8")

    domains = parse(text)
    before: set[str] = set()
    if LIST_PATH.exists():
        before = {
            line.strip()
            for line in LIST_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
    LIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIST_PATH.write_text(render(domains, commit, date), encoding="utf-8", newline="\n")

    added, removed = set(domains) - before, before - set(domains)
    print(f"{len(domains):,} domains at {commit[:12]} ({date}): +{len(added)} -{len(removed)}")
    overlap = sorted(ALWAYS_ALLOWED & set(domains))
    if overlap:
        print(f"Listed but always allowed (unchanged): {', '.join(overlap)}")


if __name__ == "__main__":
    main()
