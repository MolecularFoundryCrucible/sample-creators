"""SpinBot Photobox Carrier Uploader tool plugin.

Creates or looks up thin-film carriers (CAR), links Tray 1 & Tray 2 grids,
uploads carrier photos, and triggers carrier_segmentation post-processing.
"""
from __future__ import annotations

import logging
from pathlib import Path
from flask import Blueprint, jsonify, render_template, request, session

from crucible import Sample
from crucible.utils import get_tz_isoformat
from crucible.utils.identifiers import is_mfid
from routes.multi_uploader_common import (
    CrossProjectError,
    create_or_update_dataset,
    hub_dataset_url,
    next_carrier_name,
    register_logbook_routes,
    require_user_and_project,
    resolve_children_sorted,
    verify_sample_in_project,
)
from routes.shared import cruc_client, publish_barcode

logger = logging.getLogger(__name__)

spinbot_photobox_bp = Blueprint("spinbot_photobox", __name__)

NAME = "spinbot_photobox"
KEY = "spinbot_photobox"
DIVISION = "b67"
ORDER = 270
BLUEPRINT = spinbot_photobox_bp
URL_PREFIX = "/spinbot-photobox"
ENDPOINT = "spinbot_photobox.page"
NAV_LABEL = "SpinBot Photobox"
CARD_TITLE = "SpinBot Photobox Carrier Uploader"
CARD_DESCRIPTION = "Create or look up thin-film carriers (CAR), link Tray 1 & Tray 2 grids, upload carrier photos, and trigger carrier segmentation."
INSTRUMENT_ID = "spinbot-photobox"
INSTRUMENT_MFID = "0t4ptyzswnyps0006tqctfjbpr"
INGESTOR = ""
UI_MODE = "carrier_photo"
POST_PROCESSING = ["carrier_segmentation"]


@spinbot_photobox_bp.route("/")
def page():
    return render_template("spinbot_photobox.html")


@spinbot_photobox_bp.route("/api/next-carrier-name", methods=["GET"])
def get_next_carrier_name():
    user, err = require_user_and_project()
    if err:
        return err
    requested_project = (request.args.get("project_id") or "").strip()
    project_id = requested_project or user["selected_project"]
    user_projects = user.get("projects") or []
    if project_id not in user_projects and project_id != user.get("selected_project"):
        return jsonify({"error": "Project access denied"}), 403

    try:
        name = next_carrier_name(project_id)
        return jsonify({"sample_name": name})
    except Exception as e:
        logger.error(f"Failed to generate next carrier name: {e}")
        return jsonify({"error": str(e)}), 500


