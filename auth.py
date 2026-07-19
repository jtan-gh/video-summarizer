from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, current_app, redirect, request, session, url_for

from supabase_client import supabase

auth_bp = Blueprint("auth", __name__)

# Supabase's own access tokens default to a 1 hour lifetime
SUPABASE_INACTIVITY_TIMEOUT = timedelta(hours=1)

INACTIVITY_WARNING_OFFSET = timedelta(minutes=5)

ACCESS_TOKEN_LIFETIME = timedelta(hours=1)
TOKEN_REFRESH_MARGIN = timedelta(minutes=10)
STORE_LIFETIME = SUPABASE_INACTIVITY_TIMEOUT + timedelta(minutes=30)

# Endpoints that must stay reachable for someone who isn't logged in yet.
EXEMPT_ENDPOINTS = {"auth.login", "auth.callback", "auth.logout", "static"}

# Endpoints that run while logged in but must NOT count as "activity".
PASSIVE_ENDPOINTS = {"auth.status"}


def refresh_session_if_needed():
    """Refresh the Supabase token if it has expired."""
    refresh_token = session.get("refresh_token")
    if not refresh_token:
        return False

    try:
        result = supabase.auth.refresh_session(refresh_token)
        session["access_token"] = result.session.access_token
        session["refresh_token"] = result.session.refresh_token
        return True
    except Exception:
        # Refresh token itself is expired — force re-login
        session.clear()
        return False


def _maybe_refresh_token():
    refreshed_at = session.get("token_refreshed_at")
    if not refreshed_at:
        return

    refreshed_at_dt = datetime.fromisoformat(refreshed_at)
    if datetime.now(timezone.utc) - refreshed_at_dt > (
        ACCESS_TOKEN_LIFETIME - TOKEN_REFRESH_MARGIN
    ):
        if refresh_session_if_needed():
            session["token_refreshed_at"] = datetime.now(timezone.utc).isoformat()
            session.modified = True


def login_required(f):
    """Decorator to protect routes that require authentication."""

    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)

    return decorated


def _wipe_session(response=None):
    session.clear()
    session.modified = True
    if response is not None:
        response.delete_cookie(current_app.config.get("SESSION_COOKIE_NAME", "session"))
    return response


@auth_bp.route("/auth/login")
def login():
    response = supabase.auth.sign_in_with_oauth(
        {"provider": "google", "options": {"redirect_to": request.host_url + "auth/callback"}}
    )
    return redirect(response.url)


@auth_bp.route("/auth/callback")
def callback():
    code = request.args.get("code")

    if not code:
        return redirect(url_for("index"))

    result = supabase.auth.exchange_code_for_session({"auth_code": code})

    session.permanent = True
    session["user"] = {
        "id": result.user.id,
        "email": result.user.email,
    }
    session["access_token"] = result.session.access_token
    session["refresh_token"] = result.session.refresh_token
    session["last_activity"] = datetime.now(timezone.utc).isoformat()
    session["token_refreshed_at"] = datetime.now(timezone.utc).isoformat()

    return redirect(url_for("index"))


@auth_bp.route("/auth/logout")
def logout():
    try:
        supabase.auth.sign_out()
    except Exception:
        pass

    response = redirect(url_for("index"))
    _wipe_session(response)
    return response


@auth_bp.route("/auth/status")
def status():
    if "user" not in session:
        return {"authenticated": False}, 401

    expires_in = None
    last_activity = session.get("last_activity")
    if last_activity:
        deadline = datetime.fromisoformat(last_activity) + SUPABASE_INACTIVITY_TIMEOUT
        expires_in = max(0, int((deadline - datetime.now(timezone.utc)).total_seconds()))

    return {"authenticated": True, "expires_in": expires_in}, 200


@auth_bp.route("/auth/last_activity", methods=["POST"])
def last_activity():
    if "user" not in session:
        return {"authenticated": False}, 401

    session["last_activity"] = datetime.now(timezone.utc).isoformat()
    session.modified = True
    return {
        "authenticated": True,
        "expires_in": int(SUPABASE_INACTIVITY_TIMEOUT.total_seconds()),
    }, 200


@auth_bp.before_app_request
def check_inactivity():
    if request.endpoint in EXEMPT_ENDPOINTS:
        return

    if "user" not in session:
        return

    now = datetime.now(timezone.utc)
    last_activity = session.get("last_activity")

    if last_activity:
        last_activity_dt = datetime.fromisoformat(last_activity)
        if now - last_activity_dt > SUPABASE_INACTIVITY_TIMEOUT:
            was_status_check = request.endpoint == "auth.status"
            _wipe_session()
            if was_status_check:
                return {"authenticated": False, "reason": "inactive"}, 401
            return redirect(url_for("auth.login"))

    if request.endpoint not in PASSIVE_ENDPOINTS:
        session["last_activity"] = now.isoformat()
        session.modified = True

    _maybe_refresh_token()
