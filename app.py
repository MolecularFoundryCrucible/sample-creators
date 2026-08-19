from flask import Flask, render_template, redirect, url_for
import os
import secrets

from config import SPUTTER_TOOLS
from routes.shared import shared_bp
from routes.giwaxs import giwaxs_bp
from routes.rga import rga_bp
from routes.b30_sputter import b30_sputter_bp, blueprint_name
from routes.b30_ebeam import b30_ebeam_bp
from routes.b30_sem import b30_sem_bp

from routes.print_only import print_bp

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
    # One page per sputter tool, all served by the same blueprint.
    for tool_key, tool in SPUTTER_TOOLS.items():
        app.register_blueprint(
            b30_sputter_bp,
            url_prefix=tool["url_prefix"],
            name=blueprint_name(tool_key),
        )
    app.register_blueprint(b30_sem_bp, url_prefix="/b30-sem")
    app.register_blueprint(b30_ebeam_bp, url_prefix="/b30-ebeam")
    app.register_blueprint(print_bp, url_prefix="/print")

    # The sputter app used to live at a single URL, before it was split per tool.
    @app.route("/b30-sputter/")
    def b30_sputter_legacy():
        return redirect(url_for(f"{blueprint_name('aja')}.page"))

    @app.context_processor
    def inject_sputter_tools():
        return {"sputter_tools": SPUTTER_TOOLS, "sputter_blueprint_name": blueprint_name}

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
