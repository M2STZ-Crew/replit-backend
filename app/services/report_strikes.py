"""Prank and malicious reports: strikes, the reporting pause and appeals (v1.12.41).

19 Nov 2026: "a false alarm or prank report can be temporarily cannot report
and has a progressive penalty that if the user repeats pranking there's a
consequence"; "Yes, build it" to this ladder, counted over 12 months:

  1st  reporting paused 24 hours, and a lesson on what a false alarm costs
  2nd  paused 7 days, then 30 days of verify-first
  3rd  paused 30 days, then 90 days of verify-first    (a second staff member confirms)
  4th  reporting removed until an appeal is granted     (a second staff member confirms)

Only a report staff mark "Prank or malicious" gives a strike: never an honest
mistake (smoke from pagsisiga or ihaw-ihaw, a fire already out), and never a
neighbour who answered "Do you see it too?". Verify-first: their report does
not set off the 100 m neighbour alert until staff verify the fire. A serious
case (a truck sent out, a real household targeted) may go straight to the 3rd
step. While a 3rd or 4th step waits for its second check, the resident is
paused for 24 hours and on verify-first for up to 7 days. One appeal per strike
within 7 days, decided by someone other than whoever gave it; a 4th-step strike
may be appealed again once a year after its first 12 months.

Never blocked, at any step: calling 911, getting fire alerts, signing in. Only
sending a report (which is also how "Do you see it too?" is answered) pauses.

A strike follows the verified mobile number (an HMAC of it) as well as the
account, so a new account on the same number keeps it. Republic Act 9514 (the
Fire Code) §8(i) makes "giving false or malicious fire alarms" a prohibited
act; RepLiT fines no one. It stops the abuse quickly and keeps a record BFP or
the LGU can act on.

Every lookup here fails open on the paths a fire depends on (assert_may_report,
held_for_verification): a broken strike table must never stop a real report or
a neighbour's alert.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ReportingPausedError,
)
from app.core.logging import get_logger
from app.db.session import Database
from app.integrations.fcm import PushService, token_versions
from app.schemas.auth import AuthenticatedUser
from app.services.citizen_copy import Language, language_of, strike_message
from app.services.notification_inbox import record_inbox

log = get_logger(__name__)

MANILA = ZoneInfo("Asia/Manila")

# How long each step stops reporting; None: until an appeal is granted.
PAUSE: dict[int, timedelta | None] = {
    1: timedelta(hours=24),
    2: timedelta(days=7),
    3: timedelta(days=30),
    4: None,
}
# Verify-first, once the pause is over.
VERIFY_FIRST: dict[int, timedelta] = {
    1: timedelta(0),
    2: timedelta(days=30),
    3: timedelta(days=90),
    4: timedelta(0),
}
LIFETIME = timedelta(days=365)
MAX_STEP = 4
SERIOUS_STEP = 3
SECOND_CHECK = frozenset({3, 4})
# While a 3rd or 4th step waits for its second check.
PROVISIONAL_PAUSE = timedelta(hours=24)
PROVISIONAL_VERIFY_FIRST = timedelta(days=7)
APPEAL_WINDOW = timedelta(days=7)
# A 4th-step strike may be appealed again once it is this old, once a year.
REINSTATEMENT_AFTER = timedelta(days=365)
# An overturned strike stays this long, so both sides can see the decision.
OVERTURNED_KEPT = timedelta(days=30)

Event = Literal["given", "confirmed", "declined", "overturned", "upheld"]
AppealState = Literal["none", "pending", "upheld", "overturned"]
ReviewView = Literal["to_check", "appeals", "all"]


class Db(Protocol):
    """The pool wrapper, or a connection inside a transaction."""

    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...
    async def fetchval(self, query: str, *args: Any) -> Any: ...
    async def execute(self, query: str, *args: Any) -> str: ...


_COLUMNS = (
    "id, user_id, phone_mac, report_id, area_id, step, status, reason, serious, "
    "given_by, given_at, checked_by, checked_at, check_note, starts_at, expires_at, "
    "lesson_seen_at, appeal_text, appealed_at, appeal_decision, appeal_note, "
    "appeal_decided_by, appeal_decided_at, overturned_at"
)


@dataclass(frozen=True)
class Strike:
    """One report judged a prank, and what it does."""

    id: UUID
    user_id: UUID | None
    phone_mac: str | None
    report_id: UUID | None
    area_id: UUID | None
    step: int
    status: str  # awaiting_confirmation | active | overturned
    reason: str
    serious: bool
    given_by: UUID | None
    given_at: datetime
    checked_by: UUID | None = None
    checked_at: datetime | None = None
    check_note: str | None = None
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    lesson_seen_at: datetime | None = None
    appeal_text: str | None = None
    appealed_at: datetime | None = None
    appeal_decision: str | None = None
    appeal_note: str | None = None
    appeal_decided_by: UUID | None = None
    appeal_decided_at: datetime | None = None
    overturned_at: datetime | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Strike:
        return cls(**{f.name: row[f.name] for f in fields(cls)})

    def belongs_to(self, user_id: UUID, mac: str | None) -> bool:
        return self.user_id == user_id or (mac is not None and self.phone_mac == mac)

    def counts(self, now: datetime) -> bool:
        """Counts towards the ladder: not overturned, and not expired."""
        if self.status == "overturned":
            return False
        return self.expires_at is None or self.expires_at > now

    def pause_ends_at(self) -> datetime | None:
        """When the pause it gives ends; None when it has no end (the 4th step)."""
        if self.status == "awaiting_confirmation":
            return self.given_at + PROVISIONAL_PAUSE
        pause = PAUSE[self.step]
        if self.starts_at is None or pause is None:
            return None
        return self.starts_at + pause

    def verify_first_ends_at(self) -> datetime | None:
        if self.status == "awaiting_confirmation":
            return self.given_at + PROVISIONAL_VERIFY_FIRST
        ends = self.pause_ends_at()
        return None if ends is None else ends + VERIFY_FIRST[self.step]

    def appeal_state(self) -> AppealState:
        if self.appealed_at is None:
            return "none"
        if self.appeal_decision == "upheld":
            return "upheld"
        if self.appeal_decision == "overturned":
            return "overturned"
        return "pending"

    def can_appeal(self, now: datetime) -> bool:
        """Once within 7 days of taking effect; a 4th-step strike also once a
        year after its first 12 months."""
        if self.status != "active" or self.starts_at is None:
            return False
        if self.appeal_state() == "pending":
            return False
        if self.appealed_at is None and now <= self.starts_at + APPEAL_WINDOW:
            return True
        if self.step == MAX_STEP and now >= self.starts_at + REINSTATEMENT_AFTER:
            return self.appealed_at is None or now - self.appealed_at >= REINSTATEMENT_AFTER
        return False


@dataclass(frozen=True)
class Standing:
    """Where a resident stands: what their strikes stop, and until when."""

    now: datetime
    strikes: tuple[Strike, ...]  # every strike on record for them, newest first

    @property
    def counted(self) -> tuple[Strike, ...]:
        return tuple(s for s in self.strikes if s.counts(self.now))

    @property
    def step(self) -> int:
        return max((s.step for s in self.counted), default=0)

    @property
    def removed(self) -> bool:
        """The 4th step in effect: no reports until an appeal is granted."""
        return any(s.status == "active" and s.step == MAX_STEP for s in self.counted)

    @property
    def paused_until(self) -> datetime | None:
        ends = [e for s in self.counted if (e := s.pause_ends_at()) is not None and e > self.now]
        return max(ends, default=None)

    @property
    def can_report(self) -> bool:
        return not self.removed and self.paused_until is None

    @property
    def verify_first_until(self) -> datetime | None:
        ends = [
            e for s in self.counted if (e := s.verify_first_ends_at()) is not None and e > self.now
        ]
        return max(ends, default=None)

    @property
    def verify_first(self) -> bool:
        return self.removed or self.verify_first_until is not None

    @property
    def lesson_due(self) -> Strike | None:
        """The newest strike in effect whose lesson they have not seen."""
        return next((s for s in self.counted if s.lesson_seen_at is None), None)


def next_step(counted: Sequence[Strike], *, serious: bool) -> int:
    """The step a new strike puts someone on: one past the strikes that count
    (or past the highest step, after a serious case skipped ahead), at most the
    4th. A serious case is at least the 3rd."""
    reached = max([len(counted), *(s.step for s in counted)])
    step = min(reached + 1, MAX_STEP)
    return max(step, SERIOUS_STEP) if serious else step


# --------------------------------------------------------------------------- #
# Following the number
# --------------------------------------------------------------------------- #
def _mac_key() -> bytes:
    """A key for number MACs, derived from — and kept apart from — the JWT secret."""
    secret = get_settings().supabase_jwt_secret
    if not secret:
        raise RuntimeError("SUPABASE_JWT_SECRET is required to match strikes to a number.")
    return hmac.new(secret.encode(), b"replit/report-strikes/v1", hashlib.sha256).digest()


def phone_mac(phone: str | None, verified: bool) -> str | None:
    """The verified number's HMAC, or None when there is no verified number."""
    if not phone or not verified:
        return None
    return hmac.new(_mac_key(), phone.encode(), hashlib.sha256).hexdigest()


