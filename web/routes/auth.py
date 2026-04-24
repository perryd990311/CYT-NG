"""Authentication blueprint — login, logout, setup, Synology SSO."""
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import login_user, logout_user, login_required, current_user

from web.auth import (
    AuthUser, check_password, create_user, get_user_count,
)
from web.auth.synology_oauth import oauth, synology_sso_enabled, get_or_create_sso_user
from web.extensions import get_db
from cyt.models import User

bp = Blueprint("auth", __name__, url_prefix="/auth")

limiter = Limiter(key_func=get_remote_address, default_limits=[])


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10/minute", methods=["POST"])
def login():
    # Redirect if no users exist yet → force setup
    if get_user_count() == 0:
        return redirect(url_for("auth.setup"))

    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "GET":
        return render_template("login.html", sso_enabled=synology_sso_enabled())

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not username or not password:
        flash("Username and password are required.", "danger")
        return render_template("login.html", sso_enabled=synology_sso_enabled()), 400

    db = get_db()
    user = db.query(User).filter_by(username=username).first()

    if user is None or not user.password_hash or not check_password(password, user.password_hash):
        flash("Invalid username or password.", "danger")
        return render_template("login.html", sso_enabled=synology_sso_enabled()), 401

    user.last_login = datetime.utcnow()
    db.commit()

    login_user(AuthUser(user))
    next_page = request.args.get("next")
    return redirect(next_page or url_for("dashboard.index"))


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Signed out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/setup", methods=["GET", "POST"])
@limiter.limit("5/minute", methods=["POST"])
def setup():
    # Only accessible when no users exist
    if get_user_count() > 0:
        return redirect(url_for("auth.login"))

    if request.method == "GET":
        return render_template("setup.html")

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    password_confirm = request.form.get("password_confirm", "")

    if not username or len(username) < 3:
        flash("Username must be at least 3 characters.", "danger")
        return render_template("setup.html"), 400

    if len(password) < 8:
        flash("Password must be at least 8 characters.", "danger")
        return render_template("setup.html"), 400

    if password != password_confirm:
        flash("Passwords do not match.", "danger")
        return render_template("setup.html"), 400

    user = create_user(username, password, is_admin=True)
    login_user(AuthUser(user))
    flash(f"Admin account '{username}' created. Welcome!", "success")
    return redirect(url_for("dashboard.index"))


# --- Synology DSM OAuth2 SSO ---

@bp.route("/sso/login")
def sso_login():
    if not synology_sso_enabled():
        flash("Synology SSO is not configured.", "warning")
        return redirect(url_for("auth.login"))

    redirect_uri = url_for("auth.sso_callback", _external=True)
    return oauth.synology.authorize_redirect(redirect_uri)


@bp.route("/sso/callback")
def sso_callback():
    if not synology_sso_enabled():
        return redirect(url_for("auth.login"))

    try:
        token = oauth.synology.authorize_access_token()
        userinfo = oauth.synology.userinfo()
    except Exception:
        flash("Synology SSO authentication failed.", "danger")
        return redirect(url_for("auth.login"))

    user = get_or_create_sso_user(userinfo)
    login_user(AuthUser(user))
    return redirect(url_for("dashboard.index"))
