"""Browser-direct file uploads to Crucible datasets (signed multipart).

The browser hashes the file and PUTs its parts straight to object storage; these routes only
make the API calls that need our API key: start the session, sign parts, report status,
complete, abort, and request ingestion. File bytes never pass through this app, so Cloud
Run's request size limit doesn't apply. Contract: crucible-api docs/multipart_upload_api.md.
"""

import re
import time
import unicodedata
from threading import Lock

import requests
from flask import Blueprint, jsonify, request, session

from crucible.utils.identifiers import is_mfid
from routes import crucible_api
from routes.shared import cruc_client

uploads_bp = Blueprint("uploads", __name__)

MAX_PARTS_PER_SIGN_REQUEST = 64
MAX_PART_NUMBER = 10_000
MAX_UPLOAD_SIZE = 500 * 1024 ** 3
RETRYABLE_STATUSES = {429, 502, 503, 504}
UPLOAD_STATES = {"uploading", "completed", "aborted"}
INGESTION_CLASS_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

# Which dataset projects a user may upload into, checked once per dataset and cached briefly.
_ACCESS_TTL_S = 3600
_access_cache = {}
_access_lock = Lock()


class UploadError(Exception):
    def __init__(self, status, message, code=None, retryable=False, retry_after=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after


@uploads_bp.errorhandler(UploadError)
def _upload_error(error):
    body = {"error": error.message, "retryable": error.retryable}
    if error.code:
        body["code"] = error.code
    if error.retry_after is not None:
        body["retry_after"] = error.retry_after
    return jsonify(body), error.status


@uploads_bp.after_request
def _no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


def _api_error(error):
    """Turn an HTTP error from crucible-api into an UploadError the browser can act on."""
    response = getattr(error, "response", None)
    if response is None:
        return UploadError(502, "Crucible could not be reached. Try again.", retryable=True)
    status = response.status_code
    detail = None
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        pass
    code = detail.get("code") if isinstance(detail, dict) else None
    message = (detail.get("message") if isinstance(detail, dict) else detail) or f"Crucible returned {status}."
    retry_after = response.headers.get("Retry-After")
    retry_after = int(retry_after) if retry_after and retry_after.isdigit() else None
    retryable = status in RETRYABLE_STATUSES
    # Our own clients' errors stay 4xx; anything upstream-broken is reported as a bad gateway.
    return UploadError(status if status < 500 else 502, str(message), code=code,
                       retryable=retryable, retry_after=retry_after)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except requests.HTTPError as error:
        raise _api_error(error) from error
    except (requests.ConnectionError, requests.Timeout) as error:
        raise UploadError(502, "Crucible could not be reached. Try again.", retryable=True) from error


def _body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise UploadError(400, "Expected a JSON body.")
    return data


def _require_dataset(dataset_mfid):
    """The logged-in user may upload only into datasets of their own projects."""
    user = session.get("user")
    if not user:
        raise UploadError(401, "Not logged in")
    if not isinstance(dataset_mfid, str) or not is_mfid(dataset_mfid):
        raise UploadError(400, "dataset_mfid must be a 26-character MFID.")

    key = (user.get("orcid"), dataset_mfid)
    now = time.monotonic()
    with _access_lock:
        cached = _access_cache.get(key)
    if cached and now - cached[1] < _ACCESS_TTL_S:
        project_id = cached[0]
    else:
        dataset = _call(cruc_client.datasets.get, dataset_mfid)
        project_id = dataset.get("project_id")
        with _access_lock:
            _access_cache[key] = (project_id, now)
    if project_id not in (user.get("projects") or []):
        raise UploadError(403, "This dataset isn't in one of your projects.")


def _require_upload_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise UploadError(400, "Invalid upload_id.")
    return value


def validate_filename(filename):
    """The API's relative-path rule for stored file names."""
    if not isinstance(filename, str) or not filename:
        return "Enter a file name."
    if "\\" in filename:
        return "File names must not contain backslashes."
    if any(unicodedata.category(ch) == "Cc" for ch in filename):
        return "File names must not contain control characters."
    if filename.startswith("/"):
        return "File names must be relative paths."
    segments = filename.split("/")
    if any(not s for s in segments):
        return "File names must not contain empty path segments."
    if any(s in (".", "..") for s in segments):
        return "File names must not contain dot path segments."
    return None


def _state(value):
    return value if value in UPLOAD_STATES else "failed"


@uploads_bp.route("/initiate", methods=["POST"])
def initiate():
    data = _body()
    _require_dataset(data.get("dataset_mfid"))
    filename = data.get("filename")
    problem = validate_filename(filename)
    if problem:
        raise UploadError(400, problem)
    size = data.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_UPLOAD_SIZE:
        raise UploadError(400, "size must be a positive number of bytes, at most 500 GiB.")
    key = data.get("idempotency_key")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9-]{8,64}", key):
        raise UploadError(400, "Invalid idempotency_key.")

    try:
        status = _call(crucible_api.multipart_initiate, data["dataset_mfid"], filename, size, key)
    except UploadError as error:
        if error.code == "filename_exists":
            error.message = f"A file named {filename} already exists in this dataset."
        raise
    if _state(status.get("state")) == "completed" and status.get("existing_file"):
        return jsonify({"state": "completed", "file": status["existing_file"]})
    if not status.get("upload_id"):
        raise UploadError(502, "Crucible did not return an upload id.")
    return jsonify({
        "state": _state(status.get("state")),
        "upload_id": status["upload_id"],
        "part_size": status.get("part_size"),
    })


