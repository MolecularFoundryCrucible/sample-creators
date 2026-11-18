"""Reusable backend routes and helpers for migrated uploaders.

Provides dataset creation/updating with SHA-256 deduplication, sample lookup
with HTTP 409 disambiguation, sample creation, barcode printing, postprocessing,
and logbook / CSV export.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

from flask import current_app, jsonify, request, session

from crucible import Dataset, Sample
from crucible.utils import get_tz_isoformat
from crucible.utils.identifiers import is_mfid
from routes.deposition_common import (
    LA_TZ,
    clean,
    csv_response,
    incremental_refresh_rows,
    parse_ts,
    pick,
)
from routes.shared import cruc_client, format_user, instrument_mfid, publish_barcode

logger = logging.getLogger(__name__)

HUB_BASE_URL = os.environ.get("CRUCIBLE_HUB_URL", "https://crucible.lbl.gov/hub").rstrip("/")


class CrossProjectError(PermissionError):
    """Raised when an operation attempts to access or modify a resource in another project."""
    pass


def verify_sample_in_project(sample_id: str, project_id: str) -> dict:
    """Look up sample_id and ensure it belongs to project_id.

    Raises LookupError if sample not found.
    Raises CrossProjectError if sample exists but belongs to another project.
    """
    if not sample_id or not isinstance(sample_id, str):
        raise LookupError("sample_id is required")
    sid = sample_id.strip()
    if not sid:
        raise LookupError("sample_id is required")
    try:
        sample = cruc_client.samples.get(sid)
    except Exception:
        sample = None
    if not sample or not sample.get("unique_id"):
        raise LookupError(f"Sample '{sid}' not found")
    sample_proj = sample.get("project_id") or (sample.get("project") or {}).get("project_id")
    if sample_proj != project_id:
        raise CrossProjectError(f"Sample '{sid}' belongs to project '{sample_proj}', not '{project_id}'")
    return sample


def hub_dataset_url(dsid: str) -> str:
    """Generate canonical Crucible Hub URL for a dataset."""
    return f"{HUB_BASE_URL}/datasets/{dsid}"


def require_logged_in_user():
    """Verify session user and selected project.

    Returns (user_dict, None) or (None, (json_response, status_code)).
    """
    user = session.get("user")
    if not user:
        return None, (jsonify({"error": "Not logged in"}), 401)
    if not user.get("selected_project"):
        return None, (jsonify({"error": "No selected project"}), 400)
    return user, None


def existing_user_project_dsids(orcid: str, project_id: str) -> set[str]:
    """Return set of dataset unique_ids in project_id owned by orcid."""
    try:
        ds_list = cruc_client.datasets.list(project_id=project_id, include_owner=True, limit=None)
    except TypeError:
        ds_list = cruc_client.datasets.list(project_id=project_id, limit=None)

    matched = set()
    for ds in ds_list:
        uid = ds.get("unique_id")
        if not uid:
            continue
        owner = ds.get("owner")
        owner_orcid = ds.get("owner_orcid")
        ds_owner_id = None
        if isinstance(owner, dict):
            ds_owner_id = owner.get("orcid") or owner.get("unique_id")
        elif isinstance(owner, str):
            ds_owner_id = owner
        if not orcid or ds_owner_id == orcid or owner_orcid == orcid:
            matched.add(uid)
    return matched


def resolve_dsid_for_sha256(sha256_hash: str | None, valid_dsids: set[str]) -> tuple[str | None, bool]:
    """Look up existing dataset for a SHA-256 hash among valid project datasets."""
    if not sha256_hash or not isinstance(sha256_hash, str) or len(sha256_hash) != 64:
        return None, False
    try:
        files = cruc_client.files.list(sha256_hash=sha256_hash)
        for f in files:
            ds_mfid = f.get("dataset_mfid")
            if ds_mfid and ds_mfid in valid_dsids:
                return ds_mfid, True
    except Exception as e:
        logger.warning(f"Error checking sha256 {sha256_hash}: {e}")
    return None, False


def dataset_exists(dsid: str | None) -> bool:
    """Check whether a dataset with this MFID exists in Crucible."""
    if not dsid or not isinstance(dsid, str) or not is_mfid(dsid):
        return False
    try:
        cruc_client.datasets.get(dsid)
        return True
    except Exception:
        return False


def create_or_update_dataset(
    *,
    orcid: str,
    project_id: str,
    prod_instrument_mfid: str,
    dsid: str | None = None,
    dataset_name: str | None = None,
    measurement: str | None = None,
    data_type: str | None = None,
    data_format: str | None = None,
    session_name: str | None = None,
    timestamp: str | None = None,
    public: bool = False,
    scientific_metadata: dict | None = None,
    keywords: list[str] | None = None,
) -> tuple[str, bool]:
    """Create or update a Crucible dataset record.

    Returns (dataset_mfid, reused).
    """
    inst_mfid = instrument_mfid(prod_instrument_mfid)
    reused = False
    if dsid and is_mfid(dsid):
        try:
            existing = cruc_client.datasets.get(dsid)
        except Exception:
            existing = None
        if existing and existing.get("unique_id"):
            existing_proj = existing.get("project_id") or (existing.get("project") or {}).get("project_id")
            if existing_proj != project_id:
                raise CrossProjectError(f"Dataset '{dsid}' belongs to project '{existing_proj}', not '{project_id}'")
            reused = True

    if reused:
        updates = {}
        if dataset_name:
            updates["dataset_name"] = dataset_name
        if measurement:
            updates["measurement"] = measurement
        if data_type:
            updates["data_type"] = data_type
        if data_format:
            updates["data_format"] = data_format
        if session_name:
            updates["session_name"] = session_name
        if timestamp:
            updates["timestamp"] = timestamp
        if updates:
            cruc_client.datasets.update(dsid, **updates)
        if scientific_metadata:
            cruc_client.datasets.update_scientific_metadata(dsid, scientific_metadata)
        if keywords:
            for kw in keywords:
                if kw and isinstance(kw, str) and kw.strip():
                    cruc_client.datasets.add_keyword(dsid, kw.strip())
        return dsid, True
    else:
        now_str = datetime.now(LA_TZ).strftime("%Y%m%d_%H%M%S")
        ds_kwargs = {
            "dataset_name": dataset_name or f"{now_str}_upload",
            "owner": orcid,
            "project_id": project_id,
            "instrument_mfid": inst_mfid,
            "measurement": measurement,
            "data_type": data_type,
            "data_format": data_format,
            "session_name": session_name,
            "timestamp": timestamp or get_tz_isoformat(),
        }
        if public:
            ds_kwargs["public"] = True
        if dsid and is_mfid(dsid):
            ds_kwargs["unique_id"] = dsid
        filtered_kwargs = {k: v for k, v in ds_kwargs.items() if v is not None}
        ds = Dataset(**filtered_kwargs)
        clean_keywords = [
            k.strip() for k in (keywords or [])
            if k and isinstance(k, str) and k.strip()
        ]
        resp = cruc_client.datasets.create(
            ds,
            scientific_metadata=scientific_metadata or {},
            keywords=clean_keywords,
        )
        new_dsid = resp.get("dataset_mfid") or (resp.get("created_record") or {}).get("unique_id")
        return new_dsid, False


def lookup_sample_in_project(*, project_id: str, sample_unique_id: str = "", sample_name: str = ""):
    """Look up a sample in project_id by MFID or name.

    Returns (sample_dict, None) on success, or (None, (error_data, status_code)).
    """
    uid = sample_unique_id.strip() if sample_unique_id else ""
    sname = sample_name.strip() if sample_name else ""

    if uid:
        try:
            sample = cruc_client.samples.get(uid)
        except Exception:
            sample = None
        if not sample:
            return None, ({"error": f"Sample not found for MFID '{uid}' in project '{project_id}'"}, 404)
        if sample.get("project_id") and sample.get("project_id") != project_id:
            return None, ({"error": f"Sample '{uid}' does not belong to project '{project_id}'"}, 404)
        return sample, None

    if sname:
        try:
            matches = cruc_client.samples.list(sample_name=sname, project_id=project_id)
        except Exception as e:
            return None, ({"error": f"Failed to list samples: {e}"}, 500)
        if len(matches) == 0:
            return None, ({"error": f"No sample named '{sname}' in project '{project_id}'"}, 404)
        if len(matches) > 1:
            candidates = [
                {"unique_id": m["unique_id"], "sample_name": m.get("sample_name", "")}
                for m in matches
            ]
            return None, ({
                "error": f"Multiple samples named '{sname}' in project '{project_id}' — enter its MFID instead",
                "candidates": candidates,
            }, 409)
        return matches[0], None

    return None, ({"error": "sample_unique_id or sample_name is required"}, 400)


def register_common_uploader_routes(bp, *, tool_config: dict):
    """Register common API endpoints for migrated uploaders on bp."""
    inst_mfid = instrument_mfid(tool_config["instrument_mfid"])
    log_prefix = tool_config.get("key", "uploader")
    logbook_cols = ["Date", "User", "Dataset Name", "Measurement", "Data Type", "Dataset ID", "Comment"]

    def _row_builder(details):
        sci = details.get("scientific_metadata") or {}
        raw_ts = details.get("timestamp")
        date_str = ""
        if raw_ts:
            dt = parse_ts(raw_ts)
            try:
                date_str = dt.astimezone(LA_TZ).strftime("%Y-%m-%d %H:%M")
            except (OverflowError, ValueError):
                date_str = ""
        return {
            "Date": date_str,
            "User": format_user(details.get("owner"), pick(details, "owner_orcid", default="")),
            "Dataset Name": clean(details.get("dataset_name")),
            "Measurement": clean(details.get("measurement")),
            "Data Type": clean(details.get("data_type")),
            "Dataset ID": clean(details.get("unique_id")),
            "Comment": clean(sci.get("comments") or sci.get("comment")),
            "_dataset_id": details.get("unique_id") or "",
            "_timestamp": details.get("timestamp") or "",
        }

    def _get_logbook_rows(project_id):
        return incremental_refresh_rows(
            cache_key=(log_prefix, project_id, inst_mfid),
            fetch_summaries=lambda: cruc_client.datasets.list(
                project_id=project_id, instrument_mfid=inst_mfid, limit=2000
            ),
            build_row=_row_builder,
        )

    @bp.route("/api/lookup-sample", methods=["POST"])
    def lookup_sample():
        user, err = require_logged_in_user()
        if err:
            return err
        data = request.get_json(silent=True) or {}
        sample_unique_id = data.get("sample_unique_id") or data.get("unique_id") or ""
        sample_name = data.get("sample_name") or ""
        sample, l_err = lookup_sample_in_project(
            project_id=user["selected_project"],
            sample_unique_id=sample_unique_id,
            sample_name=sample_name,
        )
        if l_err:
            err_data, code = l_err
            return jsonify(err_data if isinstance(err_data, dict) else {"error": err_data}), code
        return jsonify({
            "found": True,
            "unique_id": sample["unique_id"],
            "sample_name": sample.get("sample_name", ""),
            "sample_type": sample.get("sample_type", ""),
            "description": sample.get("description", ""),
        })

    @bp.route("/api/create-sample", methods=["POST"])
    def create_sample():
        user, err = require_logged_in_user()
        if err:
            return err
        data = request.get_json(silent=True) or {}
        sample_name = (data.get("sample_name") or "").strip()
        sample_type = (data.get("sample_type") or "").strip()
        description = (data.get("description") or "").strip()
        if not sample_name or not sample_type:
            return jsonify({"error": "sample_name and sample_type are required"}), 400

        try:
            created = cruc_client.samples.create(Sample(
                sample_name=sample_name,
                sample_type=sample_type,
                description=description or None,
                owner=user["orcid"],
                project_id=user["selected_project"],
                timestamp=get_tz_isoformat(),
            ))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        return jsonify({
            "unique_id": created["unique_id"],
            "sample_name": created["sample_name"],
            "sample_type": sample_type,
            "description": description,
        })

    @bp.route("/api/print-barcode", methods=["POST"])
    def print_barcode():
        if not session.get("user"):
            return jsonify({"error": "Not authenticated"}), 401
        data = request.get_json(silent=True) or {}
        printer_id = (data.get("printer_id") or tool_config.get("default_printer") or "").strip()
        sample_id = (data.get("sample_id") or "").strip()
        sample_name = (data.get("sample_name") or "").strip()
        if not printer_id:
            return jsonify({"error": "printer_id is required"}), 400
        if not sample_id:
            return jsonify({"error": "sample_id is required"}), 400

        try:
            publish_barcode(printer_id, sample_id, sample_name)
        except Exception as e:
            current_app.logger.error(f"[{log_prefix}] Barcode print failed: {e}")
            return jsonify({"error": str(e)}), 500
        return jsonify({"ok": True, "sample_id": sample_id, "sample_name": sample_name}), 200

    @bp.route("/api/postprocess", methods=["POST"])
    def postprocess():
        user, err = require_logged_in_user()
        if err:
            return err
        data = request.get_json(silent=True) or {}
        dsid = (data.get("dataset_id") or data.get("dataset_mfid") or "").strip()
        if not dsid:
            return jsonify({"error": "dataset_id is required"}), 400

        try:
            ds = cruc_client.datasets.get(dsid)
        except Exception as e:
            return jsonify({"error": f"Dataset not found: {e}"}), 404

        ds_proj = ds.get("project_id")
        user_projects = user.get("projects") or []
        if ds_proj not in user_projects and ds_proj != user.get("selected_project"):
            return jsonify({"error": "Dataset does not belong to user's projects"}), 403

        steps = tool_config.get("post_processing") or []
        results = []
        for step in steps:
            try:
                res = cruc_client.datasets.postprocess(dsid, step)
                results.append(res)
            except Exception as e:
                current_app.logger.error(f"[{log_prefix}] Postprocess '{step}' failed on {dsid}: {e}")
                return jsonify({"error": f"Post-processing '{step}' failed: {e}"}), 500

        return jsonify({"ok": True, "steps": steps, "results": results}), 200

    @bp.route("/api/create-dataset", methods=["POST"])
    def create_dataset():
        user, err = require_logged_in_user()
        if err:
            return err
        data = request.get_json(silent=True) or {}
        embedded_dsid = (data.get("embedded_dsid") or "").strip()
        sha256_hash = (data.get("sha256_hash") or "").strip()
        dataset_name = (data.get("dataset_name") or "").strip() or None
        measurement = (data.get("measurement") or tool_config.get("measurement") or "").strip() or None
        data_type = (data.get("data_type") or tool_config.get("data_type") or "").strip() or None
        data_format = (data.get("data_format") or tool_config.get("data_format") or "").strip() or None
        session_name = (data.get("session_name") or "").strip() or None
        comments = (data.get("comments") or "").strip()
        keywords = data.get("keywords") or []
        sample_unique_id = (data.get("sample_unique_id") or "").strip()

        target_dsid = None
        if embedded_dsid:
            target_dsid = embedded_dsid
        elif sha256_hash:
            valid_dsids = existing_user_project_dsids(user["orcid"], user["selected_project"])
            matched_dsid, is_reused = resolve_dsid_for_sha256(sha256_hash, valid_dsids)
            if is_reused:
                target_dsid = matched_dsid

        sci_meta = {}
        if comments:
            sci_meta["comment"] = comments

        if sample_unique_id:
            try:
                verify_sample_in_project(sample_unique_id, user["selected_project"])
            except CrossProjectError as e:
                return jsonify({"error": str(e)}), 403
            except LookupError as e:
                return jsonify({"error": str(e)}), 404

        try:
            final_dsid, reused = create_or_update_dataset(
                orcid=user["orcid"],
                project_id=user["selected_project"],
                prod_instrument_mfid=tool_config["instrument_mfid"],
                dsid=target_dsid,
                dataset_name=dataset_name,
                measurement=measurement,
                data_type=data_type,
                data_format=data_format,
                session_name=session_name,
                scientific_metadata=sci_meta,
                keywords=keywords,
            )
        except CrossProjectError as e:
            return jsonify({"error": str(e)}), 403
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        if sample_unique_id:
            try:
                cruc_client.datasets.link_sample(dataset_mfid=final_dsid, sample_mfid=sample_unique_id)
            except Exception as e:
                logger.warning(f"Failed linking sample {sample_unique_id} to {final_dsid}: {e}")

        return jsonify({
            "ok": True,
            "dataset_mfid": final_dsid,
            "reused": reused,
            "hub_url": hub_dataset_url(final_dsid),
        }), 200

    @bp.route("/api/recent-datasets", methods=["GET"])
    def recent_datasets():
        user, err = require_logged_in_user()
        if err:
            return err
        try:
            limit = max(1, min(int(request.args.get("limit", 100)), 5000))
            rows = [{k: v for k, v in r.items() if not k.startswith("_")}
                    for r in _get_logbook_rows(user["selected_project"])[:limit]]
            return jsonify({"rows": rows, "count": len(rows)}), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route(f"/api/recent-datasets/<csv_filename>", methods=["GET"])
    def export_recent_datasets_csv(csv_filename):
        user, err = require_logged_in_user()
        if err:
            return err
        try:
            limit = max(1, min(int(request.args.get("limit", 100)), 5000))
            rows = _get_logbook_rows(user["selected_project"])[:limit]
            return csv_response(logbook_cols, rows, csv_filename.rsplit(".", 1)[0])
        except Exception as e:
            return jsonify({"error": str(e)}), 500
