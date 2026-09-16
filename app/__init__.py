"""Application factory.

    from app import create_app
    app = create_app()

Gunicorn entry point: `gunicorn "app:create_app()"`.
"""

from flask import Flask
from flask_compress import Compress

from .config import Config

compress = Compress()


def create_app(config_object=Config, **overrides) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object)
    app.config.update(overrides)
    app.json.sort_keys = False  # keep id/name first in responses, not alphabetical

    from . import db
    from .api import comparisons, errors, simulations, venues
    from . import pages

    db.register(app)
    db.init_db(app)

    errors.register(app)
    app.register_blueprint(venues.bp)
    app.register_blueprint(simulations.bp)
    app.register_blueprint(comparisons.bp)
    app.register_blueprint(pages.bp)

    compress.init_app(app)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app
