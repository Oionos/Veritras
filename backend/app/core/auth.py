import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from siwe import SiweMessage
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from web3 import Web3

from app.core.config import settings
from app.models.auth import AuthChallenge

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/verify", auto_error=False)


def utc(value: datetime) -> datetime:
    # SQLite strips timezone info; PostgreSQL preserves it.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def auth_error(detail="Invalid authentication credentials"):
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def sign_in_origin(request: Request) -> str:
    allowed = settings.allowed_siwe_origins
    origin = request.headers.get("origin")
    if origin is None:
        # Non-browser clients use the configured primary origin, never Host or
        # forwarded headers. A browser must use an explicitly allowed origin.
        return allowed[0]
    if origin not in allowed:
        raise HTTPException(status_code=403, detail="Sign-in origin is not allowed")
    return origin


def issue_challenge(db: Session, origin: str, address: str | None = None) -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    expires = now + timedelta(seconds=settings.auth_challenge_ttl_seconds)
    nonce = secrets.token_hex(16)
    address = Web3.to_checksum_address(address) if address else None
    message = None
    if address:
        message = SiweMessage(
            domain=urlsplit(origin).netloc, address=address, uri=origin,
            version="1", chain_id=settings.chain_id, nonce=nonce,
            issued_at=now.isoformat(), expiration_time=expires.isoformat(),
            statement="Sign in to Veritras",
        ).prepare_message()
    db.execute(delete(AuthChallenge).where(AuthChallenge.expires_at <= now).execution_options(synchronize_session=False))
    db.add(AuthChallenge(
        nonce_hash=hashlib.sha256(nonce.encode()).hexdigest(), address=address,
        origin=origin, chain_id=settings.chain_id, issued_at=now,
        expires_at=expires, message=message,
    ))
    db.commit()
    return dict(nonce=nonce, domain=urlsplit(origin).netloc, uri=origin,
                chain_id=settings.chain_id, issued_at=now, expires_at=expires,
                message=message)


def verify_challenge(db: Session, request: Request, raw: str, signature: str) -> str:
    try:
        message = SiweMessage.from_message(raw)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid SIWE message") from None
    nonce_hash = hashlib.sha256(message.nonce.encode()).hexdigest()
    challenge = db.scalar(select(AuthChallenge).where(AuthChallenge.nonce_hash == nonce_hash))
    now = datetime.now(timezone.utc)
    if challenge is None or utc(challenge.expires_at) <= now:
        raise auth_error("Invalid or expired nonce")
    issued = utc(message.issued_at._datetime)
    skew = timedelta(seconds=settings.auth_clock_skew_seconds)
    try:
        if (challenge.origin not in settings.allowed_siwe_origins
                or (request.headers.get("origin") is not None
                    and request.headers["origin"] != challenge.origin)
                or message.uri != challenge.origin
                or message.chain_id != challenge.chain_id
                or message.chain_id != settings.chain_id
                or issued < utc(challenge.issued_at) - skew
                or issued > now + skew
                or issued >= utc(challenge.expires_at)
                or (challenge.address and message.address != challenge.address)
                or (challenge.message and raw != challenge.message)
                or raw != message.prepare_message()
                or (message.expiration_time is not None
                    and utc(message.expiration_time._datetime) > utc(challenge.expires_at))):
            raise ValueError("Scope mismatch")
        message.verify(signature, domain=urlsplit(challenge.origin).netloc,
                       nonce=message.nonce, timestamp=now)
        if message.scheme not in {None, urlsplit(challenge.origin).scheme}:
            raise ValueError("Scheme mismatch")
    except Exception:
        # Invalid signatures and scope mismatches never consume a valid nonce.
        raise auth_error("Invalid sign-in scope, time, or signature") from None
    consumed = db.execute(delete(AuthChallenge).where(
        AuthChallenge.nonce_hash == nonce_hash,
        AuthChallenge.expires_at > datetime.now(timezone.utc),
    ).execution_options(synchronize_session=False)).rowcount
    if consumed != 1:
        db.rollback()
        raise auth_error("Invalid or already used nonce")
    db.commit()
    return message.address.lower()


def create_access_token(address: str) -> str:
    if not Web3.is_address(address):
        raise ValueError("Invalid wallet address")
    now = datetime.now(timezone.utc)
    return jwt.encode({
        "sub": address.lower(), "exp": now + timedelta(hours=settings.jwt_expiration_hours),
        "iat": now, "nbf": now, "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience, "jti": secrets.token_hex(16),
        "chain_id": settings.chain_id,
    }, settings.jwt_secret_key, algorithm="HS256")


def verify_access_token(token: str) -> str:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"],
            issuer=settings.jwt_issuer, audience=settings.jwt_audience,
            options={"require_exp": True, "require_iat": True, "require_nbf": True,
                     "require_sub": True, "require_iss": True, "require_aud": True,
                     "require_jti": True})
        address = payload.get("sub")
        if (not isinstance(address, str) or not Web3.is_address(address)
                or payload.get("chain_id") != settings.chain_id
                or payload["iat"] > datetime.now(timezone.utc).timestamp()):
            raise auth_error()
        return address.lower()
    except (JWTError, ValueError, TypeError):
        raise auth_error() from None


def get_current_user(token: str | None = Depends(oauth2_scheme)) -> str:
    if token is None:
        raise auth_error("Not authenticated")
    return verify_access_token(token)
