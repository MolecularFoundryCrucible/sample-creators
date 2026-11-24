"""Reusable backend routes for TEM session folder uploaders.

Provides session lookup, parent session creation/resume, and batched child
dataset preparation with session-scoped SHA-256 deduplication and fail-closed
cross-project checks.
"""
from __future__ import annotations

import logging
from typing import Any

from flask import jsonify, request

from crucible.utils.identifiers import is_mfid
from routes.shared import cruc_client
from routes.uploader_common import (
    CrossProjectError,
    create_or_update_dataset,
    hub_dataset_url,
    list_existing_dataset_filenames,
    require_logged_in_user,
    resolve_dsid_for_sha256,
    verify_sample_in_project,
)

logger = logging.getLogger(__name__)

MAX_PREPARE_ITEMS = 50


def _validate_folder_name(raw_folder_name: Any) -> tuple[str | None, str | None]:
    """Validate that raw_folder_name is a non-empty single folder basename."""
    if not isinstance(raw_folder_name, str):
        return None, "folder_name is required and must be a string"
    folder_name = raw_folder_name.strip()
    if not folder_name:
        return None, "folder_name is required"
    if folder_name in (".", "..") or ".." in folder_name:
        return None, "folder_name must be a valid single folder basename"
    if "/" in folder_name or "\\" in folder_name:
        return None, "folder_name must not contain path separators"
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in folder_name):
        return None, "folder_name must not contain control characters"
    return folder_name, None


def _normalize_keywords(raw_keywords: Any) -> tuple[list[str] | None, str | None]:
    """Normalize optional keywords list or comma-separated string."""
    if raw_keywords is None or raw_keywords == "":
        return [], None
    if isinstance(raw_keywords, list):
        return [k.strip() for k in raw_keywords if isinstance(k, str) and k.strip()], None
    if isinstance(raw_keywords, str):
        return [k.strip() for k in raw_keywords.split(",") if k.strip()], None
    return None, "keywords must be a list of strings"


def _dataset_owned_by(ds: dict, orcid: str) -> bool:
    """Check whether dataset dict ds is owned by orcid."""
    if not orcid:
        return True
    if ds.get("owner_orcid") == orcid:
        return True
    owner = ds.get("owner")
    if isinstance(owner, dict):
        return orcid in (owner.get("orcid"), owner.get("unique_id"))
    if isinstance(owner, str):
        return owner == orcid
    return False


def _get_dataset_in_project(dsid: Any, selected_project: str) -> tuple[dict | None, tuple[Any, int] | None]:
    """Validate dsid MFID, fetch it from Crucible, and enforce project ownership (fail-closed)."""
    if not isinstance(dsid, str) or not dsid.strip() or not is_mfid(dsid.strip()):
        return None, (jsonify({"error": "A valid dataset MFID is required"}), 400)
    clean_dsid = dsid.strip()
    try:
        ds = cruc_client.datasets.get(clean_dsid)
    except Exception as e:
        status = getattr(e, "status", None)
        if status is None:
            status = getattr(getattr(e, "response", None), "status_code", None)
        if status == 404:
            return None, (jsonify({"error": f"Dataset '{clean_dsid}' not found"}), 404)
        if status == 403:
            return None, (jsonify({"error": f"Access denied for dataset '{clean_dsid}'"}), 403)
        return None, (jsonify({"error": f"Failed fetching dataset '{clean_dsid}': {e}"}), 500)

    if not ds or not ds.get("unique_id"):
        return None, (jsonify({"error": f"Dataset '{clean_dsid}' not found"}), 404)

    ds_proj = ds.get("project_id") or (ds.get("project") or {}).get("project_id")
    if ds_proj != selected_project:
        return None, (
            jsonify({"error": f"Dataset '{clean_dsid}' belongs to project '{ds_proj}', not '{selected_project}'"}),
            403,
        )
    return ds, None


