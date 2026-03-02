from __future__ import annotations

from flask import Flask

try:
    from simlib import storage
    from simlib.config import FLASK_SECRET_KEY, MAX_CONTENT_LENGTH
except ModuleNotFoundError:
    from .simlib import storage
    from .simlib.config import FLASK_SECRET_KEY, MAX_CONTENT_LENGTH

try:
    from blueprint import bp
except ImportError:
    from .blueprint import bp


def create_app() -> Flask:
    # Import routes/hooks for side effects (registering on blueprint)
    # Keep imports inside factory to avoid circular imports.
    try:
        import hooks  # noqa: F401
        import routes_admin  # noqa: F401
        import routes_home  # noqa: F401
        import routes_kis  # noqa: F401
        import routes_lis  # noqa: F401
        import routes_modality  # noqa: F401
        import routes_pacs  # noqa: F401
        import routes_session  # noqa: F401
        import routes_workstation  # noqa: F401
    except ImportError:
        from . import hooks  # noqa: F401
        from . import routes_admin  # noqa: F401
        from . import routes_home  # noqa: F401
        from . import routes_kis  # noqa: F401
        from . import routes_lis  # noqa: F401
        from . import routes_modality  # noqa: F401
        from . import routes_pacs  # noqa: F401
        from . import routes_session  # noqa: F401
        from . import routes_workstation  # noqa: F401

    app = Flask(__name__)
    app.secret_key = FLASK_SECRET_KEY
    app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

    # Auto-generate SuS session codes if requested.
    storage.maybe_auto_generate_sessions()

    app.register_blueprint(bp)
    return app
