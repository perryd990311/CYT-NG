"""Synology DSM OAuth2 SSO integration."""

import os
from datetime import datetime, timezone

from authlib.integrations.flask_client import OAuth

from web.extensions import get_db
from cyt.models import User

oauth = OAuth()

# Configured lazily in init_oauth() — only when env vars are set
_synology_enabled = False


def synology_sso_enabled() -> bool:
    """Check whether Synology SSO environment vars are configured."""
    return _synology_enabled


def init_oauth(app):
    """Register Synology DSM as an OAuth2 provider if env vars are set."""
    global _synology_enabled

    dsm_url = os.environ.get("SYNOLOGY_DSM_URL", "").rstrip("/")
    client_id = os.environ.get("SYNOLOGY_OAUTH_CLIENT_ID", "")
    client_secret = os.environ.get("SYNOLOGY_OAUTH_CLIENT_SECRET", "")

    if not all([dsm_url, client_id, client_secret]):
        _synology_enabled = False
        return

    oauth.init_app(app)
    oauth.register(
        name="synology",
        client_id=client_id,
        client_secret=client_secret,
        authorize_url=f"{dsm_url}/webman/sso/SSOOauth.cgi",
        access_token_url=f"{dsm_url}/webman/sso/SSOAccessToken.cgi",
        userinfo_endpoint=f"{dsm_url}/webman/sso/SSOUserInfo.cgi",
        client_kwargs={"scope": "user_info"},
    )
    _synology_enabled = True


def get_or_create_sso_user(userinfo: dict) -> User:
    """Find or create a local user record from Synology SSO userinfo."""
    username = userinfo.get("name") or userinfo.get("user", "unknown")

    db = get_db()
    user = db.query(User).filter_by(username=username, auth_provider="synology_sso").first()

    if user is None:
        user = User(
            username=username,
            password_hash=None,
            is_admin=False,
            auth_provider="synology_sso",
        )
        db.add(user)

    user.last_login = datetime.now(timezone.utc)
    db.commit()
    return user
