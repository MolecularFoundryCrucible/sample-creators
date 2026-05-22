import os
import logging
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

from flask import Blueprint, request, jsonify, session

from crucible import CrucibleClient
cruc_client = CrucibleClient()

shared_bp = Blueprint("shared", __name__)


def get_next_serial_sample(sample_prefix, sample_type, project):
    project_samples = cruc_client.samples.list(
        project_id=project, sample_type=sample_type, limit=5000
    )
    filtered = [x["sample_name"] for x in project_samples if x["sample_name"].startswith(sample_prefix)]
    nums = sorted(int(x.replace(sample_prefix, "")) for x in filtered)
    if not nums:
        return 1
    return nums[-1] + 1


@shared_bp.route("/api/user/login", methods=["POST"])
def login():
    data = request.get_json()
    email = data.get("email", "").strip()
    if not email:
        return jsonify({"error": "Email required"}), 400

    user_info = cruc_client.users.get(email=email)
    if user_info is None:
        return jsonify({"error": "User not found"}), 404

    user_name = f"{user_info['first_name']}_{user_info['last_name']}"
    orcid = user_info["orcid"]

    projects = cruc_client.projects.list(orcid=orcid)
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