def mask_phone(phone: str | None) -> str | None:
    """+639171234567 -> "+63 9•• ••• 4567": enough to tell numbers apart."""
    if not phone or len(phone) < 8:
        return None
    return f"{phone[:3]} {phone[3]}•• ••• {phone[-4:]}"


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #
async def strikes_of(db: Db, user_id: UUID | None, mac: str | None) -> list[Strike]:
    """Every strike on the account or on its verified number, newest first."""
    rows = await db.fetch(
        f"""
        select {_COLUMNS} from public.report_strikes
        where user_id = $1 or ($2::text is not null and phone_mac = $2)
        order by given_at desc
        """,
        user_id,
        mac,
    )
    return [Strike.from_row(r) for r in rows]


async def standing_of(
    db: Db, user: AuthenticatedUser, now: datetime | None = None
) -> Standing:
    strikes = await strikes_of(db, user.id, phone_mac(user.phone, user.phone_verified))
    return Standing(now=now or datetime.now(UTC), strikes=tuple(strikes))


async def assert_may_report(db: Db, user: AuthenticatedUser) -> None:
    """Refuse a resident's report while their reporting is paused or removed.

    Staff are never refused. A failed lookup lets the report through: a broken
    strike table must not stop a real fire being reported.
    """
    if user.role != "general_user":
        return
    try:
        standing = await standing_of(db, user)
    except Exception:
        log.error("report_strike_lookup_failed", user_id=str(user.id), exc_info=True)
        return
    if standing.can_report:
        return
    until = standing.paused_until
    if standing.removed:
        message = (
            "Your reporting was removed after repeated prank reports. In an emergency, "
            "call 911. You can still appeal in RepLiT."
        )
    else:
        message = (
            f"Your reporting is paused until {when(until, 'en')}, after a report staff "
            "found was a prank. In an emergency, call 911."
        )
    raise ReportingPausedError(
        message,
        details={
            "removed": standing.removed,
            "paused_until": until.isoformat() if until else None,
            "step": standing.step,
        },
    )


