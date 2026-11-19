import configparser
import json
import os
import re
import logging
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

import requests
from flask import Blueprint, request, jsonify, session

from config import PRINT_CONFIG
from crucible import CrucibleClient
from crucible.config import config as _cruc_config
from crucible.errors import CrucibleAPIError, NotSignedInError
from crucible.utils.identifiers import IdentifierNotFoundError
try:
    from crucible.auth.session import carry_sign_in
except ImportError:
    carry_sign_in = None

DEFAULT_CRUCIBLE_API_URL = "https://crucible.lbl.gov/api/v4"


def get_crucible_hub_url() -> str:
    env_url = (os.environ.get("CRUCIBLE_HUB_URL") or "").strip()
    if env_url:
        return env_url.rstrip("/")
    try:
        from crucible.config import get_hub_url
        cfg_url = (get_hub_url() or "").strip()
        if cfg_url:
            return cfg_url.rstrip("/")
    except Exception:
        pass
    return "https://crucible.lbl.gov/hub"


def hub_dataset_url(dataset_mfid: str) -> str:
    return f"{get_crucible_hub_url()}/datasets/{dataset_mfid}"


def _maybe_carry_sign_in(target_url: str) -> None:
    if (target_url or "").rstrip("/") == "https://crucible.lbl.gov/api/v4":
        try:
            if carry_sign_in is not None:
                carry_sign_in("https://crucible.lbl.gov/api/v3", "https://crucible.lbl.gov/api/v4")
        except Exception:
            pass


def _read_ini_api_key():
    path = _cruc_config.config_file_path
    if not path.exists():
        return None
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path)
    if "crucible" in parser:
        val = parser["crucible"].get("api_key", "").strip().strip('"').strip("'")
        return val or None
    return None


class _DeferredCredential:
    """Defers NotSignedInError until an unmocked HTTP request is prepared."""

    kind = "deferred"
    source: str | None = None

    def __init__(self, client):
        self._client = client

    def bearer(self):
        self._client._ensure_credential()
        return self._client._credential.bearer()


class _DeferredCrucibleClient(CrucibleClient):
    """CrucibleClient that defers NotSignedInError from module import to HTTP request time."""

    _UNCONFIGURED = "__unconfigured_crucible_client__"

    def __init__(self, api_url=None, api_key=None):
        if not (_cruc_config._data.get("api_key") or "").strip():
            _cruc_config._data.pop("api_key", None)
            _cruc_config._sources.pop("api_key", None)
        if not (_cruc_config._data.get("api_url") or "").strip():
            _cruc_config._data.pop("api_url", None)
            _cruc_config._sources.pop("api_url", None)

        env_url = (os.environ.get("CRUCIBLE_API_URL") or "").strip() or None
        env_key = (os.environ.get("CRUCIBLE_API_KEY") or "").strip() or None
        resolved_url = (api_url or "").strip() or env_url or _cruc_config.api_url or DEFAULT_CRUCIBLE_API_URL
        resolved_key = (api_key or "").strip() if isinstance(api_key, str) else api_key
        resolved_key = resolved_key or env_key or None
        _maybe_carry_sign_in(resolved_url)
        try:
            super().__init__(api_url=resolved_url, api_key=resolved_key)
        except NotSignedInError:
            # If CRUCIBLE_API_KEY="" was set in env/.env, Config._load() skipped config.ini.
            # Check config.ini only AFTER CrucibleClient(api_key=None) failed so OAuth wins first.
            ini_key = _read_ini_api_key()
            if ini_key:
                super().__init__(api_url=resolved_url, api_key=ini_key)
                return
            super().__init__(api_url=resolved_url, api_key=self._UNCONFIGURED)
            self._credential = _DeferredCredential(self)
            self.api_key = None

    def _ensure_credential(self):
        if self._credential is not None and not isinstance(self._credential, _DeferredCredential):
            return
        from crucible.client import _resolve_credential

        self._config.reload()
        if not (self._config._data.get("api_key") or "").strip():
            self._config._data.pop("api_key", None)
            self._config._sources.pop("api_key", None)
        if not (self._config._data.get("api_url") or "").strip():
            self._config._data.pop("api_url", None)
            self._config._sources.pop("api_url", None)

        env_url = (os.environ.get("CRUCIBLE_API_URL") or "").strip() or None
        target_url = env_url or (self.api_url or "").strip() or self._config.api_url or DEFAULT_CRUCIBLE_API_URL
        env_key = (os.environ.get("CRUCIBLE_API_KEY") or "").strip() or None
        _maybe_carry_sign_in(target_url)
        try:
            cred = _resolve_credential(self._config, target_url.rstrip("/"), env_key)
        except NotSignedInError:
            ini_key = _read_ini_api_key()
            if not ini_key:
                raise
            cred = _resolve_credential(self._config, target_url.rstrip("/"), ini_key)
        self.api_url = target_url.rstrip("/")
        self._credential = cred
        self.api_key = cred.key if cred.kind == "api_key" else None

    def _request(self, method, endpoint, *args, **kwargs):
        self._ensure_credential()
        return super()._request(method, endpoint, *args, **kwargs)


