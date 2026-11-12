"""Routes shared by single-sample instrument pages (B30 SEM, B30 Raman).

The page picks or creates one sample by barcode, the user fills in acquisition parameters,
the dataset is created here from those form fields, and the browser then uploads the files
straight to storage (/api/uploads) and requests ingestion. A logbook lists the instrument's
datasets in the selected project.
"""
from datetime import datetime

from flask import current_app, jsonify, request, session

from crucible import Dataset, Sample
from crucible.utils import get_tz_isoformat
from routes.deposition_common import LA_TZ, csv_response, incremental_refresh_rows
from routes.shared import cruc_client, instrument_mfid, publish_barcode

SAMPLE_STATE_KEYS = ("sample_unique_id", "sample_name", "sample_type", "sample_description")


def form_metadata(dataset_fields, data):
    """Scientific metadata from the submitted form, following each field's config.

    Values are stored as submitted (trimmed strings), except fields with "as_number" (stored
    as numbers) and "range" fields ([start, end] numbers). Empty values are left out.
    """
    out = {}
    for field in dataset_fields:
        key = field["key"]
        value = data.get(key)
        if field.get("type") == "range":
            if isinstance(value, (list, tuple)) and len(value) == 2:
                try:
                    out[key] = [float(value[0]), float(value[1])]
                except (TypeError, ValueError):
                    pass
            continue
        if isinstance(value, str):
            value = value.strip()
        if value is None or value == "":
            continue
        if field.get("as_number"):
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
        out[key] = value
    return out