async def held_for_verification(db: Db, area_id: UUID, now: datetime | None = None) -> bool:
    """True while an unverified fire's every report comes from a resident on
    verify-first: its 100 m neighbour alert waits until staff verify it.

    One report from anyone in good standing, or from staff, lets it through.
    So does a failed lookup.
    """
    try:
        status = await db.fetchval("select status from public.areas where id = $1", area_id)
        if status != "reported":
            return False
        rows = await db.fetch(
            """
            select r.reporter_id, u.role, u.phone, u.phone_verified
            from public.area_reports ar
            join public.reports r on r.id = ar.report_id
            left join public.users u on u.id = r.reporter_id
            where ar.area_id = $1
            """,
            area_id,
        )
        if not rows:
            return False
        moment = now or datetime.now(UTC)
        for row in rows:
            if row["reporter_id"] is None or row["role"] != "general_user":
                return False
            mac = phone_mac(row["phone"], bool(row["phone_verified"]))
            strikes = await strikes_of(db, row["reporter_id"], mac)
            if not Standing(now=moment, strikes=tuple(strikes)).verify_first:
                return False
    except Exception:
        log.error("verify_first_lookup_failed", area_id=str(area_id), exc_info=True)
        return False
    log.info("neighbour_alert_held_for_verification", area_id=str(area_id))
    return True


