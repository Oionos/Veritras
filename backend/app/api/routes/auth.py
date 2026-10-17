from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from jose import jwt
from sqlalchemy.orm import Session

from app.core.auth import create_access_token, issue_challenge, sign_in_origin, verify_challenge
from app.core.database import get_db
from app.core.limiter import limiter
from app.schemas.auth import ChallengeRequest, ChallengeResponse, NonceResponse, VerifyRequest, VerifyResponse

router = APIRouter()


def no_cache(response: Response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"


@router.get("/nonce", response_model=NonceResponse)
@limiter.limit("5/minute")
def get_nonce(request: Request, response: Response, db: Session = Depends(get_db)):
    """Compatibility nonce endpoint; scope and expiry remain server controlled."""
    no_cache(response)
    return issue_challenge(db, sign_in_origin(request))


@router.post("/challenge", response_model=ChallengeResponse)
@limiter.limit("5/minute")
def challenge(request: Request, response: Response, body: ChallengeRequest, db: Session = Depends(get_db)):
    """Issue the exact message the requested wallet must sign."""
    no_cache(response)
    return issue_challenge(db, sign_in_origin(request), body.address)


@router.post("/verify", response_model=VerifyResponse)
@limiter.limit("5/minute")
def verify(request: Request, response: Response, body: VerifyRequest, db: Session = Depends(get_db)):
    no_cache(response)
    address = verify_challenge(db, request, body.message, body.signature)
    token = create_access_token(address)
    return {"access_token": token, "token_type": "bearer", "address": address,
            "expires_at": datetime.fromtimestamp(jwt.get_unverified_claims(token)["exp"], timezone.utc)}
