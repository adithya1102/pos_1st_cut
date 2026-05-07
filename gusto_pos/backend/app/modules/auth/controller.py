from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.service import AuthService
from app.modules.staff.service import StaffService
from app.modules.staff.schema import PinLoginRequest, PinLoginResponse

router = APIRouter(prefix="/auth")


@router.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    token_response = await AuthService.authenticate_user(db, form_data.username, form_data.password)

    if not token_response:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token_response


@router.post("/pin-login", response_model=PinLoginResponse)
async def pin_login(request: PinLoginRequest, db: AsyncSession = Depends(get_db)):
    result = await StaffService.pin_login(db, request)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid PIN",
        )

    return result