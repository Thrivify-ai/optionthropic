"""
Authentication routes.

Dev/staging: local JWT backed by bcrypt password hashes in PostgreSQL.
Production (USE_COGNITO=true): token exchange via AWS Cognito user pools.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.database import get_db
from app.logging_config import get_logger
from app.models.user import User, UserPlan
from app.models.user_events import UserEvent

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,
    bcrypt__ident="2b",
)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ─── Schemas ───────────────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# Admin email — always gets admin + pro
ADMIN_EMAIL = "shivraj@thrivify.ai"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    email: str
    plan: str
    is_admin: bool = False


class UserResponse(BaseModel):
    id: str
    email: str
    plan: str
    is_admin: bool
    created_at: datetime


# ─── JWT helpers ───────────────────────────────────────────────────────────────

def _create_access_token(subject: str, extra: dict | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": subject, "exp": expire, **(extra or {})}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def _verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def _hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


# ─── Cognito helper ────────────────────────────────────────────────────────────

async def _cognito_signup(email: str, password: str) -> str:
    import boto3

    client = boto3.client(
        "cognito-idp",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id or None,
        aws_secret_access_key=settings.aws_secret_access_key or None,
    )
    import asyncio

    response = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: client.sign_up(
            ClientId=settings.cognito_client_id,
            Username=email,
            Password=password,
            UserAttributes=[{"Name": "email", "Value": email}],
        ),
    )
    return response["UserSub"]


async def _cognito_login(email: str, password: str) -> str:
    import boto3
    import asyncio

    client = boto3.client(
        "cognito-idp",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id or None,
        aws_secret_access_key=settings.aws_secret_access_key or None,
    )
    response = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: client.initiate_auth(
            ClientId=settings.cognito_client_id,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": email, "PASSWORD": password},
        ),
    )
    return response["AuthenticationResult"]["IdToken"]


# ─── Current user dependency ───────────────────────────────────────────────────

async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    stmt = select(User).where(User.id == user_id)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exception
    return user


async def require_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


async def require_pro(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Pro Signals access: PRO, ENTERPRISE, or admin."""
    if current_user.is_admin:
        return current_user
    if current_user.plan in (UserPlan.PRO, UserPlan.ENTERPRISE):
        return current_user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Pro plan required. Upgrade to access Pro Signals.",
    )


# ─── Routes ────────────────────────────────────────────────────────────────────

@router.post("/signup", response_model=TokenResponse, status_code=201)
async def signup(
    body: SignupRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    existing = (
        await session.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    cognito_sub = None
    if settings.use_cognito:
        try:
            cognito_sub = await _cognito_signup(body.email, body.password)
        except Exception as exc:
            logger.error("Cognito signup failed", error=str(exc))
            raise HTTPException(status_code=502, detail="Identity provider error")

    is_admin = body.email.lower() == ADMIN_EMAIL.lower()
    plan = UserPlan.PRO if is_admin else UserPlan.FREE

    user = User(
        email=body.email,
        password_hash=_hash_password(body.password) if not settings.use_cognito else None,
        plan=plan,
        is_admin=is_admin,
        cognito_sub=cognito_sub,
    )
    session.add(user)
    await session.flush()

    session.add(
        UserEvent(
            user_id=user.id,
            event_name="signup",
            properties={"email": user.email},
            timestamp=datetime.now(timezone.utc),
        )
    )
    await session.commit()

    token = _create_access_token(
        user.id,
        {"email": user.email, "plan": user.plan.value, "is_admin": user.is_admin},
    )
    return TokenResponse(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
        user_id=user.id,
        email=user.email,
        plan=user.plan.value,
        is_admin=user.is_admin,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    stmt = select(User).where(User.email == body.email)
    user: User | None = (await session.execute(stmt)).scalar_one_or_none()

    if settings.use_cognito:
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        try:
            await _cognito_login(body.email, body.password)
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid credentials")
    else:
        if not user or not user.password_hash or not _verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    session.add(
        UserEvent(
            user_id=user.id,
            event_name="login",
            timestamp=datetime.now(timezone.utc),
        )
    )
    await session.commit()

    token = _create_access_token(
        user.id,
        {"email": user.email, "plan": user.plan.value, "is_admin": user.is_admin},
    )
    return TokenResponse(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
        user_id=user.id,
        email=user.email,
        plan=user.plan.value,
        is_admin=user.is_admin,
    )


@router.get("/me", response_model=UserResponse)
async def me(current_user: Annotated[User, Depends(get_current_user)]) -> Any:
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        plan=current_user.plan.value,
        is_admin=current_user.is_admin,
        created_at=current_user.created_at,
    )


# OAuth2 form-based login (for Swagger UI compatibility)
@router.post("/token", response_model=TokenResponse, include_in_schema=False)
async def login_form(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    return await login(
        LoginRequest(email=form_data.username, password=form_data.password),
        session,
    )
