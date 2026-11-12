"""Bulk synthesis upload: one spreadsheet row = one sample + one synthesis dataset.

Ported from manual-synthesis-ui backend/routes/synthesis.py (c25ae5c). Rows are validated in a
read-only pass first (parent references, duplicate names); nothing is written until that
passes or the user confirms.
"""
import logging

import numpy as np
import pandas as pd
from flask import Blueprint, jsonify, render_template
from rdkit import Chem

from crucible import Dataset
from routes import crucible_api
from routes.shared import cruc_client
from routes.synthesis_common import (ApiError, add_sample, current_user, explorer_url, parse_body,
                                     register_error_handlers)
from routes.synthesis_models import (AmbiguousParent, DuplicateName, ParentCandidate, SynthesisUploadRequest,
                                     SynthesisUploadResponse, UnresolvedParent)

logger = logging.getLogger(__name__)
synthesis_bp = Blueprint("synthesis", __name__)
register_error_handlers(synthesis_bp)

# Categories group synthesis types that belong to the same project/workflow. Type names
# (e.g. "Stock Solution") may repeat across categories with entirely different columns and
# parent rules, so all lookups are scoped by category first.
SYNTHESIS_CATEGORIES = {
    "Perovskites_10k": {
        "fields": {
            "Solid Precursor": [
                "Sample Name", "Sample Description", "Notes", "CAS", "RFID", "Name", "SMILES", "Abbrev",
                "Vendor", "Opened Timestamp", "Storage Location", 'NMR_ID'
            ],
            "Stock Solution": [
                "Sample Name", "Sample Description", "Notes", "Organic Salt SP-ID", "Organic Salt Name",
                "Organic Cation Actual Weight mg", "Metal Salt SP-ID", "Metal Salt Name",
                "Metal Cation Actual Weight mg", "Solvent", "Solvent Volume ml",
                "Target Concentration mol", "Storage Location"
            ],
            "Precursor Solution": [
                "Sample Name", "Sample Description", "Notes", "Target Stoichiometry", "Component A SS-ID",
                "Component B SS-ID", "SMILES_Organic", "SMILES_Metal", "Mixing Ratio", "Target Concentration (M)",
                "Storage Location", "PS Autobot Recipe Filename"
            ],
        },
        # Which columns hold parent references, and what sample_type each one must resolve
        # against. Filtering the lookup by type removes most name collisions before they can
        # reach the user.
        "parents": {
            "Stock Solution": {
                "organic_salt_sp-id": {"label": "Organic Salt SP-ID", "parent_type": "solid precursor"},
                "metal_salt_sp-id": {"label": "Metal Salt SP-ID", "parent_type": "solid precursor"},
            },
            "Precursor Solution": {
                "component_a_ss-id": {"label": "Component A SS-ID", "parent_type": "stock solution"},
                "component_b_ss-id": {"label": "Component B SS-ID", "parent_type": "stock solution"},
            },
        },
    },
    "Solgel_Opentrons_Paige": {
        "fields": {
            "Solid Precursor": [
                "Sample Name", "Sample Description", "Notes", "CAS", "RFID", "Name", "SMILES", "Abbrev.",
                "Vendor", "Opened Timestamp", "Storage Location", "NMR_ID"
            ],
            "Stock Solution": [
                "Sample Name", "Sample Description", "Notes", "Metal Salt SP-ID", "Metal Salt Name",
                "Metal Cation Actual Weight mg", "Citric Acid SP-ID", "Citric Acid Actual Weight mg",
                "Solvent", "Solvent Volume ml", "Target Concentration (M)", "Storage Location"
            ],
            "Precursor Solution": [
                "Sample Name", "Sample Description", "Notes", "Target Stoichiometry", "Preparation Method",
                "Target Total Volume (uL)", "Mn Precursor SS-ID", "Mn Precursor Volume uL",
                "Ca Precursor SS-ID", "Ca Precursor Volume uL", "Sr Precursor SS-ID", "Sr Precursor Volume uL",
                "Y Precursor SS-ID", "Y Precursor Volume uL", "Fe Precursor SS-ID", "Fe Precursor Volume uL",
                "Ti Precursor SS-ID", "Ti Precursor Volume uL", "Citric Acid SP-ID",
                "Citric Acid Precursor weight mg", "Ethylene Glycol SP-ID", "EG Volume uL",
                "Storage Location", "Opentrons Recipe Filename"
            ],
        },
        "parents": {
            "Stock Solution": {
                "metal_salt_sp-id": {"label": "Metal Salt SP-ID", "parent_type": "solid precursor"},
                "citric_acid_sp-id": {"label": "Citric Acid SP-ID", "parent_type": "solid precursor"},
            },
            "Precursor Solution": {
                "mn_precursor_ss-id": {"label": "Mn Precursor SS-ID", "parent_type": "stock solution"},
                "ca_precursor_ss-id": {"label": "Ca Precursor SS-ID", "parent_type": "stock solution"},
                "sr_precursor_ss-id": {"label": "Sr Precursor SS-ID", "parent_type": "stock solution"},
                "y_precursor_ss-id": {"label": "Y Precursor SS-ID", "parent_type": "stock solution"},
                "fe_precursor_ss-id": {"label": "Fe Precursor SS-ID", "parent_type": "stock solution"},
                "ti_precursor_ss-id": {"label": "Ti Precursor SS-ID", "parent_type": "stock solution"},
                # These two reference the original solid precursor containers directly, not a
                # stock solution made from them.
                "citric_acid_sp-id": {"label": "Citric Acid SP-ID", "parent_type": "solid precursor"},
                "ethylene_glycol_sp-id": {"label": "Ethylene Glycol SP-ID", "parent_type": "solid precursor"},
            },
        },
    },
}

