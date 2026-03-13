"""認證模組

負責使用者註冊、登入、JWT 簽發與驗證。
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Header

from config import get_settings
from database import get_db, create_user, get_user_by_username
from models import RegisterRequest, RegisterResponse, LoginRequest, TokenResponse


auth_router = APIRouter(prefix="/auth", tags=["auth"])


def create_access_token(user_id: int, username: str) -> str:
    """簽發 JWT，payload 含 sub=user_id, username, exp, iat。使用 HS256。"""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": now,
        "exp": now + timedelta(hours=settings.jwt_expire_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


async def get_current_user(
    authorization: str = Header(...),
    db=Depends(get_db),
) -> dict:
    """從 Authorization header 解析 JWT，回傳 {id, username}。

    無效/過期 token 拋出 HTTPException(401)。
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供認證權杖")

    token = authorization[len("Bearer "):]
    if not token:
        raise HTTPException(status_code=401, detail="未提供認證權杖")

    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="認證權杖已過期")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="認證權杖無效")

    return {"id": int(payload["sub"]), "username": payload["username"]}


@auth_router.post("/register", status_code=201)
async def register(request: RegisterRequest, db=Depends(get_db)) -> RegisterResponse:
    """註冊新使用者。密碼以 bcrypt 雜湊儲存。

    成功回傳 201 + {username, message}。
    username 重複回傳 409。驗證失敗回傳 422（Pydantic 處理）。
    """
    # 檢查 username 是否已存在
    existing = await get_user_by_username(db, request.username)
    if existing:
        raise HTTPException(status_code=409, detail="使用者名稱已被使用")

    # bcrypt 雜湊密碼
    password_hash = bcrypt.hashpw(
        request.password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")

    await create_user(db, request.username, password_hash)
    return RegisterResponse(username=request.username, message="註冊成功")


@auth_router.post("/login")
async def login(request: LoginRequest, db=Depends(get_db)) -> TokenResponse:
    """驗證帳密，成功回傳 {access_token, token_type: "bearer"}。失敗回傳 401。"""
    user = await get_user_by_username(db, request.username)
    if not user:
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")

    if not bcrypt.checkpw(
        request.password.encode("utf-8"),
        user["password_hash"].encode("utf-8"),
    ):
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")

    token = create_access_token(user["id"], user["username"])
    return TokenResponse(access_token=token)