def _validate_optional_sample(raw_sample_id: Any, selected_project: str) -> tuple[str, tuple[Any, int] | None]:
    """Validate an optional sample_unique_id and ensure it belongs to selected_project."""
    if raw_sample_id is None or raw_sample_id == "":
        return "", None
    if not isinstance(raw_sample_id, str):
        return "", (jsonify({"error": "sample_unique_id must be a string"}), 400)
    sample_uid = raw_sample_id.strip()
    if not sample_uid:
        return "", None
    try:
        verify_sample_in_project(sample_uid, selected_project)
    except CrossProjectError as e:
        return "", (jsonify({"error": str(e)}), 403)
    except LookupError as e:
        return "", (jsonify({"error": str(e)}), 404)
    return sample_uid, None


def _parse_prepare_items(raw_items: Any) -> tuple[list[dict] | None, str | None]:
    """Validate and normalize items for /api/session/prepare-children."""
    if not isinstance(raw_items, list) or not raw_items:
        return None, "items must be a non-empty list"
    if len(raw_items) > MAX_PREPARE_ITEMS:
        return None, f"items must contain at most {MAX_PREPARE_ITEMS} entries per request"

    parsed: list[dict] = []
    for idx, item in enumerate(raw_items):
        if not isinstance(item, dict):
            return None, f"items[{idx}] must be an object"
        raw_cid = item.get("client_id")
        raw_name = item.get("dataset_name")
        if not isinstance(raw_cid, str) or not raw_cid.strip():
            return None, f"items[{idx}].client_id is required"
        if not isinstance(raw_name, str) or not raw_name.strip():
            return None, f"items[{idx}].dataset_name is required"
        raw_sha = item.get("sha256_hash")
        sha256_hash = raw_sha.strip() if isinstance(raw_sha, str) and raw_sha.strip() else None
        raw_fmt = item.get("data_format")
        data_format = raw_fmt.strip() if isinstance(raw_fmt, str) and raw_fmt.strip() else None
        parsed.append({
            "client_id": raw_cid.strip(),
            "dataset_name": raw_name.strip(),
            "sha256_hash": sha256_hash,
            "data_format": data_format,
        })
    return parsed, None


def _list_matching_session_datasets(project_id: str, session_dataset_name: str, orcid: str) -> list[dict]:
    """Return session datasets in project_id matching session_dataset_name owned by orcid."""
    try:
        ds_list = cruc_client.datasets.list(
            project_id=project_id,
            dataset_name=session_dataset_name,
            include_owner=True,
            limit=None,
        )
    except TypeError:
        ds_list = cruc_client.datasets.list(
            project_id=project_id,
            dataset_name=session_dataset_name,
            limit=None,
        )

    matches = []
    for ds in ds_list:
        uid = ds.get("unique_id")
        if not uid:
            continue
        if ds.get("dataset_name") != session_dataset_name:
            continue
        ds_proj = ds.get("project_id") or (ds.get("project") or {}).get("project_id")
        if ds_proj != project_id:
            continue
        if not _dataset_owned_by(ds, orcid):
            continue
        matches.append({
            "unique_id": uid,
            "dataset_name": ds.get("dataset_name") or session_dataset_name,
            "creation_time": ds.get("creation_time"),
            "modification_time": ds.get("modification_time"),
            "hub_url": hub_dataset_url(uid),
        })
    return matches


def _try_list_existing_filenames(dataset_mfid: str) -> list[str] | None:
    """Return existing filenames stored on dataset_mfid, or None if list_files raises."""
    try:
        files = cruc_client.datasets.list_files(dataset_mfid) or []
    except Exception as e:
        logger.warning(f"Failed listing files for candidate dataset '{dataset_mfid}': {e}")
        return None
    seen: set[str] = set()
    filenames: list[str] = []
    for f in files:
        if not isinstance(f, dict):
            continue
        name = f.get("filename") or f.get("name") or f.get("file_name")
        if isinstance(name, str) and name and name not in seen:
            seen.add(name)
            filenames.append(name)
    return filenames


_list_existing_filenames = list_existing_dataset_filenames