@spinbot_photobox_bp.route("/api/lookup-carrier", methods=["POST"])
def lookup_carrier():
    user, err = require_user_and_project()
    if err:
        return err

    project_id = user["selected_project"]
    data = request.get_json(silent=True) or {}
    sample_unique_id = (data.get("sample_unique_id") or "").strip()
    sample_name = (data.get("sample_name") or "").strip()

    if sample_unique_id:
        try:
            sample = verify_sample_in_project(sample_unique_id, project_id)
            return jsonify({
                "unique_id": sample["unique_id"],
                "sample_name": sample.get("sample_name", ""),
            })
        except CrossProjectError as e:
            return jsonify({"error": str(e)}), 403
        except LookupError as e:
            return jsonify({"error": f"Carrier not found: {e}"}), 404
        except Exception as e:
            return jsonify({"error": f"Carrier not found: {e}"}), 404

    if sample_name:
        try:
            samples = cruc_client.samples.list(
                project_id=project_id,
                sample_type="thin film carrier",
                sample_name=sample_name,
                limit=10,
            )
            if not samples:
                # Fallback to search
                try:
                    samples = cruc_client.samples.search(sample_name, project_id=project_id, limit=10)
                    samples = [s for s in samples if s.get("sample_name") == sample_name]
                except Exception:
                    pass

            if len(samples) > 1:
                return jsonify({"error": f"Multiple carriers match name '{sample_name}'"}), 409
            if not samples:
                return jsonify({"error": f"No carrier found with name '{sample_name}'"}), 404

            match = samples[0]
            return jsonify({
                "unique_id": match["unique_id"],
                "sample_name": match.get("sample_name", ""),
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return jsonify({"error": "Provide either sample_unique_id or sample_name"}), 400


@spinbot_photobox_bp.route("/api/resolve-children", methods=["POST"])
def resolve_children():
    user, err = require_user_and_project()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    sample_uuid = (data.get("sample_uuid") or "").strip()
    if not sample_uuid:
        return jsonify({"error": "sample_uuid is required"}), 400

    try:
        verify_sample_in_project(sample_uuid, user["selected_project"])
    except CrossProjectError as e:
        return jsonify({"error": str(e)}), 403
    except LookupError as e:
        return jsonify({"error": str(e)}), 404

    try:
        children = resolve_children_sorted(sample_uuid)
        return jsonify({"children": children})
    except Exception as e:
        logger.error(f"Failed to resolve tray children {sample_uuid}: {e}")
        return jsonify({"error": str(e)}), 500


@spinbot_photobox_bp.route("/api/print-carrier", methods=["POST"])
def print_carrier():
    if not session.get("user"):
        return jsonify({"error": "Not authenticated"}), 401
    data = request.get_json(silent=True) or {}
    printer_id = (data.get("printer_id") or "b30-113").strip()
    carrier_uuid = (data.get("carrier_uuid") or "").strip()
    carrier_name = (data.get("carrier_name") or "").strip()

    if not carrier_uuid:
        return jsonify({"error": "carrier_uuid is required"}), 400

    try:
        publish_barcode(printer=printer_id, mfid=carrier_uuid, name=carrier_name)
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"Failed to print carrier barcode: {e}")
        return jsonify({"error": str(e)}), 500


@spinbot_photobox_bp.route("/api/prepare-upload", methods=["POST"])
def prepare_upload():
    user, err = require_user_and_project()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    pending_new_carrier = bool(data.get("pending_new_carrier"))
    carrier_uuid = (data.get("carrier_uuid") or "").strip()
    carrier_name = (data.get("carrier_name") or "").strip()
    tray1_uuid = (data.get("tray1_uuid") or "").strip() or None
    tray2_uuid = (data.get("tray2_uuid") or "").strip() or None
    sample_positions = data.get("sample_positions") or {}
    filename = (data.get("filename") or "carrier_photo.jpg").strip()
    comments = (data.get("comments") or "").strip() or None
    keywords = data.get("keywords") or []

    orcid = user["orcid"]
    project_id = user["selected_project"]

    try:
        if not pending_new_carrier:
            if not carrier_uuid:
                return jsonify({"error": "carrier_uuid is required"}), 400
            verify_sample_in_project(carrier_uuid, project_id)
        if tray1_uuid:
            verify_sample_in_project(tray1_uuid, project_id)
        if tray2_uuid:
            verify_sample_in_project(tray2_uuid, project_id)
    except CrossProjectError as e:
        return jsonify({"error": str(e)}), 403
    except LookupError as e:
        return jsonify({"error": str(e)}), 404

    try:
        if pending_new_carrier:
            if not carrier_name:
                carrier_name = next_carrier_name(project_id)
            carrier_sample = Sample(
                sample_name=carrier_name,
                sample_type="thin film carrier",
                project_id=project_id,
                owner=orcid,
                timestamp=get_tz_isoformat(),
            )
            created = cruc_client.samples.create(carrier_sample)
            carrier_uuid = created["unique_id"]
        elif not carrier_uuid:
            return jsonify({"error": "carrier_uuid is required"}), 400

        # Link carrier to trays
        for t in (tray1_uuid, tray2_uuid):
            if t:
                try:
                    cruc_client.samples.link(carrier_uuid, t)
                except Exception as e:
                    logger.warning(f"Could not link carrier {carrier_uuid} to tray {t}: {e}")

        # Create carrier image dataset
        stem = Path(filename).stem
        dataset_name = f"{stem} Carrier Image"
        sci_meta = {
            "sample_positions": sample_positions,
            "carrier_uuid": carrier_uuid,
        }
        if tray1_uuid:
            sci_meta["tray1_uuid"] = tray1_uuid
        if tray2_uuid:
            sci_meta["tray2_uuid"] = tray2_uuid
        if comments:
            sci_meta["comments"] = comments

        dsid, is_existing = create_or_update_dataset(
            orcid=orcid,
            project_id=project_id,
            prod_instrument_mfid=INSTRUMENT_MFID,
            dataset_name=dataset_name,
            measurement="thin film carrier image",
            data_type=None,
            scientific_metadata=sci_meta,
            keywords=keywords,
        )

        # Link dataset to carrier and trays
        to_link = [carrier_uuid] + [t for t in (tray1_uuid, tray2_uuid) if t]
        for s_mfid in to_link:
            try:
                cruc_client.datasets.link_sample(dataset_mfid=dsid, sample_mfid=s_mfid)
            except Exception as e:
                logger.warning(f"Could not link sample {s_mfid} to dataset {dsid}: {e}")

        return jsonify({
            "dataset_mfid": dsid,
            "carrier_uuid": carrier_uuid,
            "carrier_name": carrier_name,
            "hub_url": hub_dataset_url(dsid),
        })

    except CrossProjectError as e:
        return jsonify({"error": str(e)}), 403
    except Exception as e:
        logger.error(f"Failed to prepare photobox upload: {e}")
        return jsonify({"error": str(e)}), 500


@spinbot_photobox_bp.route("/api/postprocess", methods=["POST"])
def postprocess():
    user, err = require_user_and_project()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    dataset_id = (data.get("dataset_id") or data.get("dataset_mfid") or "").strip()
    if not dataset_id:
        return jsonify({"error": "dataset_id is required"}), 400

    try:
        ds = cruc_client.datasets.get(dataset_id)
    except Exception as e:
        return jsonify({"error": f"Dataset not found: {e}"}), 404

    ds_proj = ds.get("project_id")
    user_projects = user.get("projects") or []
    if ds_proj not in user_projects and ds_proj != user.get("selected_project"):
        return jsonify({"error": "Dataset does not belong to user's projects"}), 403

    try:
        res = cruc_client.datasets.postprocess(dataset_id, "carrier_segmentation")
        return jsonify({
            "ok": True,
            "dataset_mfid": dataset_id,
            "pipeline": "carrier_segmentation",
            "result": res,
        })
    except Exception as e:
        logger.error(f"Failed to trigger carrier_segmentation for {dataset_id}: {e}")
        return jsonify({"error": str(e)}), 500


register_logbook_routes(
    spinbot_photobox_bp,
    prod_instrument_mfid=INSTRUMENT_MFID,
    log_prefix="spinbot_photobox",
    csv_filename="spinbot_photobox_recent_datasets.csv",
)
