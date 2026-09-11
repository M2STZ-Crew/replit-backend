"""Audit logging: request-driven RBAC/lifecycle audit + provenance (Phase 14).

A curated set of mutating endpoints is auto-audited by the request middleware
(actor + ip/user-agent/request-id + action), so the route handlers stay clean.
Richer before/after audits (e.g. hydrant ground-truth) are written explicitly at
their action sites. audit_logs is append-only (DB-enforced).
"""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from fastapi import Request, Response

from app.core.logging import get_logger
from app.db.session import database
from app.schemas.auth import AuthenticatedUser

log = get_logger(__name__)


class _Executor(Protocol):
    """Anything that can run a statement: the pool wrapper, or a connection in a transaction."""

    async def execute(self, query: str, *args: Any) -> str: ...

_UUID = r"[0-9a-fA-F-]{36}"


@dataclass(frozen=True)
class _Rule:
    method: str
    regex: re.Pattern[str]
    action: str
    entity_type: str
    is_area: bool


def _rule(method: str, path_regex: str, action: str, entity: str, is_area: bool = False) -> _Rule:
    return _Rule(method, re.compile(path_regex), action, entity, is_area)


# Curated RBAC / lifecycle endpoints to audit automatically.
#
# The v10 actions — Admin routing, observer Accept, filing a Post-Incident Report
# — are deliberately NOT listed: each writes its own row through record_audit()
# so the entry carries what was decided (which agencies, which truck), and a
# rule here would record the same action twice.
_RULES: list[_Rule] = [
    _rule("POST", rf"^/incidents/({_UUID})/verify$", "incident.verify", "area", True),
    _rule("POST", rf"^/incidents/({_UUID})/reject$", "incident.reject", "area", True),
    _rule("POST", rf"^/incidents/({_UUID})/resolve$", "incident.resolve", "area", True),
    _rule("POST", rf"^/incidents/({_UUID})/dispatch$", "incident.dispatch", "area", True),
    _rule("POST", rf"^/incidents/({_UUID})/self-dispatch$", "incident.self_dispatch", "area", True),
    _rule("POST", rf"^/incidents/({_UUID})/en-route$", "incident.en_route", "area", True),
    _rule("POST", rf"^/incidents/({_UUID})/arrived$", "incident.arrived", "area", True),
    _rule("POST", rf"^/alarm-requests/({_UUID})/execute$", "alarm.execute", "alarm_request"),
    _rule("POST", rf"^/alarm-requests/({_UUID})/reject$", "alarm.reject", "alarm_request"),
    _rule("POST", r"^/admin/users$", "user.create", "user"),
    _rule("POST", rf"^/admin/verifications/({_UUID})/approve$", "kyc.approve", "user_verification"),
    _rule("POST", rf"^/admin/verifications/({_UUID})/reject$", "kyc.reject", "user_verification"),
    _rule("POST", rf"^/affiliates/({_UUID})/accept$", "affiliate.accept", "affiliate_request"),
    _rule("POST", rf"^/map-layer-requests/({_UUID})/approve$", 
          "map_layer.request_approve", 
          "map_layer_request"),
]


def match_audit_rule(method: str, path: str) -> tuple[str, str, UUID | None, bool] | None:
    """Return (action, entity_type, entity_id, is_area) for an audited request, or None."""
    for rule in _RULES:
        if rule.method != method:
            continue
        match = rule.regex.match(path)
        if match is None:
            continue
        entity_id: UUID | None = None
        if match.groups():
            try:
                entity_id = UUID(match.group(1))
            except ValueError:
                entity_id = None
        return rule.action, rule.entity_type, entity_id, rule.is_area
    return None


def _safe_ip(host: str | None) -> str | None:
    """Return host only if it parses as an IP address (audit_logs.ip_address is inet)."""
    if not host:
        return None
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return None
    return host


async def record_audit(
    db: _Executor,
    request: Request,
    user: AuthenticatedUser,
    *,
    action: str,
    entity_type: str,
    entity_id: UUID | None,
    area_id: UUID | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append an audit_logs row written at the action site, with request provenance.

    Unlike :func:`maybe_record_request_audit` this is not best-effort: pass the
    connection of the transaction making the change, so the action and its
    record commit together or not at all.
    """
    await db.execute(
        """
        insert into public.audit_logs
            (actor_user_id, actor_role, actor_agency, action, entity_type, entity_id,
             area_id, before_state, after_state, metadata, ip_address, user_agent,
             request_id)
        values ($1, $2::public.user_role, $3::public.agency_type, $4, $5, $6, $7,
                $8::jsonb, $9::jsonb, $10::jsonb, $11::inet, $12, $13)
        """,
        user.id,
        user.role,
        user.agency_type,
        action,
        entity_type,
        entity_id,
        area_id,
        json.dumps(before_state, default=str) if before_state is not None else None,
        json.dumps(after_state, default=str) if after_state is not None else None,
        json.dumps(metadata or {}, default=str),
        _safe_ip(request.client.host if request.client else None),
        request.headers.get("user-agent"),
        getattr(request.state, "request_id", None),
    )


async def maybe_record_request_audit(request: Request, response: Response) -> None:
    """Write an audit_logs row for a curated, successful mutating request (best-effort)."""
    try:
        if request.method not in ("POST", "PATCH", "PUT", "DELETE"):
            return
        if response.status_code >= 400:
            return
        matched = match_audit_rule(request.method, request.url.path)
        if matched is None:
            return
        action, entity_type, entity_id, is_area = matched
        await database.execute(
            """
            insert into public.audit_logs
                (actor_user_id, actor_role, actor_agency, action, entity_type, entity_id,
                 area_id, ip_address, user_agent, request_id)
            values ($1, $2::public.user_role, $3::public.agency_type, $4, $5, $6, $7,
                    $8::inet, $9, $10)
            """,
            getattr(request.state, "actor_id", None),
            getattr(request.state, "actor_role", None),
            getattr(request.state, "actor_agency", None),
            action,
            entity_type,
            entity_id,
            entity_id if is_area else None,
            _safe_ip(request.client.host if request.client else None),
            request.headers.get("user-agent"),
            getattr(request.state, "request_id", None),
        )
    except Exception:
        log.warning("audit_record_failed", path=request.url.path, exc_info=True)