from typing import Optional, Dict, List

from pydantic import BaseModel, JsonValue


class GenericMessageResponse(BaseModel):
    message: str


class User(BaseModel):
    """Base user."""
    id: int
    username: str
    first_name: str
    last_name: str
    email: str
    groups: List[int]
    date_joined: str


class UserBasic(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: str


#
# Beamlines
#

class Beamline(BaseModel):
    id: int
    slug: str
    name: str
    description: Optional[str] = None
    external_link: Optional[str] = None
    ids_owners: List[int]
    ids_watchers: List[int]
    set_noun: str


class BeamlineCreateDto(BaseModel):
    slug: Optional[str] = None
    name: str
    description: Optional[str] = None
    external_link: Optional[str] = None
    ids_owners: List[int] = []
    ids_watchers: List[int] = []
    set_noun: str


class BeamlineUpdateDto(BaseModel):
    id: int
    slug: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    external_link: Optional[str] = None
    ids_owners: Optional[List[int]] = None
    ids_watchers: Optional[List[int]] = None
    set_noun: Optional[str] = None


#
# Proposals
#

class Proposal(BaseModel):
    id: int
    slug: str
    name: str
    description: Optional[str] = None
    external_link: Optional[str] = None
    ids_owners: List[int] = []
    ids_editors: List[int] = []
    ids_watchers: List[int] = []
    date_record_created: str


class ProposalCreateDto(BaseModel):
    slug: Optional[str] = None
    name: str
    description: Optional[str] = None
    external_link: Optional[str] = None
    ids_owners: List[int] = []
    ids_editors: List[int] = []
    ids_watchers: List[int] = []


class ProposalUpdateDto(BaseModel):
    id: int
    slug: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    external_link: Optional[str] = None
    ids_owners: Optional[List[int]] = None
    ids_editors: Optional[List[int]] = None
    ids_watchers: Optional[List[int]] = None


#
# ESAFs
#

class Esaf(BaseModel):
    id: int
    slug: str
    name: str
    description: Optional[str] = None
    slug_beamline: str
    slug_proposal: str
    date_earliest_start: Optional[str] = None
    date_latest_end: Optional[str] = None
    ids_owners: List[int] = []
    ids_editors: List[int] = []
    ids_watchers: List[int] = []
    archived: bool = False
    date_record_created: str


class EsafCreateDto(BaseModel):
    slug: Optional[str] = None
    name: str
    description: Optional[str] = None
    slug_beamline: str
    slug_proposal: str
    date_earliest_start: Optional[str] = None
    date_latest_end: Optional[str] = None
    ids_owners: List[int] = []
    ids_editors: List[int] = []
    ids_watchers: List[int] = []


class EsafUpdateDto(BaseModel):
    id: int
    slug: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    date_earliest_start: Optional[str] = None
    date_latest_end: Optional[str] = None
    ids_owners: Optional[List[int]] = None
    ids_editors: Optional[List[int]] = None
    ids_watchers: Optional[List[int]] = None
    archived: Optional[bool] = None


#
# Parameters
#

class ParameterValidatorStep(BaseModel):
    type: Optional[str] = None
    arguments: Optional[List] = None
    and_: Optional[List["ParameterValidatorStep"]] = None
    or_: Optional[List["ParameterValidatorStep"]] = None
    not_: Optional[bool] = None


class Parameter(BaseModel):
    id: int
    slug: str
    name: str
    description: str
    slug_beamline: str
    # Universal ordering of this parameter in the UI relative to the others for the Beamline
    _order: int
    id_derived_from: Optional[int] = None
    # If no default is provided the default is assumed to be "".
    standard_default: Optional[str] = None
    # If the value should be unique across all samples in the same set.
    enforce_unique_in_set: bool = False
    # When new instances are generated, and the value should be unique, use this interval when auto-generating new values.
    auto_generate_interval: Optional[str] = None
    # If a choices field is present, we provide a pulldown instead of a text field and restrict the choices to this list.
    # Choices are expressed as a dict, with a short unique "name" value and a longer "description" value.
    choices: Optional[List[Dict[str, str]]] = None
    validation: Optional[ParameterValidatorStep] = None
    schema_identifier: Optional[str] = None
    date_last_modified: str


class ParameterCreateDto(BaseModel):
    slug: Optional[str] = None
    name: str
    description: Optional[str] = None
    id_derived_from: Optional[int] = None
    # If no default is provided the default is assumed to be "".
    standard_default: Optional[str] = None
    # If the value should be unique across all samples in the same set.
    enforce_unique_in_set: bool = False
    # When new instances are generated, and the value should be unique, use this interval when auto-generating new values.
    auto_generate_interval: Optional[str] = None
    # If a choices field is present, we provide a pulldown instead of a text field and restrict the choices to this list.
    # Choices are expressed as a dict, with a short unique "name" value and a longer "description" value.
    choices: Optional[List[Dict[str, str]]] = None
    validation: Optional[ParameterValidatorStep] = None
    schema_identifier: Optional[str] = None


class ParameterUpdateDto(BaseModel):
    id: int
    slug: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    id_derived_from: Optional[int] = None
    # If no default is provided the default is assumed to be "".
    standard_default: Optional[str] = None
    # If the value should be unique across all samples in the same set.
    enforce_unique_in_set: Optional[bool] = None
    # When new instances are generated, and the value should be unique, use this interval when auto-generating new values.
    auto_generate_interval: Optional[str] = None
    # If a choices field is present, we provide a pulldown instead of a text field and restrict the choices to this list.
    # Choices are expressed as a dict, with a short unique "name" value and a longer "description" value.
    choices: Optional[List[Dict[str, str]]] = None
    validation: Optional[ParameterValidatorStep] = None
    schema_identifier: Optional[str] = None


#
# Parameter Settings
#

class ParameterSettings(BaseModel):
    id: int
    id_parameter: int
    slug_scan_type: str
    # If no default is provided the default is assumed to be "".
    default: Optional[str] = None
    read_only: bool = False
    # If a non-blank value is mandatory for this parameter
    required: bool = False


class ParameterSettingsCreateDto(BaseModel):
    id_parameter: int
    slug_scan_type: str
    default: Optional[str] = None
    read_only: Optional[bool] = None
    required: Optional[bool] = None


class ParameterSettingsUpdateDto(BaseModel):
    id: int
    # If no default is provided the default is assumed to be "".
    default: Optional[str] = None
    read_only: Optional[bool] = None
    # If a non-blank value is mandatory for this parameter
    required: Optional[bool] = None


#
# Scan Types
#

class ScanType(BaseModel):
    id: int
    slug: str
    name: str
    slug_beamline: str
    description: Optional[str] = None
    slug_derived_from: Optional[str] = None
    deprecated: bool
    parameters: List[ParameterSettings]
    date_last_modified: str
    date_record_created: str


class ScanTypeCreateDto(BaseModel):
    slug: Optional[str] = None
    name: str
    slug_beamline: str
    description: Optional[str] = None
    slug_derived_from: Optional[str] = None


class ScanTypeUpdateDto(BaseModel):
    slug: str
    name: Optional[str] = None
    description: Optional[str] = None
    slug_derived_from: Optional[str] = None
    deprecated: Optional[bool] = None
    parameters: Optional[List[ParameterSettings]] = None


#
# Sample Sets
#

class SampleSetDto(BaseModel):
    id: int
    slug: str
    # Intended to be short and unique within an ESAF, but this is not strictly enforced.
    name: str
    # Meant to be longer than the name.  Can be blank.
    description: str
    slug_esaf: str
    slug_beamline: str
    slug_proposal: str
    scan_status: str
    id_most_recent_editor: int
    date_last_modified: str
    slugs_samples: List[str]


class SampleSetCreateDto(BaseModel):
    slug: Optional[str] = None
    # Intended to be short and unique, but this is not strictly enforced.
    name: str
    # Meant to be longer than the name.  Can be blank.
    description: str
    slug_esaf: str


class SampleSetUpdateDto(BaseModel):
    slug: str
    # Intended to be short and unique, but this is not strictly enforced.
    name: Optional[str] = None
    # Meant to be longer than the name.  Can be blank.
    description: Optional[str] = None


#
# Samples
#

class SampleParameterValueBasicDto(BaseModel):
    id: int
    id_parameter: int
    value: JsonValue


class SampleDto(BaseModel):
    slug: str
    # Intended to be short and unique, but this is not strictly enforced.
    name: str
    # Meant to be longer than the name.  Can be blank.
    description: str
    # Unique slug identifier of the set this config belongs to.
    slug_set: str
    slug_esaf: str
    slug_scan_type: str
    scan_status: str
    id_most_recent_editor: int
    date_last_modified: str


class SampleCreateDto(BaseModel):
    slug: Optional[str] = None
    # Intended to be short and unique, but this is not strictly enforced.
    name: str
    # Meant to be longer than the name.  Can be blank.
    description: str
    # Unique slug identifier of the set this config belongs to.
    slug_set: str
    slug_scan_type: str


class SampleUpdateDto(BaseModel):
    slug: str
    # Intended to be short and unique, but this is not strictly enforced.
    name: Optional[str] = None
    # Meant to be longer than the name.  Can be blank.
    description: Optional[str] = None
    slug_scan_type: Optional[str] = None
    scan_status: Optional[str] = None


# Special DTO for an endpoint that mass-sets parameter values by name.
class SampleSetParameterValuesByNameDto(BaseModel):
    create_parameters_if_missing: Optional[bool] = None
    allow_parameters_not_in_scan_type: Optional[bool] = None
    add_parameters_to_scan_type_if_missing: Optional[bool] = None
    remove_other_values: Optional[bool] = None
    values: Dict[str, JsonValue]


# Special DTO for fetching parameter values of a sample in dictionary format.
class SampleGetParameterValuesByNameDto(BaseModel):
    id: int
    slug: str
    slug_set: str
    # Intended to be short and unique, but this is not strictly enforced.
    name: str
    # Parameter values may be given for Parameters that are not in the currently chosen ScanType.
    # This is not strictly enforced, so old inapplicable values can be preserved
    # in case a previous ScanType is re-selected.
    parameter_values_by_name: Dict[str, JsonValue]


#
# Parameter Values
#


# Used at /api/values/, but there are better endpoints to use (see Samples)
class ParameterValueDto(BaseModel):
    id: int
    slug_sample: str
    slug_parameter: str
    parameter_name: str
    parameter_description: str
    parameter_schema_identifier: str
    value: JsonValue


#
# Additional detailed models
#

class ParameterSettingsDetails(BaseModel):
    parameter: Parameter
    # If no default is provided the default is assumed to be "".
    default: Optional[str] = None
    read_only: bool = False
    # If a non-blank value is mandatory for this parameter
    required: bool = False


class ScanTypeDetails(BaseModel):
    id: int
    slug: str
    name: str
    slug_beamline: str
    description: Optional[str] = None
    slug_derived_from: Optional[str] = None
    deprecated: bool = False
    parameters: List[ParameterSettingsDetails]
    date_last_modified: str
    date_record_created: str


class BeamlineDetails(BaseModel):
    id: int
    slug: str
    name: str
    description: Optional[str] = None
    external_link: Optional[str] = None
    owners: List[UserBasic]
    watchers: List[UserBasic]
    # The noun to use to refer to sets of samples, e.g. "bar".
    set_noun: str
    parameters: List[Parameter]
    # No need for 'ScanTypeDetails' here, because each ScanType contains
    # its list of ParameterSettings, which can be resolved against
    # the full list of Parameters included above.
    scan_types: List[ScanType]

