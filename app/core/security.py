"""Supabase access-token validation (JWKS + HS256 fallback).

Validates Bearer access tokens issued by Supabase Auth. Asymmetric tokens
(RS256/ES256) are verified against the project's JWKS public keys (fetched and
cached by key id); legacy HS256 tokens are verified with the shared JWT secret.

v8 master context: Section 5 (Auth — JWT validated against Supabase JWKS in the
FastAPI middleware), Section 13 (no hardcoded secrets).
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import jwt
from jwt import InvalidTokenError, PyJWK

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError
from app.core.logging import get_logger

log = get_logger(__name__)


class JWKSCache:
    """In-memory cache of Supabase JWKS public keys, keyed by `kid`, with a TTL."""

    def __init__(self) -> None:
        self._keys: dict[str, PyJWK] = {}
        self._expires_at: float = 0.0

    async def _refresh(self, client: httpx.AsyncClient) -> None:
        """Fetch and parse the JWKS document from Supabase."""
        settings = get_settings()
        try:
            response = await client.get(
                settings.jwks_url,
                headers={"apikey": settings.supabase_anon_key},
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            log.error("jwks_fetch_failed", error=str(exc))
            raise UnauthorizedError("Unable to fetch token signing keys.") from exc

        keys: dict[str, PyJWK] = {}
        for jwk in data.get("keys", []):
            kid = jwk.get("kid")
            if not isinstance(kid, str):
                continue
            try:
                keys[kid] = PyJWK.from_dict(jwk)
            except Exception:
                log.warning("jwks_key_parse_failed", kid=kid)
        self._keys = keys
        self._expires_at = time.monotonic() + settings.jwks_cache_ttl_seconds
        log.info("jwks_refreshed", key_count=len(keys))

    async def get_key(self, client: httpx.AsyncClient, kid: str) -> PyJWK | None:
        """Return the signing key for `kid`, refreshing the cache if needed."""
        if time.monotonic() >= self._expires_at or kid not in self._keys:
            await self._refresh(client)
        return self._keys.get(kid)


_jwks_cache = JWKSCache()


async def decode_access_token(token: str, client: httpx.AsyncClient) -> dict[str, Any]:
    """Validate a Supabase access token and return its verified claims.

    Args:
        token: The raw JWT from the Authorization: Bearer header.
        client: Shared httpx client used to fetch JWKS on cache miss.

    Returns:
        The decoded, verified claims dictionary.

    Raises:
        UnauthorizedError: if the token is malformed, unsupported, or invalid/expired.
    """
    settings = get_settings()
    try:
        header = jwt.get_unverified_header(token)
    except InvalidTokenError as exc:
        raise UnauthorizedError("Malformed authentication token.") from exc

    alg = header.get("alg", "")

    try:
        if alg == "HS256":
            if not settings.supabase_jwt_secret:
                raise UnauthorizedError("Server is not configured to validate HS256 tokens.")
            claims = jwt.decode(
                token,
                key=settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience=settings.jwt_audience,
                leeway=10,
                options={"require": ["exp", "sub"], "verify_aud": True},
            )
        elif alg in ("RS256", "ES256"):
            kid = header.get("kid")
            if not isinstance(kid, str):
                raise UnauthorizedError("Token is missing a key id (kid).")
            signing_key = await _jwks_cache.get_key(client, kid)
            if signing_key is None:
                raise UnauthorizedError("Unknown token signing key.")
            claims = jwt.decode(
                token,
                key=signing_key.key,
                algorithms=[alg],
                audience=settings.jwt_audience,
                leeway=10,
                options={"require": ["exp", "sub"], "verify_aud": True},
            )
        else:
            raise UnauthorizedError(f"Unsupported token algorithm: {alg!r}.")
    except InvalidTokenError as exc:
        raise UnauthorizedError("Invalid or expired authentication token.") from exc

    return claims