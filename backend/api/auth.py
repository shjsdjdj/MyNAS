from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status

from backend import config
from backend.api.dependencies import current_user
from backend.core.security import COOKIE_NAME, client_ip, decode_access_token, login_rate_limiter, revoke_access_token
from backend.db.database import audit, get_setting, set_setting
from backend.models.auth import ChangePasswordRequest, LoginRequest
from backend.services.auth_service import authenticate, change_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response):
    ip = client_ip(request)
    login_rate_limiter.check(ip)
    result = authenticate(payload.username, payload.password)
    if not result:
        login_rate_limiter.record_failure(ip)
        audit("login_failed", ip, detail=payload.username)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    login_rate_limiter.clear(ip)
    user, token = result
    audit("login", ip, user["id"])
    password_change_required = payload.password == "admin"
    if password_change_required:
        set_setting(f"force_pw_change_{user['id']}", "true")
    response.set_cookie(
        COOKIE_NAME, token, httponly=True, secure=config.COOKIE_SECURE,
        samesite="strict", max_age=config.JWT_EXPIRE_HOURS * 3600, path="/",
    )
    return {"token_type": "cookie", "user": user, "password_change_required": password_change_required}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    user: dict = Depends(current_user),
    cookie_token: str = Cookie(alias=COOKIE_NAME),
):
    payload = decode_access_token(cookie_token)
    revoke_access_token(cookie_token, payload["exp"])
    audit("logout", client_ip(request), user["id"])
    response.delete_cookie(
        COOKIE_NAME, path="/", httponly=True, secure=config.COOKIE_SECURE, samesite="strict"
    )
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return {
        **user,
        "password_change_required": get_setting(f"force_pw_change_{user['id']}") == "true",
    }


@router.post("/change-password")
def update_password(payload: ChangePasswordRequest, request: Request, user: dict = Depends(current_user)):
    if payload.new_password == "admin":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "新密码不能为默认密码 'admin'")
    if not change_password(user["id"], payload.current_password, payload.new_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "当前密码错误")
    set_setting(f"force_pw_change_{user['id']}", "false")
    audit("password_change", client_ip(request), user["id"])
    return {"ok": True}
