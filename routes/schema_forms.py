import math
from datetime import date, datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, render_template, request, session

from crucible import Dataset, Sample
from config import PRINT_CONFIG
from routes.shared import cruc_client


schema_forms_bp = Blueprint("schema_forms", __name__)
LA_TZ = ZoneInfo("America/Los_Angeles")

# Schemas are stored as Crucible datasets with this measurement: the schema name is the
# dataset_name and the field list is the scientific_metadata. Only _load_schemas and
# _save_schema know this, so moving schemas to cloud-storage JSON only touches those two.
SCHEMA_MEASUREMENT = "data type schema"

FIELD_TYPES = ("text", "number", "integer", "boolean", "date", "group", "list")
NESTED_TYPES = ("group", "list")


@schema_forms_bp.route("/")
def page():
    return render_template("schema_forms.html", print_config=PRINT_CONFIG)


def _require_user():
    """Return (user, error_response). Exactly one is None."""
    user = session.get("user")
    if not user:
        return None, (jsonify({"error": "Not logged in"}), 401)
    if not user.get("selected_project"):
        return None, (jsonify({"error": "No selected project"}), 400)
    return user, None


def _load_schemas(project):
    """Names and IDs of the schemas created in this project, sorted by name."""
    records = cruc_client.datasets.list(
        project_id=project,
        data_type=SCHEMA_MEASUREMENT,
        limit=None,
    )
    schemas = [
        {"id": record["unique_id"], "name": record.get("dataset_name", "")}
        for record in records
    ]
    return sorted(schemas, key=lambda s: s["name"].lower())


def _get_schema(project, schema_id):
    """One schema with its fields, or None if it isn't a schema in this project."""
    summary = next((s for s in _load_schemas(project) if s["id"] == schema_id), None)
    if summary is None:
        return None
    record = cruc_client.datasets.get(schema_id, include_metadata=True)
    fields = (record.get("scientific_metadata") or {}).get("fields") or []
    return {**summary, "fields": fields}


def _save_schema(user, name, fields):
    created = cruc_client.datasets.create(
        Dataset(
            dataset_name=name,
            measurement=SCHEMA_MEASUREMENT,
            data_type=SCHEMA_MEASUREMENT,
            timestamp=datetime.now(LA_TZ).isoformat(),
            owner=user["orcid"],
            project_id=user["selected_project"],
        ),
        scientific_metadata={"fields": fields},
    )
    return {"id": created["dataset_mfid"], "name": name, "fields": fields}


def _clean_fields(fields, where="the schema"):
    """Validate a builder field list (recursively) and strip it to name/type/required/fields."""
    if not isinstance(fields, list) or not fields:
        raise ValueError(f"Add at least one field to {where}")

    cleaned = []
    seen = set()
    for field in fields:
        if not isinstance(field, dict):
            raise ValueError(f"Invalid field in {where}")
        name = str(field.get("name") or "").strip()
        field_type = field.get("type")
        if not name:
            raise ValueError(f"Every field in {where} needs a name")
        if name in seen:
            raise ValueError(f"Field '{name}' appears twice in {where}")
        if field_type not in FIELD_TYPES:
            raise ValueError(f"Field '{name}' has an unknown type")
        seen.add(name)

        item = {"name": name, "type": field_type, "required": bool(field.get("required"))}
        if field_type in NESTED_TYPES:
            item["fields"] = _clean_fields(field.get("fields"), f"'{name}'")
        cleaned.append(item)
    return cleaned


def _is_blank(value):
    if isinstance(value, dict):
        return all(_is_blank(v) for v in value.values())
    if isinstance(value, list):
        return all(_is_blank(v) for v in value)
    if isinstance(value, bool):
        return not value
    return value is None or str(value).strip() == ""


