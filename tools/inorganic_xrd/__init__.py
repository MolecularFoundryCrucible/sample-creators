"""Inorganic XRD Uploader tool plugin.

Supports three upload modes:
1. Single Sample: 1+ .txt files, each mapped to a sample.
2. From File: 1 combined .txt file with tab-separated sample names on line 1,
   split into flat multiple datasets.
3. From Parent: 1 combined .txt file linked to parent sample dataset and
   per-child sample child datasets.
"""
from __future__ import annotations

import logging
from pathlib import Path
from flask import Blueprint, jsonify, render_template, request

from routes.multi_uploader_common import (
    CrossProjectError,
    create_or_update_dataset,
    existing_user_project_dsids,
    hub_dataset_url,
    register_logbook_routes,
    require_user_and_project,
    resolve_children_sorted,
    resolve_dsid_for_sha256,
    verify_sample_in_project,
)
from routes.shared import cruc_client

logger = logging.getLogger(__name__)

inorganic_xrd_bp = Blueprint("inorganic_xrd", __name__)

NAME = "inorganic_xrd"
KEY = "inorganic_xrd"
DIVISION = "b67"
ORDER = 240
BLUEPRINT = inorganic_xrd_bp
URL_PREFIX = "/inorganic-xrd"
ENDPOINT = "inorganic_xrd.page"
NAV_LABEL = "Inorganic - XRD"
CARD_TITLE = "Inorganic - XRD"
CARD_DESCRIPTION = "Upload Inorganic XRD (.txt) datasets in Single Sample, From File (multi-sample), or From Parent sample modes."
INSTRUMENT_ID = "inorganic-xrd"
INSTRUMENT_MFID = "0tmz7j9xmsrvn000tbs1zjwgpr"
INGESTOR = "InorganicXRDIngestor"
UI_MODE = "multi_assignment"
POST_PROCESSING = []


@inorganic_xrd_bp.route("/")
def page():
    return render_template("inorganic_xrd.html")


@inorganic_xrd_bp.route("/api/resolve-children", methods=["POST"])
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
        logger.error(f"Failed to resolve child samples for {sample_uuid}: {e}")
        return jsonify({"error": str(e)}), 500