def register_session_uploader_routes(bp, tool_config: dict) -> None:
    """Register TEM session check, start, and child-preparation routes on bp."""
    tool_name = tool_config["name"]
    prod_instrument_mfid = tool_config["instrument_mfid"]

    @bp.route("/api/session/check", methods=["POST"])
    def session_check():
        user, err = require_logged_in_user()
        if err:
            return err
        data = request.get_json(silent=True) or {}
        folder_name, fn_err = _validate_folder_name(data.get("folder_name"))
        if fn_err:
            return jsonify({"error": fn_err}), 400

        selected_project = user["selected_project"]
        session_dataset_name = f"{tool_name} session: {folder_name}"
        try:
            matches = _list_matching_session_datasets(
                project_id=selected_project,
                session_dataset_name=session_dataset_name,
                orcid=user.get("orcid") or "",
            )
        except Exception as e:
            return jsonify({"error": f"Failed checking existing sessions: {e}"}), 500

        return jsonify({
            "ok": True,
            "session_name": folder_name,
            "session_dataset_name": session_dataset_name,
            "matches": matches,
        }), 200

    @bp.route("/api/session/start", methods=["POST"])
    def session_start():
        user, err = require_logged_in_user()
        if err:
            return err
        data = request.get_json(silent=True) or {}
        folder_name, fn_err = _validate_folder_name(data.get("folder_name"))
        if fn_err:
            return jsonify({"error": fn_err}), 400

        raw_existing = data.get("existing_session_dsid")
        if raw_existing is not None and not isinstance(raw_existing, str):
            return jsonify({"error": "existing_session_dsid must be a string"}), 400
        existing_session_dsid = (raw_existing or "").strip()

        raw_comments = data.get("comments")
        if raw_comments is not None and not isinstance(raw_comments, str):
            return jsonify({"error": "comments must be a string"}), 400
        comments = (raw_comments or "").strip()

        keywords, kw_err = _normalize_keywords(data.get("keywords"))
        if kw_err:
            return jsonify({"error": kw_err}), 400

        selected_project = user["selected_project"]
        sample_uid, sample_err = _validate_optional_sample(data.get("sample_unique_id"), selected_project)
        if sample_err:
            return sample_err

        expected_ds_name = f"{tool_name} session: {folder_name}"
        if existing_session_dsid and existing_session_dsid != "new":
            existing_ds, ds_err = _get_dataset_in_project(existing_session_dsid, selected_project)
            if ds_err:
                return ds_err
            session_dsid = existing_session_dsid
            ds_name = existing_ds.get("dataset_name") or expected_ds_name
            reused = True
        else:
            try:
                session_dsid, reused = create_or_update_dataset(
                    orcid=user["orcid"],
                    project_id=selected_project,
                    prod_instrument_mfid=prod_instrument_mfid,
                    dataset_name=expected_ds_name,
                    measurement=f"full {tool_name} session",
                    session_name=folder_name,
                    scientific_metadata={"comments": comments} if comments else None,
                    keywords=keywords,
                )
            except CrossProjectError as e:
                return jsonify({"error": str(e)}), 403
            except Exception as e:
                return jsonify({"error": str(e)}), 500
            ds_name = expected_ds_name

        if sample_uid:
            try:
                cruc_client.datasets.link_sample(dataset_mfid=session_dsid, sample_mfid=sample_uid)
            except Exception as e:
                logger.warning(f"Failed linking sample {sample_uid} to session {session_dsid}: {e}")

        return jsonify({
            "ok": True,
            "session_dsid": session_dsid,
            "session_name": folder_name,
            "dataset_name": ds_name,
            "reused": reused,
            "hub_url": hub_dataset_url(session_dsid),
        }), 200

    @bp.route("/api/session/prepare-children", methods=["POST"])
    def session_prepare_children():
        user, err = require_logged_in_user()
        if err:
            return err
        data = request.get_json(silent=True) or {}

        items, items_err = _parse_prepare_items(data.get("items"))
        if items_err:
            return jsonify({"error": items_err}), 400

        raw_comments = data.get("comments")
        if raw_comments is not None and not isinstance(raw_comments, str):
            return jsonify({"error": "comments must be a string"}), 400
        comments = (raw_comments or "").strip()

        keywords, kw_err = _normalize_keywords(data.get("keywords"))
        if kw_err:
            return jsonify({"error": kw_err}), 400

        selected_project = user["selected_project"]
        parent_ds, parent_err = _get_dataset_in_project(data.get("session_dsid"), selected_project)
        if parent_err:
            return parent_err
        session_dsid = parent_ds["unique_id"]

        sample_uid, sample_err = _validate_optional_sample(data.get("sample_unique_id"), selected_project)
        if sample_err:
            return sample_err

        raw_session_name = data.get("session_name")
        if raw_session_name is not None and not isinstance(raw_session_name, str):
            return jsonify({"error": "session_name must be a string"}), 400
        effective_session_name = (raw_session_name or "").strip() or parent_ds.get("session_name") or None

        try:
            existing_children = cruc_client.datasets.list_children(session_dsid, limit=None)
        except Exception as e:
            return jsonify({"error": f"Failed listing children for session '{session_dsid}': {e}"}), 500

        # Snapshot existing session children before preparing this batch so SHA-256
        # deduplication is strictly scoped to children already linked to this session.
        valid_child_dsids = {
            c["unique_id"] for c in (existing_children or [])
            if isinstance(c, dict) and c.get("unique_id")
        }

        # Accept optional "exclude_dsids" list in request JSON and seed claimed_child_dsids
        raw_exclude = data.get("exclude_dsids") or []
        claimed_child_dsids: set[str] = {
            d.strip() for d in raw_exclude
            if isinstance(d, str) and d.strip()
        }

        candidates_by_name: dict[str, list[str]] = {}
        for c in (existing_children or []):
            if isinstance(c, dict) and c.get("unique_id"):
                dname = c.get("dataset_name")
                if isinstance(dname, str) and dname:
                    candidates_by_name.setdefault(dname, []).append(c["unique_id"])

        files_cache: dict[str, list[str] | None] = {}

        children = []
        for item in items:
            matched_dsid = None
            same_name_unclaimed = {
                d for d in candidates_by_name.get(item["dataset_name"], [])
                if d not in claimed_child_dsids
            }
            if item["sha256_hash"] and same_name_unclaimed:
                matched_dsid, _ = resolve_dsid_for_sha256(item["sha256_hash"], same_name_unclaimed)
                if matched_dsid:
                    claimed_child_dsids.add(matched_dsid)

            if matched_dsid is None:
                for cand_dsid in candidates_by_name.get(item["dataset_name"], []):
                    if cand_dsid in claimed_child_dsids:
                        continue
                    if cand_dsid not in files_cache:
                        files_cache[cand_dsid] = _try_list_existing_filenames(cand_dsid)
                    cand_files = files_cache[cand_dsid]
                    if cand_files is None:
                        continue
                    if item["dataset_name"] not in cand_files:
                        matched_dsid = cand_dsid
                        claimed_child_dsids.add(cand_dsid)
                        break

            try:
                child_dsid, reused = create_or_update_dataset(
                    orcid=user["orcid"],
                    project_id=selected_project,
                    prod_instrument_mfid=prod_instrument_mfid,
                    dsid=matched_dsid,
                    dataset_name=item["dataset_name"],
                    data_format=item["data_format"],
                    session_name=effective_session_name,
                    scientific_metadata={"comment": comments} if comments else None,
                    keywords=keywords,
                )
            except CrossProjectError as e:
                return jsonify({"error": str(e)}), 403
            except Exception as e:
                return jsonify({"error": str(e)}), 500

            if child_dsid not in valid_child_dsids:
                try:
                    cruc_client.datasets.link(session_dsid, child_dsid)
                except Exception as e:
                    return jsonify({"error": f"Failed linking child '{child_dsid}' to session '{session_dsid}': {e}"}), 500

            if sample_uid:
                try:
                    cruc_client.datasets.link_sample(dataset_mfid=child_dsid, sample_mfid=sample_uid)
                except Exception as e:
                    logger.warning(f"Failed linking sample {sample_uid} to child {child_dsid}: {e}")

            if reused:
                if child_dsid not in files_cache or files_cache[child_dsid] is None:
                    files_cache[child_dsid] = _try_list_existing_filenames(child_dsid)
                existing_filenames = files_cache[child_dsid] or []
            else:
                existing_filenames = []

            children.append({
                "client_id": item["client_id"],
                "dataset_mfid": child_dsid,
                "reused": reused,
                "existing_filenames": existing_filenames,
                "hub_url": hub_dataset_url(child_dsid),
            })

        return jsonify({
            "ok": True,
            "session_dsid": session_dsid,
            "children": children,
        }), 200
