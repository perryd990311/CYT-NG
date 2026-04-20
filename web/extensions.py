"""Shared Flask extension instances — imported by app factory and blueprints."""
from flask_socketio import SocketIO
from sqlalchemy.orm import scoped_session, sessionmaker

socketio = SocketIO()

# SQLAlchemy session managed manually (models already use declarative_base)
_Session = None


def init_db(app):
    """Bind engine + create tables using cyt.models, expose scoped session."""
    global _Session
    from cyt.models import Base, init_db as _init

    engine, Session = _init(
        app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", "")
    )
    _Session = scoped_session(Session)
    return engine


def get_db():
    """Return the current scoped session."""
    return _Session()