@inorganic_xrd_bp.route("/api/create-uploads", methods=["POST"])
def create_uploads():
    user, err = require_user_and_project()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    mode = data.get("mode") or "single"
    comments = data.get("comments") or None
    keywords = data.get("keywords") or []

    orcid = user["orcid"]
    project_id = user["selected_project"]
    valid_dsids = existing_user_project_dsids(orcid, project_id)

    try:
        if mode == "single":
            files = data.get("files") or []
            if not files:
                return jsonify({"error": "No files provided"}), 400

            for item in files:
                s_uid = (item.get("sample_uuid") or "").strip()
                if s_uid:
                    verify_sample_in_project(s_uid, project_id)

            results = []
            for item in files:
                filename = item.get("filename") or "xrd_data.txt"
                sha256 = item.get("sha256") or ""
                sample_uuid = (item.get("sample_uuid") or "").strip()

                reused_dsid, _ = resolve_dsid_for_sha256(sha256, valid_dsids)
                stem = Path(filename).stem
                dataset_name = f"{stem} XRD"
                sci_meta = {"filename": filename}
                if comments:
                    sci_meta["comments"] = comments

                dsid, is_existing = create_or_update_dataset(
                    orcid=orcid,
                    project_id=project_id,
                    prod_instrument_mfid=INSTRUMENT_MFID,
                    dsid=reused_dsid,
                    dataset_name=dataset_name,
                    measurement=None,
                    data_type=None,
                    scientific_metadata=sci_meta,
                    keywords=keywords,
                )

                if sample_uuid:
                    try:
                        cruc_client.datasets.link_sample(dataset_mfid=dsid, sample_mfid=sample_uuid)
                    except Exception as e:
                        logger.warning(f"Could not link sample {sample_uuid} to {dsid}: {e}")

                results.append({
                    "filename": filename,
                    "dataset_mfid": dsid,
                    "is_existing": is_existing,
                    "hub_url": hub_dataset_url(dsid),
                })

            return jsonify({"mode": "single", "uploads": results})

        elif mode == "flat_multi":
            filename = data.get("filename") or "combined_xrd.txt"
            samples = data.get("samples") or []
            if not samples:
                return jsonify({"error": "No samples assigned"}), 400

            for s in samples:
                s_uid = (s.get("sample_uuid") or s.get("uuid") or "").strip()
                if s_uid:
                    verify_sample_in_project(s_uid, project_id)

            stem = Path(filename).stem
            results = []
            for s in samples:
                sample_uuid = (s.get("sample_uuid") or s.get("uuid") or "").strip()
                if not sample_uuid:
                    continue
                sample_name = s.get("sample_name") or s.get("name") or sample_uuid
                position = s.get("position") or ""

                dataset_name = f"{stem}_{sample_name} XRD"
                sci_meta = {
                    "filename": filename,
                    "sample_uuid": sample_uuid,
                }
                if position:
                    sci_meta["position"] = position
                if comments:
                    sci_meta["comments"] = comments

                dsid, is_existing = create_or_update_dataset(
                    orcid=orcid,
                    project_id=project_id,
                    prod_instrument_mfid=INSTRUMENT_MFID,
                    dataset_name=dataset_name,
                    measurement=None,
                    data_type=None,
                    scientific_metadata=sci_meta,
                    keywords=keywords,
                )

                try:
                    cruc_client.datasets.link_sample(dataset_mfid=dsid, sample_mfid=sample_uuid)
                except Exception as e:
                    logger.warning(f"Could not link sample {sample_uuid} to {dsid}: {e}")

                results.append({
                    "dataset_mfid": dsid,
                    "sample_uuid": sample_uuid,
                    "sample_name": sample_name,
                    "position": position,
                    "hub_url": hub_dataset_url(dsid),
                })

            return jsonify({"mode": "flat_multi", "uploads": results})

        elif mode == "parent_child":
            filename = data.get("filename") or "combined_xrd.txt"
            parent_uuid = (data.get("parent_uuid") or "").strip()
            raw_children = data.get("children") or data.get("child_uuids") or []
            if not parent_uuid:
                return jsonify({"error": "parent_uuid is required"}), 400

            children_specs = []
            for idx, c in enumerate(raw_children):
                if isinstance(c, dict):
                    uid = (c.get("uuid") or c.get("sample_uuid") or c.get("unique_id") or "").strip()
                    pos = (c.get("position") or "").strip() or f"S{idx + 1:02d}"
                    name = (c.get("name") or c.get("sample_name") or uid).strip()
                else:
                    uid = str(c).strip()
                    pos = f"S{idx + 1:02d}"
                    name = uid
                if uid:
                    children_specs.append({"uuid": uid, "position": pos, "name": name})

            child_uuids = [c["uuid"] for c in children_specs]

            verify_sample_in_project(parent_uuid, project_id)
            for c_uid in child_uuids:
                verify_sample_in_project(c_uid, project_id)

            stem = Path(filename).stem
            parent_name = f"{stem} Parent XRD"
            parent_meta = {
                "upload_mode": "parent",
                "filename": filename,
                "parent_sample_uuid": parent_uuid,
                "child_sample_uuids": child_uuids,
            }
            if comments:
                parent_meta["comments"] = comments

            parent_dsid, _ = create_or_update_dataset(
                orcid=orcid,
                project_id=project_id,
                prod_instrument_mfid=INSTRUMENT_MFID,
                dataset_name=parent_name,
                measurement=None,
                data_type=None,
                scientific_metadata=parent_meta,
                keywords=keywords,
            )

            try:
                cruc_client.datasets.link_sample(dataset_mfid=parent_dsid, sample_mfid=parent_uuid)
            except Exception as e:
                logger.warning(f"Could not link parent sample {parent_uuid} to {parent_dsid}: {e}")

            children_results = []
            for spec in children_specs:
                ch_uuid = spec["uuid"]
                ch_pos = spec["position"]
                ch_name = spec["name"]

                ch_meta = {
                    "filename": filename,
                    "parent_dataset_mfid": parent_dsid,
                    "parent_sample_uuid": parent_uuid,
                    "sample_uuid": ch_uuid,
                    "position": ch_pos,
                }
                if comments:
                    ch_meta["comments"] = comments

                dataset_name = f"{stem}_{ch_name} XRD" if ch_name else f"{stem}_{ch_uuid} XRD"
                ch_dsid, _ = create_or_update_dataset(
                    orcid=orcid,
                    project_id=project_id,
                    prod_instrument_mfid=INSTRUMENT_MFID,
                    dataset_name=dataset_name,
                    measurement=None,
                    data_type=None,
                    scientific_metadata=ch_meta,
                    keywords=keywords,
                )

                try:
                    cruc_client.datasets.link(parent_mfid=parent_dsid, child_mfid=ch_dsid)
                except Exception as e:
                    logger.warning(f"Could not link parent ds {parent_dsid} to child ds {ch_dsid}: {e}")

                try:
                    cruc_client.datasets.link_sample(dataset_mfid=ch_dsid, sample_mfid=ch_uuid)
                except Exception as e:
                    logger.warning(f"Could not link child sample {ch_uuid} to {ch_dsid}: {e}")

                children_results.append({
                    "child_dataset_mfid": ch_dsid,
                    "sample_uuid": ch_uuid,
                    "position": ch_pos,
                    "hub_url": hub_dataset_url(ch_dsid),
                })

            all_upload_targets = [parent_dsid] + [c["child_dataset_mfid"] for c in children_results]
            return jsonify({
                "mode": "parent_child",
                "parent_dataset_mfid": parent_dsid,
                "parent_hub_url": hub_dataset_url(parent_dsid),
                "children": children_results,
                "upload_targets": all_upload_targets,
            })

        else:
            return jsonify({"error": f"Invalid mode '{mode}'"}), 400

    except CrossProjectError as e:
        return jsonify({"error": str(e)}), 403
    except LookupError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(f"Failed to create uploads: {e}")
        return jsonify({"error": str(e)}), 500


register_logbook_routes(
    inorganic_xrd_bp,
    prod_instrument_mfid=INSTRUMENT_MFID,
    log_prefix="inorganic_xrd",
    csv_filename="inorganic_xrd_recent_datasets.csv",
)
