"""Local authentication — Flask-Login integration, bcrypt password hashing."""
import bcrypt
from flask_login import LoginManager, UserMixin

from web.extensions import get_db
from cyt.models import User

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message_category = "warning"


class AuthUser(UserMixin):
    """Wrapper around the SQLAlchemy User model for Flask-Login."""

    def __init__(self, user: User):
        self.id = user.id
        self.username = user.username
        self.is_admin = user.is_admin
        self.auth_provider = user.auth_provider
        self._user = user

    def get_id(self):
        return str(self.id)


@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    user = db.query(User).get(int(user_id))
    if user is None:
        return None
    return AuthUser(user)


def hash_password(password: str) -> str:
    """Hash a password with bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def check_password(password: str, password_hash: str) -> bool:
    """Verify a password against its bcrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_user(username: str, password: str, is_admin: bool = False,
                auth_provider: str = "local") -> User:
    """Create a new user with hashed password."""
    db = get_db()
    user = User(
        username=username,
        password_hash=hash_password(password) if password else None,
        is_admin=is_admin,
        auth_provider=auth_provider,
    )
    db.add(user)
    db.commit()
    return user


def get_user_count() -> int:
    """Return total number of users."""
    db = get_db()
    return db.query(User).count()