def _clean_values(fields, values, path=""):
    """Check submitted form values against a schema's fields and coerce their types.

    Empty optional fields are dropped. An optional group left entirely blank is dropped
    without checking its required children, and blank list entries are ignored.
    """
    if not isinstance(values, dict):
        values = {}

    cleaned = {}
    for field in fields:
        name = field["name"]
        label = f"{path}{name}"
        raw = values.get(name)
        field_type = field["type"]

        if field_type == "group":
            if _is_blank(raw):
                if field["required"]:
                    raise ValueError(f"{label} is required")
                continue
            cleaned[name] = _clean_values(field["fields"], raw, f"{label}.")
            continue

        if field_type == "list":
            items = [item for item in (raw if isinstance(raw, list) else []) if not _is_blank(item)]
            if not items:
                if field["required"]:
                    raise ValueError(f"{label} needs at least one entry")
                continue
            cleaned[name] = [
                _clean_values(field["fields"], item, f"{label}[{i}].")
                for i, item in enumerate(items, start=1)
            ]
            continue

        if field_type == "boolean":
            cleaned[name] = bool(raw)
            continue

        text = "" if raw is None else str(raw).strip()
        if not text:
            if field["required"]:
                raise ValueError(f"{label} is required")
            continue

        if field_type == "number":
            try:
                number = float(text)
            except ValueError:
                raise ValueError(f"{label} must be a number")
            if not math.isfinite(number):
                raise ValueError(f"{label} must be a number")
            cleaned[name] = number
        elif field_type == "integer":
            try:
                cleaned[name] = int(text)
            except ValueError:
                raise ValueError(f"{label} must be a whole number")
        elif field_type == "date":
            try:
                date.fromisoformat(text)
            except ValueError:
                raise ValueError(f"{label} must be a valid date")
            cleaned[name] = text
        else:
            cleaned[name] = text
    return cleaned


@schema_forms_bp.route("/api/schemas", methods=["GET"])
def list_schemas():
    user, err = _require_user()
    if err:
        return err
    try:
        return jsonify(_load_schemas(user["selected_project"]))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@schema_forms_bp.route("/api/schemas/<schema_id>", methods=["GET"])
def get_schema(schema_id):
    user, err = _require_user()
    if err:
        return err
    try:
        schema = _get_schema(user["selected_project"], schema_id)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    if schema is None:
        return jsonify({"error": "Schema not found in the selected project"}), 404
    return jsonify(schema)


@schema_forms_bp.route("/api/schemas", methods=["POST"])
def create_schema():
    user, err = _require_user()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Schema name is required"}), 400
    try:
        fields = _clean_fields(data.get("fields"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        existing = _load_schemas(user["selected_project"])
        if any(s["name"].lower() == name.lower() for s in existing):
            return jsonify({"error": f"A schema named {name} already exists in this project"}), 409
        schema = _save_schema(user, name, fields)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify(schema), 201


@schema_forms_bp.route("/api/samples", methods=["POST"])
def create_sample():
    user, err = _require_user()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    name = str(data.get("sample_name") or "").strip()
    sample_type = str(data.get("sample_type") or "").strip()
    description = str(data.get("description") or "").strip()
    if not name:
        return jsonify({"error": "Sample name is required"}), 400
    try:
        created_at = datetime.fromisoformat(str(data.get("timestamp") or "").strip())
    except ValueError:
        return jsonify({"error": "A valid sample creation time is required"}), 400
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=LA_TZ)

    try:
        sample = cruc_client.samples.create(Sample(
            sample_name=name,
            sample_type=sample_type or None,
            description=description or None,
            timestamp=created_at.isoformat(),
            owner=user["orcid"],
            project_id=user["selected_project"],
        ))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({
        "unique_id": sample["unique_id"],
        "sample_name": sample.get("sample_name", name),
        "sample_type": sample.get("sample_type") or "",
    }), 201


@schema_forms_bp.route("/api/datasets", methods=["POST"])
def create_dataset():
    user, err = _require_user()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    schema_id = str(data.get("schema_id") or "").strip()
    sample_id = str(data.get("sample_id") or "").strip()
    dataset_name = str(data.get("dataset_name") or "").strip()
    if not dataset_name:
        return jsonify({"error": "Dataset name is required"}), 400

    try:
        schema = _get_schema(user["selected_project"], schema_id)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    if schema is None:
        return jsonify({"error": "Schema not found in the selected project"}), 404

    try:
        metadata = _clean_values(schema["fields"], data.get("values"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    now = datetime.now(LA_TZ)
    try:
        created = cruc_client.datasets.create(
            Dataset(
                dataset_name=dataset_name,
                measurement=schema["name"],
                data_type=schema["name"],
                timestamp=now.isoformat(),
                owner=user["orcid"],
                project_id=user["selected_project"],
            ),
            scientific_metadata=metadata,
        )
        if sample_id:
            cruc_client.datasets.add_sample(
                dataset_mfid=created["dataset_mfid"],
                sample_mfid=sample_id,
            )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({
        "dataset_id": created["dataset_mfid"],
        "dataset_name": created["created_record"]["dataset_name"],
        "sample_id": sample_id,
        "metadata": metadata,
    }), 201
