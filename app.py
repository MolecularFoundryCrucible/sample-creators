from flask import Flask, render_template
import secrets

from routes.shared import shared_bp
from routes.giwaxs import giwaxs_bp
from routes.rga import rga_bp


def create_app():
    app = Flask(__name__)
    app.secret_key = secrets.token_hex(32)

    app.register_blueprint(shared_bp)
    app.register_blueprint(giwaxs_bp, url_prefix="/giwaxs")
    app.register_blueprint(rga_bp, url_prefix="/rga")

    @app.route("/")
    def index():
        return render_template("index.html")

    return app


if __name__ == "__main__":
    app = create_app()
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
