from backend import config
from backend.core.security import create_access_token, hash_password, verify_password
from backend.db.database import connection, utc_now


def ensure_default_admin() -> dict:
    now = utc_now()
    with connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (config.ADMIN_USERNAME,)).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO users(username,password_hash,is_admin,created_at,updated_at) VALUES(?,?,?,?,?)",
                (config.ADMIN_USERNAME, hash_password(config.ADMIN_PASSWORD), 1, now, now),
            )
            row = conn.execute("SELECT * FROM users WHERE username = ?", (config.ADMIN_USERNAME,)).fetchone()
        return _public_user(row)


def authenticate(username: str, password: str) -> tuple[dict, str] | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return None
    user = _public_user(row)
    return user, create_access_token(user["id"], user["username"])


def get_user(user_id: int) -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _public_user(row) if row else None


def change_password(user_id: int, current: str, new: str) -> bool:
    with connection() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row or not verify_password(current, row["password_hash"]):
            return False
        conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (hash_password(new), utc_now(), user_id),
        )
        return True


def change_username(user_id: int, username: str) -> dict:
    with connection() as conn:
        existing = conn.execute("SELECT id FROM users WHERE username=? AND id!=?", (username, user_id)).fetchone()
        if existing:
            raise ValueError("Username already exists")
        conn.execute("UPDATE users SET username=?,updated_at=? WHERE id=?", (username, utc_now(), user_id))
    return get_user(user_id)


def _public_user(row) -> dict:
    return {"id": row["id"], "username": row["username"], "is_admin": bool(row["is_admin"])}
