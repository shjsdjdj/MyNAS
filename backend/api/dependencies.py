from fastapi import Cookie, Depends, HTTPException, status
from jwt import InvalidTokenError

from backend.core.security import COOKIE_NAME, access_token_is_revoked, decode_access_token
from backend.services.auth_service import get_user


def current_user(
    cookie_token: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> dict:
    token = cookie_token
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "需要登录")
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (InvalidTokenError, KeyError, ValueError, TypeError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已失效")
    if access_token_is_revoked(token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已失效")
    user = get_user(user_id)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    return {
        **user,
        "session": {
            "issued_at": payload.get("iat"),
            "expires_at": payload.get("exp"),
            "auth_type": "cookie",
        },
    }


def active_user(user: dict = Depends(current_user)) -> dict:
    """Block access until forced password change is completed."""
    from backend.db.database import get_setting
    if get_setting(f"force_pw_change_{user['id']}") == "true":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "请先修改默认密码")
    return user


def admin_user(user: dict = Depends(active_user)) -> dict:
    if not user["is_admin"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    return user
