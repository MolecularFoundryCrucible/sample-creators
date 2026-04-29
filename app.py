from flask import Flask, render_template
import os
import secrets

from routes.shared import shared_bp
from routes.giwaxs import giwaxs_bp
from routes.rga import rga_bp
from routes.b30_sputter import b30_sputter_bp

class PrefixMiddleware:
    """Set SCRIPT_NAME so Flask generates correct URLs behind a reverse proxy."""

    def __init__(self, app, prefix=""):
        self.app = app
        self.prefix = prefix.rstrip("/")

    def __call__(self, environ, start_response):
        if self.prefix:
            environ["SCRIPT_NAME"] = self.prefix
            path = environ.get("PATH_INFO", "")
            if path.startswith(self.prefix):
                environ["PATH_INFO"] = path[len(self.prefix) :]
        return self.app(environ, start_response)


def create_app():
    app = Flask(__name__)
    app.secret_key = secrets.token_hex(32)

    app.register_blueprint(shared_bp)
    app.register_blueprint(giwaxs_bp, url_prefix="/giwaxs")
    app.register_blueprint(rga_bp, url_prefix="/rga")
    app.register_blueprint(b30_sputter_bp, url_prefix="/b30-sputter")
    @app.route("/")
    def index():
        return render_template("index.html")

    prefix = os.environ.get("SCRIPT_NAME", "")
    if prefix:
        app.wsgi_app = PrefixMiddleware(app.wsgi_app, prefix=prefix)

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
