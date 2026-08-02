import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from epyhia.config import CredentialNotConfigured, settings

_bearer_scheme = HTTPBearer(auto_error=False)

_jwks_clients: dict[str, jwt.PyJWKClient] = {}


class Unauthorized(Exception):
    """Raised for anything wrong with the bearer token itself — missing, malformed,
    expired, wrong audience or issuer. There is no second path in (FR-057)."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


def _jwks_client(domain: str) -> jwt.PyJWKClient:
    client = _jwks_clients.get(domain)
    if client is None:
        client = jwt.PyJWKClient(f"https://{domain}/.well-known/jwks.json")
        _jwks_clients[domain] = client
    return client


async def require_operator(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    """Auth0 Bearer validation for every operator route (FR-057) — no bypass key, no
    cookie session. Raises `CredentialNotConfigured` if Auth0 itself isn't configured,
    and `Unauthorized` for anything wrong with the token."""
    domain = settings.require("auth0")
    audience = settings.auth0_audience
    if audience is None:
        raise CredentialNotConfigured("auth0_audience")

    if credentials is None:
        raise Unauthorized("missing bearer token")

    try:
        signing_key = _jwks_client(domain).get_signing_key_from_jwt(credentials.credentials)
        claims = jwt.decode(
            credentials.credentials,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience,
            issuer=f"https://{domain}/",
        )
    except jwt.PyJWTError as exc:
        raise Unauthorized(str(exc)) from exc

    return claims