async def strike_counts(db: Db, reporters: Sequence[Mapping[str, Any]]) -> dict[UUID, int]:
    """Strikes in effect for each reporter (rows with reporter_id, phone,
    phone_verified), for staff weighing a report."""
    now = datetime.now(UTC)
    counts: dict[UUID, int] = {}
    for row in reporters:
        reporter = row.get("reporter_id")
        if reporter is None or reporter in counts:
            continue
        mac = phone_mac(row.get("phone"), bool(row.get("phone_verified")))
        counts[reporter] = len([s for s in await strikes_of(db, reporter, mac) if s.counts(now)])
    return counts


# --------------------------------------------------------------------------- #
# Giving, checking, appealing
# --------------------------------------------------------------------------- #
async def assert_markable(db: Db, report_id: UUID) -> None:
    """A report is judged once its fire is rejected or closed as a false alarm."""
    ok = await db.fetchval(
        """
        select exists (
            select 1 from public.area_reports ar
            join public.areas a on a.id = ar.area_id
            where ar.report_id = $1
              and (a.status = 'rejected'
                   or exists (select 1 from public.post_incident_reports p
                              where p.area_id = a.id and p.false_alarm))
        )
        """,
        report_id,
    )
    if not ok:
        raise ConflictError(
            "Mark a report as a prank once its fire is rejected or closed as a false alarm.",
            error_code="not_closed_as_false",
        )


async def give(
    db: Db,
    *,
    report_id: UUID,
    reason: str,
    serious: bool,
    giver: AuthenticatedUser,
    now: datetime | None = None,
) -> Strike:
    """Mark one report a prank: a strike for its reporter, on the next step."""
    moment = now or datetime.now(UTC)
    if len(reason.strip()) < 3:
        raise BadRequestError(
            "Say what staff found. The resident reads it.", error_code="reason_required"
        )
    reporter = await db.fetchrow(
        """
        select r.reporter_id, u.role, u.phone, u.phone_verified,
               (select ar.area_id from public.area_reports ar
                 where ar.report_id = r.id order by ar.added_at limit 1) as area_id
        from public.reports r
        left join public.users u on u.id = r.reporter_id
        where r.id = $1
        """,
        report_id,
    )
    if reporter is None:
        raise NotFoundError("Report not found.", error_code="report_not_found")
    if reporter["reporter_id"] is None or reporter["role"] is None:
        raise BadRequestError("This report's account no longer exists.", error_code="reporter_gone")
    if reporter["role"] != "general_user":
        raise BadRequestError(
            "Only a resident's report can be marked as a prank.",
            error_code="not_a_resident_report",
        )
    marked = await db.fetchval(
        "select id from public.report_strikes where report_id = $1", report_id
    )
    if marked is not None:
        raise ConflictError(
            "This report is already marked as a prank.",
            error_code="already_marked",
            details={"strike_id": str(marked)},
        )
    mac = phone_mac(reporter["phone"], bool(reporter["phone_verified"]))
    counted = [s for s in await strikes_of(db, reporter["reporter_id"], mac) if s.counts(moment)]
    step = next_step(counted, serious=serious)
    waits = step in SECOND_CHECK
    row = await db.fetchrow(
        f"""
        insert into public.report_strikes (
            user_id, phone_mac, report_id, area_id, step, reason, serious,
            given_by, given_at, status, starts_at, expires_at
        ) values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        returning {_COLUMNS}
        """,
        reporter["reporter_id"],
        mac,
        report_id,
        reporter["area_id"],
        step,
        reason.strip(),
        serious,
        giver.id,
        moment,
        "awaiting_confirmation" if waits else "active",
        None if waits else moment,
        None if waits else moment + LIFETIME,
    )
    strike = Strike.from_row(row)
    log.info(
        "report_strike_given",
        strike_id=str(strike.id),
        step=step,
        serious=serious,
        awaiting_check=waits,
    )
    return strike