cruc_client = _DeferredCrucibleClient(
    api_url=(os.environ.get("CRUCIBLE_API_URL") or "").strip() or None,
    api_key=(os.environ.get("CRUCIBLE_API_KEY") or "").strip() or None,
)

# config.py names instruments by their prod MFID. An environment whose instruments were
# registered separately (staging) maps prod MFIDs to its own, e.g. '{"<prod>": "<staging>"}'.
_INSTRUMENT_MFID_OVERRIDES = json.loads(os.environ.get("INSTRUMENT_MFID_OVERRIDES") or "{}")


def instrument_mfid(prod_mfid):
    return _INSTRUMENT_MFID_OVERRIDES.get(prod_mfid, prod_mfid)


shared_bp = Blueprint("shared", __name__)


_PRINTER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def resolve_printer(printer):
    """Turn user input into a validated printer_id.

    Accepts either "b30-113" or the fully qualified "crucible-printer/b30-113"
    (an older config value or a copy-pasted MQTT topic). Only validates the
    shape crucible-api itself requires for printer_id (letters, digits, '_',
    '-', 1-64 chars) -- which printers actually exist is what GET
    /print/printers (and the print page's dropdown built from it) is for, not
    a local allowlist, which would just go stale against the real fleet.
    """
    prefix = PRINT_CONFIG["printer_topic_prefix"] + "/"
    name = str(printer or "").strip()
    if name.startswith(prefix):
        name = name[len(prefix):]
    if not _PRINTER_ID_RE.fullmatch(name):
        raise ValueError(f"'{name}' is not a valid printer id")
    return name


class PrinterTimeoutError(RuntimeError):
    """Raised when a print job gets no result within the server's wait window."""


def publish_barcode(printer, mfid, name=""):
    """Send one label job to a Crucible label printer via crucible-api.

    Raises PrinterTimeoutError if the printer didn't confirm within the
    server's wait window (likely offline), or RuntimeError if it explicitly
    reported failure.
    """
    printer_id = resolve_printer(printer)
    result = cruc_client.print.barcode(printer_id=printer_id, mfid=mfid, name=name)
    if result.get("status") == "ok":
        return result
    detail = result.get("detail") or f"Printer reported status={result.get('status')}"
    if result.get("status") == "timeout":
        raise PrinterTimeoutError(detail)
    raise RuntimeError(detail)


def get_next_serial_sample(sample_prefix, sample_type, project):
    project_samples = cruc_client.samples.list(
        project_id=project, sample_type=sample_type, limit=None
    )
    filtered = [x["sample_name"] for x in project_samples if x["sample_name"].startswith(sample_prefix)]
    nums = sorted(int(x.replace(sample_prefix, "")) for x in filtered)
    if not nums:
        return 1
    return nums[-1] + 1


def format_user(user, fallback=""):
    if not isinstance(user, dict):
        return fallback
    full_name = " ".join(
        part.strip()
        for part in (user.get("first_name", ""), user.get("last_name", ""))
        if isinstance(part, str) and part.strip()
    )
    username = user.get("username")
    if full_name and username:
        return f"{full_name} (@{username})"
    if username:
        return f"@{username}"
    return full_name or fallback


