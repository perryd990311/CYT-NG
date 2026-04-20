"""CYT-NG Flask application factory."""
from flask import Flask

from web.config import Config
from web.extensions import socketio, init_db


def create_app(config_class=Config):
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config.from_object(config_class)

    # Extensions
    socketio.init_app(app, async_mode=app.config.get("SOCKETIO_ASYNC_MODE", "gevent"))
    init_db(app)

    # Authentication
    from web.auth import login_manager
    login_manager.init_app(app)

    from web.auth.synology_oauth import init_oauth
    init_oauth(app)

    # Rate limiting
    from web.routes.auth import limiter
    limiter.init_app(app)

    # Blueprints
    from web.routes.auth import bp as auth_bp
    from web.routes.dashboard import bp as dashboard_bp
    from web.routes.analysis import bp as analysis_bp
    from web.routes.devices import bp as devices_bp
    from web.routes.reports import bp as reports_bp
    from web.routes.settings import bp as settings_bp
    from web.routes.sensors import bp as sensors_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(analysis_bp)
    app.register_blueprint(devices_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(sensors_bp)

    # Background scheduler (ingestion + fingerprinting) — only when serving
    if not app.config.get("TESTING"):
        from cyt.tasks import init_scheduler
        init_scheduler(app)

    # Teardown — remove scoped session after each request
    @app.teardown_appcontext
    def shutdown_session(exception=None):
        from web.extensions import _Session
        if _Session is not None:
            _Session.remove()

    return app