def register_instrument_routes(bp, *, config, session_key, dataset_to_row, logbook_cols,
                               csv_filename, log_prefix):
    """Register state, sample, print, dataset and logbook routes on an instrument blueprint.

    config needs: dataset_fields, dataset_type, measurement, instrument_mfid, printer_name,
    dataset_label (used in dataset names, e.g. "SEM").
    """
    instrument = instrument_mfid(config["instrument_mfid"])

    def get_state():
        if session_key not in session:
            session[session_key] = {k: "" for k in SAMPLE_STATE_KEYS}
        return session[session_key]

    def remember_sample(sample_id, name, sample_type, description):
        state = get_state()
        state.update(sample_unique_id=sample_id, sample_name=name, sample_type=sample_type,
                     sample_description=description)
        session.modified = True

    def logbook_rows(project_id):
        return incremental_refresh_rows(
            cache_key=(log_prefix, project_id, instrument),
            fetch_summaries=lambda: cruc_client.datasets.list(
                project_id=project_id, instrument_mfid=instrument, limit=2000),
            build_row=dataset_to_row,
        )

    def selected_project():
        user = session.get("user")
        if not user:
            return None, (jsonify({"error": "Not logged in"}), 401)
        project_id = user.get("selected_project")
        if not project_id:
            return None, (jsonify({"error": "No selected project"}), 400)
        return project_id, None

    def logbook_limit():
        return max(1, min(int(request.args.get("limit", 100)), 5000))

    @bp.route("/api/state", methods=["GET"])
    def get_state_route():
        return jsonify(get_state())

    @bp.route("/api/lookup-sample", methods=["POST"])
    def lookup_sample():
        unique_id = (request.get_json(silent=True) or {}).get("unique_id", "").strip()
        if not unique_id:
            return jsonify({"error": "No barcode value provided"}), 400
        try:
            sample = cruc_client.samples.get(unique_id)
        except Exception:
            sample = None
        if sample is None:
            return jsonify({"found": False, "unique_id": unique_id})

        remember_sample(sample["unique_id"], sample["sample_name"], sample.get("sample_type", ""),
                        sample.get("description", ""))
        return jsonify({
            "found": True,
            "unique_id": sample["unique_id"],
            "sample_name": sample["sample_name"],
            "sample_type": sample.get("sample_type", ""),
            "description": sample.get("description", ""),
        })

    @bp.route("/api/create-sample", methods=["POST"])
    def create_sample():
        user = session.get("user")
        if not user:
            return jsonify({"error": "Not logged in"}), 401
        data = request.get_json(silent=True) or {}
        sample_name = data.get("sample_name", "").strip()
        sample_type = data.get("sample_type", "").strip()
        description = data.get("description", "").strip()
        if not sample_name or not sample_type:
            return jsonify({"error": "sample_name and sample_type are required"}), 400

        try:
            created = cruc_client.samples.create(Sample(
                sample_name=sample_name,
                timestamp=get_tz_isoformat(),
                owner=user["orcid"],
                project_id=user["selected_project"],
                sample_type=sample_type,
                description=description or None,
            ))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        remember_sample(created["unique_id"], created["sample_name"], sample_type, description)
        return jsonify({
            "unique_id": created["unique_id"],
            "sample_name": created["sample_name"],
            "sample_type": sample_type,
            "description": description,
        })

    @bp.route("/api/print-barcode", methods=["POST"])
    def print_barcode():
        data = request.get_json(silent=True) or {}
        sample_name = data.get("sample_name", "").strip()
        sample_mfid = data.get("sample_id", "").strip()
        if not sample_mfid:
            return jsonify({"error": "sample_id is required"}), 400
        try:
            publish_barcode(config["printer_name"], sample_mfid, sample_name)
        except Exception as e:
            current_app.logger.error(f"[{log_prefix}] Barcode print failed: {e}")
            return jsonify({"error": str(e)}), 500
        return jsonify({"ok": True, "sample_id": sample_mfid, "sample_name": sample_name}), 200

    @bp.route("/api/upload-dataset", methods=["POST"])
    def upload_dataset():
        """Create the dataset from the form fields and link the sample.

        The browser then uploads the files straight to storage and requests ingestion.
        """
        user = session.get("user")
        if not user:
            return jsonify({"error": "Not logged in"}), 401
        state = get_state()
        if not state.get("sample_unique_id"):
            return jsonify({"error": "No sample selected. Scan a barcode first."}), 400

        scientific_metadata = form_metadata(config["dataset_fields"], request.get_json(silent=True) or {})
        sample_name = (state.get("sample_name") or "").strip() or "unknown-sample"
        date_str = datetime.now(LA_TZ).strftime("%Y%m%d_%H%M%S")
        dataset_name = f"{date_str}_{config['dataset_label']}_on_{sample_name}"

        try:
            ds = Dataset(
                dataset_name=dataset_name,
                data_type=config["dataset_type"],
                owner=user["orcid"],
                project_id=user["selected_project"],
                instrument_mfid=instrument,
                measurement=config["measurement"],
                timestamp=get_tz_isoformat(),
            )
            new_dataset = cruc_client.datasets.create(ds, scientific_metadata=scientific_metadata)
            dataset_mfid = new_dataset["dataset_mfid"]
            cruc_client.datasets.add_sample(dataset_mfid=dataset_mfid, sample_mfid=state["sample_unique_id"])
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        return jsonify({"dataset_name": dataset_name, "dataset_id": dataset_mfid, "sample_name": state["sample_name"]})

    @bp.route("/api/recent-datasets", methods=["GET"])
    def recent_datasets():
        project_id, err = selected_project()
        if err:
            return err
        try:
            rows = [{k: v for k, v in row.items() if not k.startswith("_")}
                    for row in logbook_rows(project_id)[:logbook_limit()]]
            return jsonify({"rows": rows, "count": len(rows)}), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route(f"/api/recent-datasets/{csv_filename}", methods=["GET"])
    def export_recent_datasets_csv():
        project_id, err = selected_project()
        if err:
            return err
        try:
            return csv_response(logbook_cols, logbook_rows(project_id)[:logbook_limit()],
                                csv_filename.rsplit(".", 1)[0])
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return get_state