@shared_bp.route("/api/sample-types", methods=["GET"])
def sample_types():
    """Distinct sample types already used in the selected project, for the type typeahead."""
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401
    project = user.get("selected_project", "")
    if not project:
        return jsonify([])
    samples = cruc_client.samples.list(project_id=project, limit=None)
    return jsonify(sorted({s["sample_type"] for s in samples if s.get("sample_type")}))


@shared_bp.route("/api/user/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    user_ref = str(data.get("user_ref") or data.get("email") or "").strip()
    if not user_ref:
        return jsonify({"error": "Email or username required"}), 400

    try:
        user_info = cruc_client.users.get(user_ref)
    except NotSignedInError as e:
        logger.error(f"Crucible client not signed in: {e}")
        return jsonify({"error": str(e)}), 500
    except (IdentifierNotFoundError, ValueError):
        return jsonify({"error": "User not found"}), 404
    except CrucibleAPIError as e:
        if e.status == 404:
            return jsonify({"error": "User not found"}), 404
        logger.error(f"Crucible error while fetching user info ({e.status}): {e}")
        return jsonify({"error": f"Crucible error ({e.status})"}), 502
    except requests.HTTPError as e:
        status = getattr(e.response, "status_code", None)
        if status == 404:
            return jsonify({"error": "User not found"}), 404
        logger.error(f"HTTP error while fetching user info: {e}")
        return jsonify({"error": f"Crucible error ({status or 502})"}), 502
    except requests.RequestException as e:
        logger.error(f"Upstream request failed while fetching user info: {e}")
        return jsonify({"error": "Crucible upstream request failed"}), 502
    except Exception as e:
        logger.error(f"Error occurred while fetching user info: {e}")
        return jsonify({"error": "User not found"}), 404

    if not user_info:
        return jsonify({"error": "User not found"}), 404

    user_unique_id = user_info.get("unique_id") or user_info.get("orcid") or user_ref
    user_name = format_user(user_info, user_unique_id)

    try:
        projects = cruc_client.users.list_projects(user_unique_id, limit=None)
    except NotSignedInError as e:
        logger.error(f"Crucible client not signed in: {e}")
        return jsonify({"error": str(e)}), 500
    except CrucibleAPIError as e:
        logger.error(f"Crucible error while fetching user projects ({e.status}): {e}")
        return jsonify({"error": f"Crucible error ({e.status})"}), 502
    except requests.HTTPError as e:
        status = getattr(e.response, "status_code", None)
        logger.error(f"HTTP error while fetching user projects: {e}")
        return jsonify({"error": f"Crucible error ({status or 502})"}), 502
    except requests.RequestException as e:
        logger.error(f"Upstream request failed while fetching user projects: {e}")
        return jsonify({"error": "Crucible upstream request failed"}), 502

    project_ids = sorted(x["project_id"] for x in projects)

    session["user"] = {
        "email": user_info.get("email", ""),
        "login_reference": user_ref,
        "username": user_info.get("username", ""),
        "user_name": user_name,
        "orcid": user_unique_id,
        "projects": project_ids,
        "selected_project": project_ids[0] if project_ids else "",
    }

    return jsonify(session["user"])


@shared_bp.route("/api/user/logout", methods=["POST"])
def logout():
    session.pop("user", None)
    session.pop("giwaxs", None)
    session.pop("rga", None)
    return jsonify({"ok": True})


@shared_bp.route("/api/user", methods=["GET"])
def get_user():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401
    return jsonify(user)


@shared_bp.route("/api/user/project", methods=["POST"])
def set_project():
    data = request.get_json() or {}
    project = str(data.get("project") or "")
    if "user" in session:
        if project and "projects" in session["user"] and project not in session["user"]["projects"]:
            return jsonify({"error": "Not a member of project"}), 403
        session["user"]["selected_project"] = project
        session.modified = True
        return jsonify({"ok": True, "user": session["user"]})
    return jsonify({"ok": True})