async def _locked(db: Db, strike_id: UUID) -> Strike:
    row = await db.fetchrow(
        f"select {_COLUMNS} from public.report_strikes where id = $1 for update", strike_id
    )
    if row is None:
        raise NotFoundError("Strike not found.", error_code="strike_not_found")
    return Strike.from_row(row)


async def check(
    db: Db,
    *,
    strike_id: UUID,
    reviewer: AuthenticatedUser,
    confirm: bool,
    note: str | None,
    now: datetime | None = None,
) -> Strike:
    """The second staff member's check of a 3rd or 4th step."""
    moment = now or datetime.now(UTC)
    strike = await _locked(db, strike_id)
    if strike.status != "awaiting_confirmation":
        raise ConflictError(
            "This strike is not waiting for a second check.", error_code="not_awaiting_check"
        )
    if strike.given_by == reviewer.id:
        raise ForbiddenError(
            "A second staff member checks it, not the one who gave it.",
            error_code="same_reviewer",
        )
    if confirm:
        row = await db.fetchrow(
            f"""
            update public.report_strikes
               set status = 'active', checked_by = $2, checked_at = $3, check_note = $4,
                   starts_at = $3, expires_at = $5
             where id = $1
            returning {_COLUMNS}
            """,
            strike_id,
            reviewer.id,
            moment,
            note,
            None if strike.step == MAX_STEP else moment + LIFETIME,
        )
    else:
        row = await db.fetchrow(
            f"""
            update public.report_strikes
               set status = 'overturned', checked_by = $2, checked_at = $3, check_note = $4,
                   overturned_at = $3
             where id = $1
            returning {_COLUMNS}
            """,
            strike_id,
            reviewer.id,
            moment,
            note,
        )
    return Strike.from_row(row)


async def appeal(
    db: Db,
    *,
    strike_id: UUID,
    user: AuthenticatedUser,
    text: str,
    now: datetime | None = None,
) -> Strike:
    """The resident's appeal of their own strike."""
    moment = now or datetime.now(UTC)
    if len(text.strip()) < 10:
        raise BadRequestError(
            "Say a little more about why this was not a prank.", error_code="appeal_too_short"
        )
    strike = await _locked(db, strike_id)
    if not strike.belongs_to(user.id, phone_mac(user.phone, user.phone_verified)):
        raise NotFoundError("Strike not found.", error_code="strike_not_found")
    if not strike.can_appeal(moment):
        raise ConflictError("This strike can't be appealed now.", error_code="appeal_closed")
    row = await db.fetchrow(
        f"""
        update public.report_strikes
           set appeal_text = $2, appealed_at = $3, appeal_decision = null,
               appeal_note = null, appeal_decided_by = null, appeal_decided_at = null
         where id = $1
        returning {_COLUMNS}
        """,
        strike_id,
        text.strip(),
        moment,
    )
    return Strike.from_row(row)