@uploads_bp.route("/sign", methods=["POST"])
def sign():
    data = _body()
    _require_dataset(data.get("dataset_mfid"))
    upload_id = _require_upload_id(data.get("upload_id"))
    parts = data.get("parts")
    if not isinstance(parts, list) or not 1 <= len(parts) <= MAX_PARTS_PER_SIGN_REQUEST:
        raise UploadError(400, f"Send 1 to {MAX_PARTS_PER_SIGN_REQUEST} parts per request.")
    clean = []
    for part in parts:
        number = part.get("part_number") if isinstance(part, dict) else None
        crc32c = part.get("crc32c") if isinstance(part, dict) else None
        if not isinstance(number, int) or isinstance(number, bool) or not 1 <= number <= MAX_PART_NUMBER:
            raise UploadError(400, "Invalid part_number.")
        if not isinstance(crc32c, str) or not re.fullmatch(r"[A-Za-z0-9+/]{6}==", crc32c):
            raise UploadError(400, "Invalid crc32c.")
        clean.append({"part_number": number, "crc32c": crc32c})

    signed = _call(crucible_api.multipart_sign_parts, data["dataset_mfid"], upload_id, clean)
    out = []
    for part in signed.get("parts") or []:
        url = part.get("url") or ""
        if not url.startswith("https://"):
            raise UploadError(502, "Crucible returned an unusable upload URL.")
        # Browsers refuse to let scripts set these; they derive them from the URL and body.
        headers = {k: v for k, v in (part.get("headers") or {}).items() if k.lower() not in ("content-length", "host")}
        out.append({"part_number": part.get("part_number"), "url": url, "headers": headers})
    return jsonify({"parts": out})


@uploads_bp.route("/status", methods=["GET"])
def status():
    dataset_mfid = request.args.get("dataset_mfid")
    _require_dataset(dataset_mfid)
    upload_id = _require_upload_id(request.args.get("upload_id"))
    acknowledged = set()
    marker = 0
    for _ in range(MAX_PART_NUMBER // crucible_api.STATUS_PAGE_LIMIT + 1):
        page = _call(crucible_api.multipart_status_page, dataset_mfid, upload_id, marker)
        parts = page.get("parts") or []
        acknowledged.update(p["part_number"] for p in parts if isinstance(p.get("part_number"), int))
        nxt = page.get("next_part_number_marker")
        if nxt and nxt > marker and parts:
            marker = nxt
            continue
        return jsonify({
            "state": _state(page.get("state")),
            "acknowledged_part_numbers": sorted(acknowledged),
            "part_size": page.get("part_size"),
            "failure_code": page.get("failure_code"),
            "file": page.get("existing_file"),
        })
    raise UploadError(502, "The upload status listed more parts than allowed.")


@uploads_bp.route("/complete", methods=["POST"])
def complete():
    data = _body()
    _require_dataset(data.get("dataset_mfid"))
    upload_id = _require_upload_id(data.get("upload_id"))
    sha256 = data.get("sha256_hash")
    crc32c = data.get("crc32c")
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise UploadError(400, "sha256_hash must be 64 lowercase hex characters.")
    if not isinstance(crc32c, str) or not re.fullmatch(r"[A-Za-z0-9+/]{6}==", crc32c):
        raise UploadError(400, "Invalid crc32c.")
    return jsonify(_call(crucible_api.multipart_complete, data["dataset_mfid"], upload_id, sha256, crc32c))


@uploads_bp.route("/abort", methods=["POST"])
def abort():
    data = _body()
    _require_dataset(data.get("dataset_mfid"))
    upload_id = _require_upload_id(data.get("upload_id"))
    _call(crucible_api.multipart_abort, data["dataset_mfid"], upload_id)
    return jsonify({"ok": True})


@uploads_bp.route("/ingest", methods=["POST"])
def ingest():
    data = _body()
    _require_dataset(data.get("dataset_mfid"))
    file_mfid = data.get("file_mfid")
    if not isinstance(file_mfid, str) or not is_mfid(file_mfid):
        raise UploadError(400, "file_mfid must be a 26-character MFID.")
    ingestion_class = data.get("ingestion_class") or None
    if ingestion_class is not None and not (isinstance(ingestion_class, str) and INGESTION_CLASS_RE.fullmatch(ingestion_class)):
        raise UploadError(400, "Invalid ingestion_class.")
    requested = data.get("requested", True) is not False
    return jsonify(_call(crucible_api.request_ingestion, file_mfid, requested, ingestion_class))
