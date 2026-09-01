import json
import os
import logging
import time
import uuid
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

from flask import Blueprint, request, jsonify, session
import paho.mqtt.publish as publish

from config import PRINT_CONFIG
from crucible import CrucibleClient
cruc_client = CrucibleClient(api_url = 'https://crucible.lbl.gov/api/v3',
                             api_key=os.environ.get('CRUCIBLE_API_KEY', ''))


shared_bp = Blueprint("shared", __name__)


def resolve_printer(printer):
    """Turn user input into a validated short printer name.

    Accepts either "b30-113" or the fully qualified "crucible-printer/b30-113".
    The name ends up in an MQTT topic, so it is checked against the allowlist in
    PRINT_CONFIG rather than merely sanitized.

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


def publish_barcode(printer, mfid, name=""):
    """Send one label job to a Crucible label printer over MQTT."""
    topic = f"{PRINT_CONFIG['printer_topic_prefix']}/{resolve_printer(printer)}/print"
    payload = {
        "job_id": str(uuid.uuid4()),
        "mfid": mfid,
        "name": name,
        "ts": time.time(),
    }

    publish.single(
        topic=topic,
        payload=json.dumps(payload),
        hostname=os.environ.get("MQTT_BROKER", "mqtt.mfdata.org"),
        port=int(os.environ.get("MQTT_PORT", "8883")),
        auth={
            "username": os.environ.get("MQTT_USERNAME", "crucible-printers"),
            "password": os.environ.get("MQTT_PASSWORD"),
        },
        tls={"ca_certs": None},
    )


def get_next_serial_sample(sample_prefix, sample_type, project):
    project_samples = cruc_client.samples.list(
        project_id=project, sample_type=sample_type, limit=int(1e8)
    )
    filtered = [x["sample_name"] for x in project_samples if x["sample_name"].startswith(sample_prefix)]
    nums = sorted(int(x.replace(sample_prefix, "")) for x in filtered)
    if not nums:
        return 1
    return nums[-1] + 1


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
    data = request.get_json()
    email = data.get("email", "").strip()
    logger.info(f'{email=}')
    if not email:
        return jsonify({"error": "Email required"}), 400

    try:
        user_info = cruc_client.users.get(email=email)
    except Exception as e:
        logger.error(f"Error occurred while fetching user info for email {email}: {e}")
        return jsonify({"error": "User not found"}), 404

    user_name = f"{user_info['first_name']}_{user_info['last_name']}"
    orcid = user_info.get('unique_id', None)
    if orcid is None:
        orcid = user_info["orcid"]

    projects = cruc_client.projects.list(orcid=orcid, limit = int(1e5))
    project_ids = sorted(x["project_id"] for x in projects)

    session["user"] = {
        "email": email,
        "user_name": user_name,
        "orcid": orcid,
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
