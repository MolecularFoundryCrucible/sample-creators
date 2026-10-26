import os
import logging
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

from flask import Blueprint, request, jsonify, session

from config import PRINT_CONFIG
from crucible import CrucibleClient
cruc_client = CrucibleClient(api_url = 'https://crucible.lbl.gov/api/v3',
                             api_key=os.environ.get('CRUCIBLE_API_KEY', ''))


shared_bp = Blueprint("shared", __name__)


def resolve_printer(printer):
    """Turn user input into a validated short printer name.

    Accepts either "b30-113" or the fully qualified "crucible-printer/b30-113".
    crucible-api's print endpoint doesn't validate printer_id against a known-
    printers list, so it is checked against the allowlist in PRINT_CONFIG here
    rather than merely sanitized.

    The error deliberately does not name the valid printers — users are expected to
    know the printer they are standing next to.
    """
    prefix = PRINT_CONFIG["printer_topic_prefix"] + "/"
    name = str(printer or "").strip().lower()
    if name.startswith(prefix):
        name = name[len(prefix):]
    if not name:
        raise ValueError("No printer name given")
    if name not in PRINT_CONFIG["printers"]:
        raise ValueError(f"'{name}' is not a known printer")
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


def list_printers():
    """Printers crucible-api has ever seen a status heartbeat from, with live online state.

    Discovery only: a printer that's never been powered on won't appear, and this list is
    never checked against PRINT_CONFIG's allowlist (or used to enforce one) -- it's purely
    informational, for the print page's dropdown.

    Not yet wrapped by nano-crucible (only client.print.barcode() exists there), so this
    calls the client's own internal request method directly, same as every resource module
    in nano-crucible itself does.
    """
    return cruc_client._request("get", "/print/printers").get("printers", [])


def get_next_serial_sample(sample_prefix, sample_type, project):
    project_samples = cruc_client.samples.list(
        project_id=project, sample_type=sample_type, limit=int(1e8)
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
    samples = cruc_client.samples.list(project_id=project, limit=int(1e8))
    return jsonify(sorted({s["sample_type"] for s in samples if s.get("sample_type")}))


@shared_bp.route("/api/user/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    user_ref = str(data.get("user_ref") or data.get("email") or "").strip()
    if not user_ref:
        return jsonify({"error": "Email or username required"}), 400

    try:
        user_info = cruc_client.users.get(user_ref)
    except Exception as e:
        logger.error(f"Error occurred while fetching user info: {e}")
        return jsonify({"error": "User not found"}), 404

    user_unique_id = user_info.get("unique_id") or user_info.get("orcid")
    user_name = format_user(user_info, user_unique_id or user_ref)

    projects = cruc_client.projects.list(orcid=user_unique_id, limit=int(1e5))
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
    data = request.get_json()
    project = data.get("project", "")
    if "user" in session:
        session["user"]["selected_project"] = project
        session.modified = True
    return jsonify({"ok": True})
