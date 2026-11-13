import os
import threading
import time

from flask import Blueprint, request, jsonify, flash, redirect, url_for, render_template, current_app, session

from lib.cookie_module import issue_cookie
from lib.user_module import authenticate_user, user_change_password, get_users
from routes.decorators import login_required, csrf_protect

auth = Blueprint('auth', __name__)

# ── Brute-force protection: too many wrong passwords from one address locks it out for a while ──
MAX_FAILS = int(os.getenv("LOGIN_MAX_ATTEMPTS", "8"))
# per account too, so faking the client address (X-Forwarded-For) doesn't get unlimited tries
MAX_FAILS_USER = MAX_FAILS * 4
LOCK_S = int(os.getenv("LOGIN_LOCKOUT_MINUTES", "15")) * 60
_fails: dict[str, list[float]] = {}
_fails_lock = threading.Lock()
MIN_PASSWORD_LEN = 8


def _client_ip() -> str:
    return request.remote_addr or "?"       # ProxyFix already applied X-Forwarded-For


def _locked_for(key: str, limit: int) -> int:
    """Seconds this address / account must still wait (0 = may try)."""
    now = time.time()
    with _fails_lock:
        recent = [t for t in _fails.get(key, []) if now - t < LOCK_S]
        _fails[key] = recent
        if len(recent) >= limit:
            return int(LOCK_S - (now - recent[0])) + 1
    return 0


def _note_fail(*keys: str) -> None:
    with _fails_lock:
        for key in keys:
            _fails.setdefault(key, []).append(time.time())
        if len(_fails) > 10000:            # don't grow forever under a spray attack
            for k in list(_fails)[:5000]:
                _fails.pop(k, None)

@auth.route('/login', methods=['POST'])
@csrf_protect
def auth_login():
    username = request.form.get("loginEmail", "").strip()
    password = request.form.get("loginPassword", "")
    remember = request.form.get("rememberMe") is not None     # ✅ checkbox

    if not username or not password:
        return jsonify(success=False, message="Malformed Request"), 400

    ip = _client_ip()
    user_key = "user:" + username.lower()
    wait = max(_locked_for(ip, MAX_FAILS), _locked_for(user_key, MAX_FAILS_USER))
    if wait:
        current_app.config["logger"].warning("Login blocked for %s: too many failed attempts", ip)
        return jsonify(success=False, message=f"Too many failed logins. Try again in {wait // 60 + 1} minutes."), 429

    auth_result = authenticate_user(current_app.config['db'], username, password)
    if not auth_result.get('success'):
        _note_fail(ip, user_key)
        current_app.config["logger"].warning("Failed login for '%s' from %s", username[:64], ip)
        return jsonify(success=False, message="Invalid credentials"), 401

    with _fails_lock:
        _fails.pop(ip, None)
        _fails.pop(user_key, None)
    # New session id on login (stops session fixation)
    current_app.session_interface.regenerate(session)
    # Still using the password from .env? Nudge them to change it.
    session["default_password"] = bool(os.getenv("ROOT_PASSWORD")) and password == os.getenv("ROOT_PASSWORD")

    user_data = auth_result.get('result')

    resp = jsonify(success=True, message="Authenticated")

    # ── add the remember-me cookie, only if box ticked ───────────────────
    if remember:
        issue_cookie(resp, current_app.config["db"], user_data.get('user_id'))

    return resp


@auth.route("/logout", methods=['GET'])
def auth_logout():
    db = current_app.config["db"]
    if session.get("user_id"):
        db.execute_commit("DELETE FROM user_remember_tokens WHERE user_id=?", (session["user_id"],))
    session.clear()
    resp = jsonify(success=True)
    resp.delete_cookie("remember_me", path="/")
    return redirect(url_for("base_site.base_site_login"))


@auth.route("/change_password", methods=["POST"])
@login_required
@csrf_protect
def auth_change_password():
    log = current_app.config["logger"]

    # helper to decide output style
    wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    username = session.get("username")
    current_password = request.form.get("currentPassword", "")
    new_password     = request.form.get("newPassword", "")

    if not username:
        msg = "No username provided."
        log.error(msg)
        if not wants_json:
            return jsonify(success=False, message=msg), 400
        flash(msg, "error")
        return redirect(url_for("dashboard.dashboard_index"))

    if new_password and len(new_password) < MIN_PASSWORD_LEN:
        msg = f"Use at least {MIN_PASSWORD_LEN} characters for the new password."
        if wants_json:
            return jsonify(success=False, message=msg), 400
        flash(msg, "danger")
        return redirect(url_for("dashboard.dashboard_change_password"))

    if not new_password:
        msg = "No new password provided."
        log.error(msg)
        if wants_json:
            return jsonify(success=False, message=msg), 400
        flash(msg, "danger")
        return redirect(url_for("dashboard.dashboard_index"))

    # replace "admin" with session username if you support per-user change
    result = user_change_password(
        current_app.config["db"],
        username,
        current_password,
        new_password,
    )

    log.debug(result["message"])

    if result["success"]:
        session["default_password"] = False
        # sign out "remember me" on other devices
        uid = session.get("user_id")
        if uid:
            current_app.config["db"].execute_commit("DELETE FROM user_remember_tokens WHERE user_id=?", (uid,))

    if wants_json:
        status = 200 if result["success"] else 400
        return jsonify(success=result["success"], message=result["message"]), status

    flash(result["message"], "success" if result["success"] else "danger")
    return redirect(url_for("dashboard.dashboard_index"))