async def decide_appeal(
    db: Db,
    *,
    strike_id: UUID,
    reviewer: AuthenticatedUser,
    overturn: bool,
    note: str | None,
    now: datetime | None = None,
) -> Strike:
    """Uphold or overturn an appeal; never by whoever gave the strike."""
    moment = now or datetime.now(UTC)
    strike = await _locked(db, strike_id)
    if strike.status != "active" or strike.appeal_state() != "pending":
        raise ConflictError(
            "There is no appeal waiting on this strike.", error_code="no_pending_appeal"
        )
    if strike.given_by == reviewer.id:
        raise ForbiddenError(
            "Someone other than whoever gave the strike decides its appeal.",
            error_code="same_reviewer",
        )
    row = await db.fetchrow(
        f"""
        update public.report_strikes
           set appeal_decision = $2, appeal_note = $3, appeal_decided_by = $4,
               appeal_decided_at = $5,
               status = case when $2 = 'overturned' then 'overturned' else status end,
               overturned_at = case when $2 = 'overturned' then $5 else overturned_at end
         where id = $1
        returning {_COLUMNS}
        """,
        strike_id,
        "overturned" if overturn else "upheld",
        note,
        reviewer.id,
        moment,
    )
    return Strike.from_row(row)


async def lesson_seen(db: Db, *, strike_id: UUID, user: AuthenticatedUser) -> bool:
    """Record that the resident read the lesson; False when it is not theirs."""
    result = await db.execute(
        """
        update public.report_strikes
           set lesson_seen_at = coalesce(lesson_seen_at, now())
         where id = $1 and (user_id = $2 or ($3::text is not null and phone_mac = $3))
        """,
        strike_id,
        user.id,
        phone_mac(user.phone, user.phone_verified),
    )
    return not result.endswith(" 0")


async def purge(db: Db, now: datetime | None = None) -> int:
    """Delete strikes that expired, and overturned ones after 30 days (hourly)."""
    moment = now or datetime.now(UTC)
    result = await db.execute(
        """
        delete from public.report_strikes
         where (status = 'active' and expires_at is not null and expires_at <= $1)
            or (status = 'overturned' and overturned_at <= $2)
        """,
        moment,
        moment - OVERTURNED_KEPT,
    )
    try:
        return int(result.rsplit(" ", 1)[-1])
    except ValueError:
        return 0


# --------------------------------------------------------------------------- #
# Telling the resident
# --------------------------------------------------------------------------- #
_MONTHS: dict[Language, tuple[str, ...]] = {
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
    "tl": ("Ene", "Peb", "Mar", "Abr", "May", "Hun", "Hul", "Ago", "Set", "Okt", "Nob", "Dis"),
}


def when(moment: datetime | None, language: Language) -> str:
    """ "20 Nov, 3:15 PM", Manila time, in the reader's language."""
    if moment is None:
        return ""
    local = moment.astimezone(MANILA)
    hour = local.hour % 12 or 12
    half = "AM" if local.hour < 12 else "PM"
    return f"{local.day} {_MONTHS[language][local.month - 1]}, {hour}:{local:%M} {half}"


async def tell(db: Database, strike: Strike, event: Event) -> None:
    """Push and inbox the resident about their strike, in their language.

    Best-effort, after the change is committed: a failed push never undoes it.
    """
    if strike.user_id is None:
        return
    try:
        row = await db.fetchrow(
            "select language, phone, phone_verified from public.users where id = $1",
            strike.user_id,
        )
        if row is None:
            return
        language = language_of(row["language"])
        strikes = await strikes_of(
            db, strike.user_id, phone_mac(row["phone"], bool(row["phone_verified"]))
        )
        standing = Standing(now=datetime.now(UTC), strikes=tuple(strikes))
        title, body = strike_message(
            language,
            event,
            step=strike.step,
            awaiting=strike.status == "awaiting_confirmation",
            until=when(standing.paused_until, language),
            can_report=standing.can_report,
        )
        data = {"strike_id": str(strike.id), "event": event}
        # The in-app alert plays what the push does (lib/alerts/inbox_watcher.dart
        # reads sound_category before the type).
        await record_inbox(
            db,
            [strike.user_id],
            "report_strike",
            title,
            body,
            {**data, "sound_category": "rejected"},
        )
        tokens = await db.fetch(
            "select fcm_token, app_version from public.device_tokens "
            "where user_id = $1 and is_active",
            strike.user_id,
        )
        if not tokens:
            return
        result = await PushService().send_to_tokens(
            tokens=[t["fcm_token"] for t in tokens],
            title=title,
            body=body,
            data={"type": "report_strike", **data},
            sound="rejected",
            tag=f"strike-{strike.id}",
            versions=token_versions(tokens),
        )
        if result.invalid_tokens:
            await db.execute(
                "update public.device_tokens set is_active = false "
                "where fcm_token = any($1::text[])",
                result.invalid_tokens,
            )
    except Exception:
        log.error("report_strike_tell_failed", strike_id=str(strike.id), exc_info=True)


