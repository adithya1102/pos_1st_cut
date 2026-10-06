from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.service import AuthService
from app.modules.carevo_customer.service import CarevoService
from app.modules.staff.service import StaffService
from app.modules.staff.schema import PinLoginRequest, PinLoginResponse

router = APIRouter(prefix="/auth")


def _client_ip(request: Request) -> str:
    """Caller IP for the rate-limit bucket.

    Copied in shape from app/modules/public/controller.py so there is one
    convention in the codebase. Behind Render's proxy the socket peer is the
    proxy, so X-Forwarded-For is read first and its LEFTMOST entry taken. That
    header is spoofable and is used for NOTHING but bucketing a rate limit — no
    authorization decision depends on it.
    """
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/login")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """Staff login, now rate-limited.

    THROTTLED per username and per IP (see CarevoService.check_login_rate_limit).
    Neither this nor /pin-login had any limit, so an owner password could be
    ground down with unlimited attempts from one host.

    The limit is checked BEFORE authentication, so a refusal costs no bcrypt
    verification — which also means the throttle doubles as the backstop
    against using this endpoint as a CPU sink now that hashing is cost-12
    bcrypt.
    """
    CarevoService.check_login_rate_limit(form_data.username, _client_ip(request))

    token_response = await AuthService.authenticate_user(
        db, form_data.username, form_data.password
    )

    if not token_response:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token_response


@router.post("/pin-login", response_model=PinLoginResponse)
async def pin_login(
    request: Request,
    payload: PinLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """PIN login for a NAMED staff account.

    `username` is now required in the body — see PinLoginRequest for why. In
    short: without it this endpoint answered "is this PIN anyone's?" and issued
    a token for whichever of 1,906 rows matched first.

    401 is returned identically for an unknown username and a wrong PIN, so
    this is not a username oracle.

    BREAKING for the two MAUI desktop clients, which send {pin} only:
      GustoPOS     ApiService.cs:1074
      GustoWaiter  ApiService.cs:884
    Both are recorded in carevomd.md. Neither sends an Authorization header on
    any request today, so neither is a working authenticated client as it
    stands.
    """
    CarevoService.check_login_rate_limit(payload.username, _client_ip(request))

    result = await StaffService.pin_login(db, payload)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or PIN",
        )

    return result
