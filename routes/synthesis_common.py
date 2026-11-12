"""Helpers shared by the synthesis upload and fabrication traveler blueprints.

Their frontend (ported from manual-synthesis-ui) reads errors as {"detail": ...}, so these
blueprints keep that shape instead of this app's usual {"error": ...}.
"""
from flask import jsonify, request, session
from pydantic import ValidationError

from crucible import Sample
from crucible.config import get_graph_explorer_url
from crucible.utils import get_tz_isoformat
from routes.shared import cruc_client


class ApiError(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def register_error_handlers(bp):
    @bp.errorhandler(ApiError)
    def _api_error(error):
        return jsonify({"detail": error.detail}), error.status

    @bp.errorhandler(ValidationError)
    def _validation_error(error):
        return jsonify({"detail": error.errors(include_url=False, include_context=False)}), 422


def parse_body(model):
    return model.model_validate(request.get_json(silent=True) or {})


def current_user(project=None):
    """The logged-in user; identity always comes from the session, never the request body.

    With a project, also checks that it is one of the user's projects.
    """
    user = session.get("user")
    if not user:
        raise ApiError(401, "Not logged in")
    if project is not None and project not in (user.get("projects") or []):
        raise ApiError(403, f"'{project}' is not one of your projects")
    return user


def explorer_url(project, unique_id):
    return f"{get_graph_explorer_url().rstrip('/')}/{project}/samples/{unique_id}"


def add_sample(orcid, project, sample_name, description, sample_type=None):
    timestamp = get_tz_isoformat()
    new_sample = cruc_client.samples.create(Sample(
        sample_name=sample_name, sample_type=sample_type, description=description,
        timestamp=timestamp, owner=orcid, project_id=project,
    ))
    return {
        "sample_name": sample_name,
        "description": description,
        "project": project,
        "unique_id": new_sample["unique_id"],
        "timestamp": timestamp,
    }
