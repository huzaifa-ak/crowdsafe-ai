"""Application factory.

    from app import create_app
    app = create_app()

Gunicorn entry point: `gunicorn "app:create_app()"`.
"""

import mimetypes

from flask import Flask
from flask_compress import Compress

from .config import Config

compress = Compress()


def create_app(config_object=Config, **overrides) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object)
    app.config.update(overrides)
    app.json.sort_keys = False  # keep id/name first in responses, not alphabetical

    # Windows reads MIME types from the registry, where .js is commonly
    # registered as text/plain. Browsers refuse to execute a module script
    # served that way, so without this every page loads with its JavaScript
    # silently discarded and the canvas never draws. Linux, and so Render, has
    # the right type already, which is what makes this fail on one machine and
    # not the other.
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/css", ".css")

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

    if app.config.get("SEED_EXAMPLES"):
        from .seed import seed_if_empty
        seed_if_empty(app)

    compress.init_app(app)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app