CRUCIBLE_ID_LENGTH = 26


def canonical(smi):
    """Canonical SMILES, or None if parsing fails or the input is empty."""
    if not isinstance(smi, str) or not smi.strip():
        return None
    mol = Chem.MolFromSmiles(smi)
    return Chem.MolToSmiles(mol) if mol is not None else None


def add_synthesis_dataset(orcid, project, ds_record, synthesis_type, sample_uuid, session_name=None):
    sample_name = ds_record['sample_name']
    ds_obj = Dataset(dataset_name=f'{synthesis_type} recipe for {sample_name}',
                     public=False,
                     owner=orcid,
                     project_id=project,
                     measurement=f"{synthesis_type} synthesis",
                     session_name=session_name,
                     timestamp=ds_record['timestamp'])
    keywords = [k for k in [synthesis_type, sample_name, session_name] if k is not None]
    new_ds = cruc_client.datasets.create(ds_obj, keywords=keywords)
    dataset_mfid = new_ds['created_record']['unique_id']
    crucible_api.add_scientific_metadata(dataset_mfid, ds_record)
    cruc_client.samples.link_dataset(sample_uuid, dataset_mfid)


def _candidate(sample):
    return ParentCandidate(
        unique_id=sample['unique_id'],
        sample_name=sample['sample_name'],
        sample_type=sample.get('sample_type'),
        date_created=sample.get('timestamp') or sample.get('creation_time'),
        description=sample.get('description'),
    )


def _selection_is_valid(unique_id, project, parent_type):
    """The client echoes selections back to us, so re-check them before linking."""
    try:
        sample = cruc_client.samples.get(unique_id)
    except Exception:
        return False
    return bool(sample) and sample.get('project_id') == project and sample.get('sample_type') == parent_type


