from functools import wraps
from flask import Blueprint, redirect, request, session, url_for
from supabase_client import supabase

auth_bp = Blueprint("auth", __name__)


def refresh_session_if_needed():
    """Refresh the Supabase token if it has expired."""
    refresh_token = session.get("refresh_token")
    if not refresh_token:
        return False

    try:
        result = supabase.auth.refresh_session(refresh_token)
        session["access_token"]  = result.session.access_token
        session["refresh_token"] = result.session.refresh_token
        return True
    except Exception:
        # Refresh token itself is expired — force re-login
        session.clear()
        return False


def login_required(f):
    """Decorator to protect routes that require authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


@auth_bp.route("/auth/login")
def login():
    response = supabase.auth.sign_in_with_oauth({
        "provider": "google",
        "options": {
            "redirect_to": request.host_url + "auth/callback"
        }
    })
    return redirect(response.url)


@auth_bp.route("/auth/callback")
def callback():
    code = request.args.get("code")

    if not code:
        return redirect(url_for("index"))

    result = supabase.auth.exchange_code_for_session({"auth_code": code})

    session["user"] = {
        "id":    result.user.id,
        "email": result.user.email,
    }
    session["access_token"]  = result.session.access_token
    session["refresh_token"] = result.session.refresh_token  # store refresh token

    return redirect(url_for("index"))


@auth_bp.route("/auth/logout")
def logout():
    supabase.auth.sign_out()
    session.clear()
    return redirect(url_for("index"))