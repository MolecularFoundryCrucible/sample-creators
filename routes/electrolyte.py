import math
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, render_template, request, session

from crucible import Dataset, Sample
from config import PRINT_CONFIG
from routes.shared import cruc_client


electrolyte_bp = Blueprint("electrolyte", __name__)
LA_TZ = ZoneInfo("America/Los_Angeles")


@electrolyte_bp.route("/")
def page():
    return render_template("electrolyte.html", print_config=PRINT_CONFIG)


def _existing_samples(name, project):
    return cruc_client.samples.list(
        sample_name=name,
        project_id=project,
        limit=10,
    )


def _sample_summaries(samples):
    return [
        {
            "unique_id": item["unique_id"],
            "sample_name": item.get("sample_name", ""),
            "sample_type": item.get("sample_type", ""),
        }
        for item in samples
    ]


@electrolyte_bp.route("/api/check-name", methods=["POST"])
def check_name():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401
    if not user.get("selected_project"):
        return jsonify({"error": "No selected project"}), 400

    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Electrolyte name is required"}), 400

    try:
        samples = _existing_samples(name, user["selected_project"])
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({
        "exists": bool(samples),
        "sample_name": name,
        "existing_samples": _sample_summaries(samples),
    })


@electrolyte_bp.route("/api/existing-preparation", methods=["POST"])
def existing_preparation():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401
    if not user.get("selected_project"):
        return jsonify({"error": "No selected project"}), 400

    data = request.get_json(silent=True) or {}
    sample_id = str(data.get("sample_id") or "").strip()
    name = str(data.get("name") or "").strip()
    if not sample_id or not name:
        return jsonify({"error": "Sample ID and electrolyte name are required"}), 400

    try:
        matching_samples = _existing_samples(name, user["selected_project"])
        sample = next(
            (item for item in matching_samples if item.get("unique_id") == sample_id),
            None,
        )
        if sample is None:
            return jsonify({"error": "Sample not found in the selected project"}), 404

        preparations = cruc_client.datasets.list(
            sample_mfid=sample_id,
            measurement="electrolyte preparation",
            project_id=user["selected_project"],
            limit=10,
        )
        if not preparations:
            return jsonify({
                "found": False,
                "sample_id": sample_id,
                "sample_name": sample.get("sample_name", name),
            })

        preparation = cruc_client.datasets.get(
            preparations[0]["unique_id"],
            include_metadata=True,
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    metadata = preparation.get("scientific_metadata") or {}
    preparation_date = str(
        metadata.get("preparation_date") or preparation.get("timestamp") or ""
    )[:10]
    ingredients = metadata.get("ingredients") or []
    if not isinstance(ingredients, list):
        ingredients = []

    return jsonify({
        "found": True,
        "sample_id": sample_id,
        "sample_name": sample.get("sample_name", name),
        "dataset_id": preparation.get("unique_id", ""),
        "dataset_name": preparation.get("dataset_name", ""),
        "preparation_date": preparation_date,
        "concentration": metadata.get("electrolyte_concentration", ""),
        "ph": metadata.get("electrolyte_pH", ""),
        "ingredients": ingredients,
    })


@electrolyte_bp.route("/api/create", methods=["POST"])
def create_electrolyte():
    user = session.get("user")
    if not user:
        return jsonify({"error": "Not logged in"}), 401
    if not user.get("selected_project"):
        return jsonify({"error": "No selected project"}), 400

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid request"}), 400

    name = str(data.get("name") or "").strip()
    preparation_date = str(data.get("preparation_date") or "").strip()
    concentration = str(data.get("concentration") or "").strip()
    raw_ingredients = data.get("ingredients") or []

    if not name:
        return jsonify({"error": "Electrolyte name is required"}), 400
    if not concentration:
        return jsonify({"error": "Electrolyte concentration is required"}), 400

    try:
        prepared_on = date.fromisoformat(preparation_date)
    except ValueError:
        return jsonify({"error": "A valid preparation date is required"}), 400

    try:
        ph = float(data.get("ph"))
    except (TypeError, ValueError):
        return jsonify({"error": "Electrolyte pH must be a number"}), 400
    if not math.isfinite(ph) or not 0 <= ph <= 14:
        return jsonify({"error": "Electrolyte pH must be between 0 and 14"}), 400

    if not isinstance(raw_ingredients, list):
        return jsonify({"error": "Ingredients must be a list"}), 400

    ingredients = []
    for ingredient in raw_ingredients:
        if not isinstance(ingredient, dict):
            return jsonify({"error": "Each ingredient must include a type and amount"}), 400
        ingredient_type = str(ingredient.get("type") or "").strip()
        amount = str(ingredient.get("amount") or "").strip()
        if not ingredient_type or not amount:
            return jsonify({"error": "Each ingredient must include a type and amount"}), 400
        ingredients.append({"type": ingredient_type, "amount": amount})

    if not ingredients:
        return jsonify({"error": "At least one ingredient is required"}), 400

    timestamp = datetime.combine(prepared_on, time.min, LA_TZ).isoformat()
    preparation_metadata = {
        "preparation_date": preparation_date,
        "ingredients": ingredients,
        "electrolyte_concentration": concentration,
        "electrolyte_pH": ph,
    }

    try:
        existing_samples = _existing_samples(name, user["selected_project"])

        existing_sample_id = str(data.get("existing_sample_id") or "").strip()
        if existing_sample_id:
            sample = next(
                (item for item in existing_samples
                 if item.get("unique_id") == existing_sample_id),
                None,
            )
            if sample is None:
                return jsonify({
                    "error": "The selected sample no longer matches this name and project"
                }), 409
        elif existing_samples and not data.get("allow_duplicate"):
            return jsonify({
                "exists": True,
                "error": f"A sample named {name} already exists in this project.",
                "sample_name": name,
                "existing_samples": _sample_summaries(existing_samples),
            }), 409
        else:
            sample = cruc_client.samples.create(Sample(
                sample_name=name,
                sample_type="electrolyte",
                timestamp=timestamp,
                owner=user["orcid"],
                project_id=user["selected_project"],
            ))

        preparation = cruc_client.datasets.create(
            Dataset(
                dataset_name=f"{name} electrolyte preparation {preparation_date}",
                measurement="electrolyte preparation",
                timestamp=timestamp,
                owner=user["orcid"],
                project_id=user["selected_project"],
            ),
            scientific_metadata=preparation_metadata,
        )
        cruc_client.datasets.add_sample(
            dataset_mfid=preparation["dataset_mfid"],
            sample_mfid=sample["unique_id"],
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({
        "unique_id": sample["unique_id"],
        "sample_name": sample["sample_name"],
        "dataset_id": preparation["dataset_mfid"],
        "dataset_name": preparation["created_record"]["dataset_name"],
        "existing_sample_reused": bool(existing_sample_id),
    }), 201
