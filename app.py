from flask import Flask, abort, render_template, redirect, url_for
from markupsafe import Markup, escape
import json
import os
import secrets

from config import DIVISIONS, SPUTTER_TOOLS, TOOLS
from tool_registry import divisions_with_tools, expand_tools, validate_registry
from routes.shared import shared_bp
from routes.giwaxs import giwaxs_bp
from routes.rga import rga_bp
from routes.b30_sputter import b30_sputter_bp, blueprint_name
from routes.b30_ebeam import b30_ebeam_bp
from routes.b30_sem import b30_sem_bp
from routes.electrolyte import electrolyte_bp
from routes.schema_forms import schema_forms_bp

from routes.print_only import print_bp
from routes.uploads import uploads_bp

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
    # A missing-trailing-slash request would otherwise get a 308 redirect built from
    # whatever Host header the proxy in front of this app forwards, which isn't always
    # crucible.lbl.gov -- so avoid that redirect entirely and accept both forms.
    app.url_map.strict_slashes = False

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
    app.register_blueprint(electrolyte_bp, url_prefix="/electrolyte")
    app.register_blueprint(schema_forms_bp, url_prefix="/schema-forms")
    app.register_blueprint(print_bp, url_prefix="/print")
    app.register_blueprint(uploads_bp, url_prefix="/api/uploads")

    # The sputter app used to live at a single URL, before it was split per tool.
    @app.route("/b30-sputter/")
    def b30_sputter_legacy():
        return redirect(url_for(f"{blueprint_name('aja')}.page"))

    tools = expand_tools(TOOLS, SPUTTER_TOOLS, blueprint_name)
    validate_registry(DIVISIONS, tools, set(app.view_functions))
    divisions = divisions_with_tools(DIVISIONS, tools)
    divisions_by_key = {d["key"]: d for d in divisions}

    @app.context_processor
    def inject_divisions():
        return {"nav_divisions": divisions}

    manifest_cache = {"key": None, "entries": {}}

    def vite_manifest():
        """Vite's build manifest, reloaded when a rebuild changes it."""
        path = os.path.join(app.static_folder, "dist", ".vite", "manifest.json")
        try:
            key = (path, os.path.getmtime(path))
        except OSError:
            return {}
        if key != manifest_cache["key"]:
            with open(path) as f:
                manifest_cache["entries"] = json.load(f)
            manifest_cache["key"] = key
        return manifest_cache["entries"]

    @app.context_processor
    def inject_vite_entry():
        def vite_entry(name):
            """<script>/<link> tags for a Vite entry from frontend/vite.config.ts."""
            chunk = next((c for c in vite_manifest().values() if c.get("isEntry") and c.get("name") == name), None)
            if chunk is None:
                app.logger.warning("Vite entry %r not built; run `npm run build` in frontend/", name)
                return Markup(f"<!-- vite entry {escape(name)} missing -->")
            asset = lambda path: url_for("static", filename=f"dist/{path}")
            tags = [f'<link rel="stylesheet" href="{asset(css)}">' for css in chunk.get("css", [])]
            tags.append(f'<script type="module" src="{asset(chunk["file"])}"></script>')
            return Markup("\n".join(tags))
        return {"vite_entry": vite_entry}

    @app.url_defaults
    def add_static_version(endpoint, values):
        """Append the file's mtime to static URLs so a deploy invalidates browser caches."""
        if endpoint != "static" or "filename" not in values:
            return
        try:
            path = os.path.join(app.static_folder, values["filename"])
            values["v"] = int(os.path.getmtime(path))
        except OSError:
            # A missing asset should 404 on its own, not 500 every page that links it.
            pass

    @app.route("/")
    def index():
        return render_template("index.html", divisions=divisions)

    @app.route("/division/<key>")
    def division(key):
        selected = divisions_by_key.get(key)
        if selected is None:
            abort(404)
        return render_template("division.html", division=selected)

    prefix = os.environ.get("SCRIPT_NAME", "")
    if prefix:
        app.wsgi_app = PrefixMiddleware(app.wsgi_app, prefix=prefix)

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