def resolve_parent_reference(reference, project, parent_type):
    """Resolve one parent reference to a sample unique_id.

    Returns (unique_id, candidates). A unique_id means the reference resolved; otherwise
    candidates holds the competing matches, which is empty when nothing matched at all.
    """
    reference = str(reference).strip()

    # The sheet's *-ID columns may hold a real Crucible id rather than a name.
    if len(reference) == CRUCIBLE_ID_LENGTH:
        try:
            found = cruc_client.samples.get(reference)
        except Exception:
            found = None
        if found:
            return found['unique_id'], []

    matches = cruc_client.samples.list(sample_name=reference, project_id=project, sample_type=parent_type)
    if len(matches) == 1:
        return matches[0]['unique_id'], []
    return None, matches


def validate_rows(records, project, category, synthesis_type, selections):
    """Read-only pass: resolve parent references and find names already in the project.

    Returns (resolved, ambiguous, unresolved, duplicates); resolved maps (row, field) to a
    parent unique_id.
    """
    parent_conf = SYNTHESIS_CATEGORIES[category]["parents"].get(synthesis_type)
    resolved, ambiguous, unresolved, duplicates = {}, [], [], []

    for row, record in records:
        sample_name = record.get('sample_name')

        if sample_name:
            existing = cruc_client.samples.list(sample_name=sample_name, project_id=project)
            if existing:
                duplicates.append(DuplicateName(row=row, sample_name=sample_name, existing_count=len(existing),
                                                existing_ids=[e['unique_id'] for e in existing]))

        if not parent_conf:
            continue

        for field, field_conf in parent_conf.items():
            field_label = field_conf['label']
            parent_type = field_conf['parent_type']
            reference = record.get(field)
            if reference is None or not str(reference).strip():
                continue

            chosen = selections.get((row, field))
            if chosen and _selection_is_valid(chosen, project, parent_type):
                resolved[(row, field)] = chosen
                continue

            parent_id, candidates = resolve_parent_reference(reference, project, parent_type)
            if parent_id:
                resolved[(row, field)] = parent_id
            elif candidates:
                ambiguous.append(AmbiguousParent(row=row, sample_name=sample_name, field=field,
                                                 field_label=field_label, reference=str(reference).strip(),
                                                 candidates=[_candidate(c) for c in candidates]))
            else:
                unresolved.append(UnresolvedParent(row=row, sample_name=sample_name, field=field,
                                                   field_label=field_label, reference=str(reference).strip(),
                                                   expected_type=parent_type))

    return resolved, ambiguous, unresolved, duplicates


def prepare_records(dataset_df):
    """Normalise the sheet and pair each row with its original position."""
    dataset_df = dataset_df.replace('', np.nan).dropna(how='all')
    # Empty cells become None. (replace(np.nan, None) no longer does this in pandas 3.)
    dataset_df = dataset_df.astype(object).where(dataset_df.notna(), None)
    dataset_df.columns = [x.lower().replace(' ', '_') for x in dataset_df.columns]
    # dropna keeps the original labels, so the index still points at the row the user sees.
    return list(zip(dataset_df.index.tolist(), dataset_df.to_dict('records')))