# --------------------------------------------------------------------------- #
# The console's queues
# --------------------------------------------------------------------------- #
_VIEWS: dict[ReviewView, tuple[str, str]] = {
    "to_check": ("s.status = 'awaiting_confirmation'", "s.given_at"),
    "appeals": (
        "s.status = 'active' and s.appealed_at is not null and s.appeal_decision is null",
        "s.appealed_at",
    ),
    "all": ("true", "s.given_at desc"),
}


async def review_queue(db: Db, view: ReviewView, limit: int = 200) -> list[dict[str, Any]]:
    """Strikes for the console, with who and what each concerns."""
    where, order = _VIEWS[view]
    return await _review_rows(db, where, order, limit)


async def review_item(db: Db, strike_id: UUID) -> dict[str, Any]:
    """One strike as the console's queues show it."""
    rows = await _review_rows(db, "s.id = $2", "s.given_at", 1, strike_id)
    if not rows:
        raise NotFoundError("Strike not found.", error_code="strike_not_found")
    return rows[0]


async def _review_rows(
    db: Db, where: str, order: str, limit: int, *args: Any
) -> list[dict[str, Any]]:
    rows = await db.fetch(
        f"""
        select {", ".join(f"s.{c.strip()}" for c in _COLUMNS.split(","))},
               u.full_name as resident_name, u.phone as resident_phone,
               g.full_name as given_by_name, c.full_name as checked_by_name,
               d.full_name as appeal_decided_by_name,
               r.created_at as report_created_at, r.device_lat as report_lat,
               r.device_lng as report_lng, r.notes as report_notes,
               (select count(*) from public.report_strikes o
                 where (o.user_id = s.user_id
                        or (s.phone_mac is not null and o.phone_mac = s.phone_mac))
                   and o.status <> 'overturned'
                   and (o.expires_at is null or o.expires_at > now())) as resident_strikes
        from public.report_strikes s
        left join public.users u on u.id = s.user_id
        left join public.users g on g.id = s.given_by
        left join public.users c on c.id = s.checked_by
        left join public.users d on d.id = s.appeal_decided_by
        left join public.reports r on r.id = s.report_id
        where {where}
        order by {order}
        limit $1
        """,
        limit,
        *args,
    )
    items: list[dict[str, Any]] = []
    shown = [f.name for f in fields(Strike) if f.name != "phone_mac"]
    for row in rows:
        strike = Strike.from_row(row)
        items.append(
            {
                **{name: getattr(strike, name) for name in shown},
                "pause_ends_at": strike.pause_ends_at(),
                "appeal_state": strike.appeal_state(),
                "resident_name": row["resident_name"],
                "resident_phone": mask_phone(row["resident_phone"]),
                "resident_strikes": int(row["resident_strikes"] or 0),
                "given_by_name": row["given_by_name"],
                "checked_by_name": row["checked_by_name"],
                "appeal_decided_by_name": row["appeal_decided_by_name"],
                "report_created_at": row["report_created_at"],
                "report_lat": row["report_lat"],
                "report_lng": row["report_lng"],
                "report_notes": row["report_notes"],
            }
        )
    return items
