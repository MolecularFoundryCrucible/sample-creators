"""Request/response models for the synthesis upload and fabrication traveler APIs.

Ported from manual-synthesis-ui backend/models.py (c25ae5c). Identity fields (orcid, email,
user_name, operator) are optional: the server always takes them from the logged-in session,
whatever the client sends.
"""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel

# ---------- Synthesis ----------


class ParentCandidate(BaseModel):
    unique_id: str
    sample_name: str
    sample_type: Optional[str] = None
    date_created: Optional[str] = None
    description: Optional[str] = None


class AmbiguousParent(BaseModel):
    """A parent reference matching several samples; the user must pick one."""
    row: int
    sample_name: Optional[str] = None
    field: str
    field_label: str
    reference: str
    candidates: List[ParentCandidate]


class UnresolvedParent(BaseModel):
    """A parent reference matching no sample of the expected type."""
    row: int
    sample_name: Optional[str] = None
    field: str
    field_label: str
    reference: str
    expected_type: str


class DuplicateName(BaseModel):
    row: int
    sample_name: str
    existing_count: int
    existing_ids: List[str]


class ParentSelection(BaseModel):
    row: int
    field: str
    unique_id: str


class SynthesisUploadRequest(BaseModel):
    project: str
    category: str
    synthesis_type: str
    data: List[Dict[str, Any]]
    session_name: Optional[str] = None
    # Set by the client after the user resolves an earlier validation response.
    parent_selections: List[ParentSelection] = []
    confirm_duplicate_names: bool = False
    email: Optional[str] = None
    orcid: Optional[str] = None
    user_name: Optional[str] = None


class SynthesisUploadResponse(BaseModel):
    success: bool
    message: str
    summary: Optional[Dict[str, Any]] = None
    # Populated when validation halted the upload before anything was written.
    needs_selection: List[AmbiguousParent] = []
    unresolved_parents: List[UnresolvedParent] = []
    duplicate_names: List[DuplicateName] = []


# ---------- Fabrication traveler ----------


class PlannedChiplet(BaseModel):
    block: str
    name: str


class WaferCreateRequest(BaseModel):
    project: str
    template_id: str
    wafer_name: str
    description: str = ""
    wafer_options: Dict[str, str]
    template_default: str = "standard"
    spec: Dict[str, Any] = {}
    planned_chiplets: List[PlannedChiplet] = []
    step_date: Optional[str] = None
    orcid: Optional[str] = None
    operator: Optional[str] = None


class StepRecordRequest(BaseModel):
    template_id: str
    step_id: str
    wafer_id: str
    project: str
    target_ids: List[str]
    status: Literal["done", "skipped"]
    step_date: str
    # {row_key: {field_key: value}} for the step's sub-step rows.
    rows: Dict[str, Dict[str, Any]] = {}
    # Which template default the form started from (for the record).
    template_default: Optional[str] = None
    comments: Optional[str] = None
    # For create_chiplets / create_chips steps: parent unique_id -> new child names.
    new_children: Dict[str, List[str]] = {}
    # New child sample name -> map-derived scientific metadata.
    child_details: Dict[str, Dict[str, Any]] = {}
    orcid: Optional[str] = None
    operator: Optional[str] = None


class StepEditRequest(BaseModel):
    step_date: str
    rows: Dict[str, Dict[str, Any]] = {}
    # Only used when editing the wafer specification record.
    parameters: Dict[str, Any] = {}
    # None preserves the existing plan; an empty list explicitly clears it.
    planned_chiplets: Optional[List[PlannedChiplet]] = None
    comments: Optional[str] = None
    orcid: Optional[str] = None
    operator: Optional[str] = None


class PrintLabelRequest(BaseModel):
    printer_id: str
    sample_id: str


class MaskCreateRequest(BaseModel):
    project: str
    dataset_name: str


class ChipMapBlock(BaseModel):
    id: str
    name: str


class ChipMapChip(BaseModel):
    id: str
    block: str
    label: str
    outline: List[float]
    layer: Optional[str] = None


class ChipMapCreateRequest(BaseModel):
    units: Literal["mm"] = "mm"
    blocks: List[ChipMapBlock]
    chips: List[ChipMapChip]
    expected_version: int = 0