def upload_all_sample_synthesis_info(orcid, project, records, category, synthesis_type, resolved, unresolved,
                                     session_name=None):
    parent_field_names = list(SYNTHESIS_CATEGORIES[category]["parents"].get(synthesis_type, {}))

    # Rows whose parent reference matched nothing are skipped outright rather than written
    # without their genealogy.
    skip = {}
    for u in unresolved:
        skip.setdefault(u.row, []).append(f"{u.field_label} '{u.reference}' matched no {u.expected_type}")

    success_count = failed_count = 0
    error_messages, created_samples = [], []

    for row, record in records:
        display_row = row + 1
        sample_name = record.get('sample_name', 'Unknown')

        if row in skip:
            failed_count += 1
            error_messages.append(f"Row {display_row} '{sample_name}': {'; '.join(skip[row])} — row skipped, nothing written")
            continue

        try:
            new_samp = add_sample(orcid=orcid, project=project, sample_name=record['sample_name'],
                                  description=record['sample_description'], sample_type=synthesis_type.lower())
            sample_uuid = new_samp['unique_id']
            created_samples.append({'sample_name': record['sample_name'], 'unique_id': sample_uuid,
                                    'explorer_url': explorer_url(project, sample_uuid)})

            for field in parent_field_names:
                parent_id = resolved.get((row, field))
                if parent_id:
                    cruc_client.samples.link(parent_id, sample_uuid)

            record.update({f'{k}_canonical': canonical(v) for k, v in record.items() if 'smiles' in k.lower()})
            add_synthesis_dataset(orcid, project, record, synthesis_type, sample_uuid, session_name)
            success_count += 1
        except Exception as err:
            failed_count += 1
            error_messages.append(f"Row {display_row} '{sample_name}': {err}")
            logger.error(f"dataset upload failed for {record} with error: {err}")

    summary = {
        "Project": project,
        "Synthesis Type": synthesis_type,
        "Samples Uploaded": success_count,
        "Failed": failed_count,
        "Total Rows": len(records),
        "Created Samples": created_samples,
    }
    if error_messages:
        summary["Errors"] = error_messages

    if failed_count == 0 and success_count > 0:
        status_msg = f"Successfully uploaded {success_count} samples to project '{project}'"
    elif success_count == 0 and failed_count > 0:
        status_msg = f"Upload failed: All {failed_count} samples failed to upload"
    elif success_count > 0 and failed_count > 0:
        status_msg = f"Partial upload: {success_count} samples uploaded successfully, {failed_count} failed"
    else:
        status_msg = "No samples to upload"
    return status_msg, summary


@synthesis_bp.route("/")
def page():
    return render_template("synthesis.html")


@synthesis_bp.route("/api/fields", methods=["GET"])
def get_synthesis_fields():
    return jsonify({"categories": {name: conf["fields"] for name, conf in SYNTHESIS_CATEGORIES.items()}})


@synthesis_bp.route("/api/upload", methods=["POST"])
def upload_synthesis_data():
    req = parse_body(SynthesisUploadRequest)
    user = current_user(req.project)
    if req.category not in SYNTHESIS_CATEGORIES:
        raise ApiError(400, f"Unknown synthesis category: {req.category}")
    if req.synthesis_type not in SYNTHESIS_CATEGORIES[req.category]["fields"]:
        raise ApiError(400, f"Unknown synthesis type for {req.category}: {req.synthesis_type}")
    if not req.data:
        return jsonify(SynthesisUploadResponse(success=False, message="No data provided for upload").model_dump())

    records = prepare_records(pd.DataFrame(req.data))
    selections = {(s.row, s.field): s.unique_id for s in req.parent_selections}

    # Pass 1 is read-only, so halting here leaves Crucible untouched.
    resolved, ambiguous, unresolved, duplicates = validate_rows(
        records, req.project, req.category, req.synthesis_type, selections)

    if ambiguous:
        return jsonify(SynthesisUploadResponse(
            success=False,
            message=f"{len(ambiguous)} parent reference(s) match more than one sample. "
                    f"Choose which one to link, then upload again. Nothing has been uploaded yet.",
            needs_selection=ambiguous, unresolved_parents=unresolved, duplicate_names=duplicates,
        ).model_dump())

    if duplicates and not req.confirm_duplicate_names:
        return jsonify(SynthesisUploadResponse(
            success=False,
            message=f"{len(duplicates)} of {len(records)} rows use a Sample Name that already exists in "
                    f"'{req.project}'. Confirm to upload them anyway. Nothing has been uploaded yet.",
            unresolved_parents=unresolved, duplicate_names=duplicates,
        ).model_dump())

    status_msg, summary = upload_all_sample_synthesis_info(
        orcid=user["orcid"], project=req.project, records=records, category=req.category,
        synthesis_type=req.synthesis_type, resolved=resolved, unresolved=unresolved,
        session_name=req.session_name)
    return jsonify(SynthesisUploadResponse(success=True, message=status_msg, summary=summary).model_dump())
