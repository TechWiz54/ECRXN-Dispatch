import logging
from typing import Any, Dict, List, Optional

import bcrypt
from flask import session

module_logger = logging.getLogger("icad_dispatch.user_handler")


# =============================================================================
# Public API
# =============================================================================
def get_users(db, user_id: Optional[int] = None, username: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
    """
    Fetch users filtered by `user_id` and/or `username`.

    Parameters
    ----------
    db : SQLiteDatabase
        Your database wrapper.
    user_id : int | None
        Filter by primary key.
    username : str | None
        Filter by exact username.

    Returns
    -------
    list[dict] | None
        List of row dicts if any match; otherwise None (preserves your prior behavior).
    """
    base = """
           SELECT
               ur.*
           FROM users ur \
           """

    where, params = [], []
    if user_id is not None:
        where.append("ur.user_id = ?")
        params.append(user_id)
    if username is not None:
        where.append("ur.user_username = ?")
        params.append(username)

    sql = base
    if where:
        sql += " WHERE " + " AND ".join(where)
    # GROUP BY is unnecessary for a single table; leaving out to avoid extra work.

    users_result = db.execute_query(sql, tuple(params) if params else None, fetch_mode="all")

    if not users_result.get("success"):
        module_logger.error("get_users query failed: %s", users_result.get("message"))
        return None

    rows = users_result.get("result") or []
    return rows or None


def password_validate(database_password: Any, given_password: str) -> bool:
    """
    Validate a plaintext password against a stored bcrypt hash.

    Handles SQLite return types that might be `bytes`, `str`, or `memoryview`.

    Parameters
    ----------
    database_password : Any
        Stored bcrypt hash (ideally bytes). If str, it will be encoded as UTF-8.
    given_password : str
        Plaintext password from the user.

    Returns
    -------
    bool
        True if the password matches; False otherwise.
    """
    if database_password is None:
        return False

    # Normalize to bytes for bcrypt
    if isinstance(database_password, memoryview):
        database_password = database_password.tobytes()
    elif isinstance(database_password, str):
        database_password = database_password.encode("utf-8")

    try:
        return bcrypt.checkpw(given_password.encode("utf-8"), database_password)
    except Exception as e:
        module_logger.error("bcrypt check failed: %s", e)
        return False


def authenticate_user(db, username: str, password: str) -> Dict[str, Any]:
    """
    Authenticate a user by username and password, setting Flask session keys on success.

    Returns
    -------
    dict
        {
          "success": bool,
          "message": str,
          "result": user_row (on success)
        }
    """
    users = get_users(db, username=username)
    if users is None or not users:
        return {"success": False, "message": "User not found."}

    user_row = users[0]
    if not password_validate(user_row.get("user_password"), password):
        module_logger.warning("Password Incorrect: %s", username)
        return {"success": False, "message": "Invalid Username or Password"}

    if not set_session_keys(user_row):
        module_logger.error("Cannot set session values for logged in user")
        return {"success": False, "message": "Internal Error"}

    return {"success": True, "message": "Authenticated Successfully", "result": user_row}


def set_session_keys(user_data: Dict[str, Any]) -> bool:
    """
    Store minimal authenticated user context in Flask session.

    Parameters
    ----------
    user_data : dict
        Row dict from `users`.

    Returns
    -------
    bool
        True on success; False otherwise.
    """
    try:
        username = user_data.get("user_username")
        user_id = user_data.get("user_id")
        if not username:
            raise ValueError("No Username in row")

        session.update(
            user_id=user_id,
            username=username,
            authenticated=True,
        )
        return True

    except (IndexError, AttributeError, KeyError, ValueError) as e:
        module_logger.error("Session set failed: %s", e, exc_info=True)
        return False
    except Exception as e:
        module_logger.error("Unexpected error setting session: %s", e, exc_info=True)
        return False


def update_user_password(db, username: str, password: str) -> Dict[str, Any]:
    """
    Update a user's password (bcrypt hash) by username.

    Parameters
    ----------
    db : SQLiteDatabase
    username : str
    password : str

    Returns
    -------
    dict
        Standard `execute_commit` result. (Uses return_count=True for clarity.)
    """
    hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    q = "UPDATE users SET user_password = ? WHERE user_username = ?"
    return db.execute_commit(q, (hashed_password, username), return_row_id=False, return_count=True)


def user_change_password(db, username: str, current_password: str, new_password: str) -> Dict[str, Any]:
    """
    Change a user's password after verifying the current password.

    Parameters
    ----------
    db : SQLiteDatabase
    username : str
    current_password : str
    new_password : str

    Returns
    -------
    dict
        {
          "success": bool,
          "message": str
        }
    """
    users = get_users(db, username=username)
    if users is None or not users:
        return {"success": False, "message": "Username or password incorrect"}

    user_row = users[0]
    if not password_validate(user_row.get("user_password"), current_password):
        module_logger.warning("Password Incorrect for user '%s'", username)
        return {"success": False, "message": "Invalid Username or Password"}

    up = update_user_password(db, username, new_password)
    if up.get("success"):
        # Optionally, enforce that a row was affected:
        # if up.get("result", 0) == 0: return {"success": False, "message": "No password updated."}
        return {"success": True, "message": "Password Changed Successfully"}
    return {"success": False, "message": f"Password Change Failed. {up.get('message')}"}


# =============================================================================
# Forgotten password (needs access to the server itself)
# =============================================================================
def reset_admin_password(db, new_password: str, username: Optional[str] = None) -> Dict[str, Any]:
    """Set a user's password without the old one (admin = ROOT_USERNAME, else the first account)."""
    if not new_password or len(new_password) < 8:
        return {"success": False, "message": "Use at least 8 characters."}
    users = get_users(db, username=username) if username else get_users(db)
    if not users:
        return {"success": False, "message": f"No user named '{username}'." if username else "No users yet."}
    target = users[0]["user_username"]
    res = update_user_password(db, target, new_password)
    if not res.get("success"):
        return {"success": False, "message": res.get("message") or "Couldn't save."}
    # sign out every "remember me" device
    db.execute_commit("DELETE FROM user_remember_tokens WHERE user_id = ?", (users[0]["user_id"],))
    return {"success": True, "message": f"Password for '{target}' changed.", "username": target}


def apply_env_password_reset(db, env_path: str) -> None:
    """
    RESET_ADMIN_PASSWORD=<new> in .env -> set that as the admin password on start-up,
    then remove the line from .env so the plain-text password doesn't stay on disk.
    """
    import os
    new = (os.getenv("RESET_ADMIN_PASSWORD") or "").strip()
    if not new:
        return
    res = reset_admin_password(db, new, os.getenv("ROOT_USERNAME") or None)
    if res["success"]:
        module_logger.warning("Admin password was reset from RESET_ADMIN_PASSWORD in .env (%s).", res["username"])
    else:
        module_logger.error("RESET_ADMIN_PASSWORD in .env was not applied: %s", res["message"])
    os.environ.pop("RESET_ADMIN_PASSWORD", None)
    try:
        with open(env_path, encoding="utf-8") as fh:
            lines = fh.readlines()
        with open(env_path, "w", encoding="utf-8") as fh:
            fh.writelines(l for l in lines if not l.strip().startswith("RESET_ADMIN_PASSWORD"))
    except OSError as e:
        module_logger.error("Couldn't remove RESET_ADMIN_PASSWORD from %s - delete that line by hand: %s", env_path, e)
