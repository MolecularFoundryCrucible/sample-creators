import json
import logging
import os
import re
import requests
from urllib.parse import quote_plus
from typing import Optional, TypeVar, Generic, Union, Type
from pydantic import BaseModel, TypeAdapter, Field
from dotenv import load_dotenv

from beamline_data_toolkit.sample_tracker.model import (
    GenericMessageResponse,
    Beamline,
    BeamlineCreateDto,
    BeamlineUpdateDto,
    Proposal,
    ProposalCreateDto,
    ProposalUpdateDto,
    Esaf,
    EsafCreateDto,
    EsafUpdateDto,
    Parameter,
    ParameterCreateDto,
    ParameterUpdateDto,
    ParameterSettings,
    ParameterSettingsCreateDto,
    ParameterSettingsUpdateDto,
    ScanType,
    ScanTypeCreateDto,
    ScanTypeUpdateDto,
    SampleSetDto,
    SampleSetCreateDto,
    SampleSetUpdateDto,
    SampleDto,
    SampleCreateDto,
    SampleUpdateDto,
    SampleSetParameterValuesByNameDto,
    SampleGetParameterValuesByNameDto,
    ParameterValueDto,
    ParameterSettingsDetails,
    ScanTypeDetails,
    BeamlineDetails
)

T = TypeVar("T")

logger = logging.getLogger("sample_tracker_client")
can_debug = logger.isEnabledFor(logging.DEBUG)


class PaginationModel(BaseModel, Generic[T]):
    next: Optional[int]
    previous: Optional[int]
    results: T

class SampletrackerLoginError(Exception):
    """Represents an error encountered logging into the Sample Tracker"""

    def __init__(self, message):
        self.message = message


class SampletrackerCommError(Exception):
    """Represents an error encountered during communication with the Sample Tracker."""

    def __init__(self, message):
        self.message = message


def build_parameters(
    filter_fields: Optional[dict] = None,
    page: Optional[int] = None,
    order_by: Optional[str] = None,
) -> dict:
    parameters = {}
    if filter_fields is not None:
        parameters.update(filter_fields)
    if page is not None:
        parameters["page"] = page
    if order_by is not None:
        parameters["ordering"] = "-"+order_by
    return parameters


class SampleTrackerClient:
    """Client for communicating with the Sample Tracker REST API server via http"""

    def __init__(
        self,
        base_url: str,
        token: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        auto_login=True,
        logger: logging.Logger = logger,
    ):
        """Initialize a new instance.

        Parameters
        ----------
        base_url : str
            Base url. e.g. `http://localhost:8000/`
        username : str
            username to login with
        password : str
            password to login with
        timeout_seconds : [int], optional
            timeout in seconds to wait for http connections to return, by default None
        """
        load_dotenv()
        if base_url is None:
            base_url = os.getenv(
                "SAMPLE_TRACKER_BASE_URL",
                "https://sample-tracker.dataportal.als.lbl.gov/",
            )

        if username is None:
            username = os.getenv(
                "SAMPLE_TRACKER_USERNAME", "user"
            )
        if password is None:
            password = os.getenv(
                "SAMPLE_TRACKER_PASSWORD", "password"
            )

        self._logger = logger
        self._base_url = base_url
        self._timeout_seconds = (
            timeout_seconds  # we are hitting a transmission timeout...
        )
        self._username = username
        self._password = password
        self._token = token
        self._headers = {}

        if self._token:
            self._headers["Authorization"] = "Token {}".format(self._token)
        else:
            assert (self._username is not None) and (
                self._password is not None
            ), "Sample Tracker login credentials (username, password) must be provided if token is not provided"
            if auto_login:
                self.login()


    def _log_in_via_users_login(self):
        login_url = "/".join([self._base_url.strip("/"), "api-token-auth/"])

        response = requests.post(
            login_url,
            json={"username": self._username, "password": self._password},
            headers=self._headers,
            stream=False,
            verify=True,
        )
        if not response.ok:
            try:
                response_text = response.json()
            except json.decoder.JSONDecodeError:
                response_text = response.text
            self._logger.error(f" Failed to log in to Sample Tracker via endpoint Users/login: {response_text}")
        return response


    def get_new_token(self):
        """logs in using the provided username / password combination
        and receives token for further communication"""
        # Users/login only works for functional accounts and auth/msad for regular users.
        self._logger.info(" Requesting new Sample Tracker API token")

        response = self._log_in_via_users_login()
        if response.ok:
            return response.json()["token"]  # not sure if semantically correct

        try:
            response_text = response.json()
        except json.decoder.JSONDecodeError:
            response_text = response.text
        self._logger.error(f" Failed log in:  {response_text}")
        raise SampletrackerLoginError(response.content)


    def login(self):
        """Attempts to authenticate using the stored username and password.
        Does not check if authentication has already occured."""
        self._token = self.get_new_token()
        self._headers["Authorization"] = "Token {}".format(self._token)


    def get_current_token(self):
        return self._token


    def _call_endpoint(
        self,
        cmd: str,
        endpoint: str,
        data: Optional[BaseModel] = None,
        parameters: dict = {},
        operation: str = "",
        paged: bool = False,
        model: Type[T] = dict,
    ) -> Optional[T]:
        response = None
        endpoint_url = "/".join([self._base_url.strip("/"), "api", endpoint.lstrip("/")])

        response = requests.request(
            method=cmd,
            url=endpoint_url,
            json=data.model_dump(exclude_none=True) if data is not None else None,
            params=parameters,
            headers=self._headers,
            timeout=self._timeout_seconds,
            stream=False,
            verify=True,
        )

        if not response.ok:
            if response.status_code == 404:
                self._logger.debug(
                    "Operation '%s' successful, returning None for 404 response",
                    operation,
                )
                return None
            raise SampletrackerCommError(
                "Error in operation %s: Response code not 'ok'. Response text: %s"
                % (operation, response.text)
            )
        if len(response.content) == 0:
            self._logger.debug(
                "Operation '%s' successful, returning None for empty response",
                operation,
            )
            return None
        if paged:
            adapter = TypeAdapter(PaginationModel[model])
            paged_result = adapter.validate_json(response.content.decode("utf-8"))
            self._logger.debug("Operation '%s' successful, returning paged result", operation)
            return paged_result.results
        adapter = TypeAdapter(model)
        result = adapter.validate_json(response.content.decode("utf-8"))
        if not isinstance(result, list):
            self._logger.debug(
                "Operation '%s' successful%s",
                operation,
                (
                    f", id={getattr(result, 'id', 'unknown')}"
                    if hasattr(result, "id")
                    else ""
                ),
            )
        else:
            self._logger.debug(
                "Operation '%s' successful, returning list of %d items",
                operation,
                len(result),
            )
        return result


    #
    # Beamlines
    #

    def beamline_get_one(self, slug: str) -> Optional[Beamline]:
        result: Optional[Beamline] = self._call_endpoint(
            cmd="get",
            endpoint=f"beamlines/{quote_plus(str(slug))}/",
            operation="beamline_get_one",
            model=Beamline,
        )
        return result


    def beamline_get_many(
        self,
        filter_fields: Optional[dict] = None,
        page: Optional[int] = None,
        order_by: Optional[str] = None,
    ) -> list[Beamline]:
        parameters = build_parameters(filter_fields, page, order_by)
        result: Optional[list[Beamline]] = self._call_endpoint(
            cmd="get",
            endpoint=f'beamlines/',
            operation="beamline_get_many",
            parameters=parameters,
            paged=True,
            model=list[Beamline],
        )
        if result is None:
            return []
        return result


    def beamline_get_details(self, slug: str) -> Optional[BeamlineDetails]:
        result: Optional[BeamlineDetails] = self._call_endpoint(
            cmd="get",
            endpoint=f"beamlines/{quote_plus(str(slug))}/details/",
            operation="beamline_get_details",
            model=BeamlineDetails,
        )
        return result


    def beamline_create(
        self, beamlineDto: BeamlineCreateDto
    ) -> Beamline:
        result: Optional[Beamline] = self._call_endpoint(
            cmd="post",
            endpoint=f"beamlines/",
            data=beamlineDto,
            operation="beamline_create",
            model=Beamline,
        )
        assert result is not None
        return result


    def beamline_update(
        self,
        beamline: Union[Beamline, BeamlineUpdateDto]
    ) -> Optional[Beamline]:
        result: Optional[Beamline] = self._call_endpoint(
            cmd="patch",
            endpoint=f"beamlines/{quote_plus(str(beamline.slug))}/",
            data=beamline,
            operation="beamline_update",
            model=Beamline,
        )
        return result


    #
    # Proposals
    #


    def proposal_get_one(self, slug: str) -> Optional[Proposal]:
        result: Optional[Proposal] = self._call_endpoint(
            cmd="get",
            endpoint=f"proposals/{quote_plus(str(slug))}/",
            operation="proposal_get_one",
            model=Proposal,
        )
        return result


    def proposal_get_many(
        self,
        filter_fields: Optional[dict] = None,
        page: Optional[int] = None,
        order_by: Optional[str] = None,
    ) -> list[Proposal]:
        parameters = build_parameters(filter_fields, page, order_by)
        result: Optional[list[Proposal]] = self._call_endpoint(
            cmd="get",
            endpoint=f'proposals/',
            operation="proposal_get_many",
            parameters=parameters,
            paged=True,
            model=list[Proposal],
        )
        if result is None:
            return []
        return result


    def proposal_get_by_name(self, name: str) -> list[Proposal]:
        return self.proposal_get_many(filter_fields={"name": name})


    def proposal_create(
        self, proposalDto: ProposalCreateDto
    ) -> Proposal:
        result: Optional[Proposal] = self._call_endpoint(
            cmd="post",
            endpoint=f"proposals/",
            data=proposalDto,
            operation="proposal_create",
            model=Proposal,
        )
        assert result is not None
        return result


    # ProposalUpdateDto is needed here because everything is optional when updating
    def proposal_update(
        self,
        proposal: Union[Proposal, ProposalUpdateDto]
    ) -> Optional[Proposal]:
        result: Optional[Proposal] = self._call_endpoint(
            cmd="patch",
            endpoint=f"proposals/{quote_plus(str(proposal.slug))}/",
            data=proposal,
            operation="proposal_update",
            model=Proposal,
        )
        return result


    def proposal_delete(self, slug: str) -> Optional[str]:
        result: Optional[str] = self._call_endpoint(
            cmd="delete",
            endpoint=f"proposals/{quote_plus(str(slug))}/",
            operation="proposal_delete",
            model=str,
        )
        return result


    #
    # ESAFs
    #

    def esaf_get_one(self, slug: str) -> Optional[Esaf]:
        result: Optional[Esaf] = self._call_endpoint(
            cmd="get",
            endpoint=f"esafs/{quote_plus(str(slug))}/",
            operation="esaf_get_one",
            model=Esaf,
        )
        return result


    def esaf_get_many(
        self,
        filter_fields: Optional[dict] = None,
        page: Optional[int] = None,
        order_by: Optional[str] = None,
    ) -> list[Esaf]:
        parameters = build_parameters(filter_fields, page, order_by)
        result: Optional[list[Esaf]] = self._call_endpoint(
            cmd="get",
            endpoint=f'esafs/',
            operation="esaf_get_many",
            parameters=parameters,
            paged=True,
            model=list[Esaf],
        )
        if result is None:
            return []
        return result


    def esaf_get_by_name(self, name: str) -> list[Esaf]:
        return self.esaf_get_many(filter_fields={"name": name})


    def esaf_get_parameter_values(self, slug: str) -> list[SampleGetParameterValuesByNameDto]:
        result: Optional[list[SampleGetParameterValuesByNameDto]] = self._call_endpoint(
            cmd="get",
            endpoint=f"esafs/{quote_plus(str(slug))}/parameter_values/",
            operation="esaf_get_parameter_values",
            model=list[SampleGetParameterValuesByNameDto],
        )
        if result is None:
            return []
        return result


    def esaf_create(
        self, dto: EsafCreateDto
    ) -> Esaf:
        result: Optional[Esaf] = self._call_endpoint(
            cmd="post",
            endpoint=f"esafs/",
            data=dto,
            operation="esaf_create",
            model=Esaf,
        )
        assert result is not None
        return result


    # EsafUpdateDto is needed here because everything is optional when updating
    def esaf_update(
        self,
        esaf: Union[Esaf, EsafUpdateDto]
    ) -> Optional[Esaf]:
        result: Optional[Esaf] = self._call_endpoint(
            cmd="patch",
            endpoint=f"esafs/{quote_plus(str(esaf.slug))}/",
            data=esaf,
            operation="esaf_update",
            model=Esaf,
        )
        return result


    def esaf_delete(self, slug: str) -> Optional[str]:
        result: Optional[str] = self._call_endpoint(
            cmd="delete",
            endpoint=f"esafs/{quote_plus(str(slug))}/",
            operation="esaf_delete",
            model=str,
        )
        return result


    #
    # Parameters
    #

    def parameter_get_one(self, id: int) -> Optional[Parameter]:
        result: Optional[Parameter] = self._call_endpoint(
            cmd="get",
            endpoint=f"parameters/{quote_plus(str(id))}/",
            operation="parameter_get_one",
            model=Parameter,
        )
        return result


    def parameter_create(
        self, dto: ParameterCreateDto
    ) -> Parameter:
        result: Optional[Parameter] = self._call_endpoint(
            cmd="post",
            endpoint=f"parameters/",
            data=dto,
            operation="parameter_create",
            model=Parameter,
        )
        assert result is not None
        return result


    def parameter_update(
        self,
        parameter: Union[Parameter, ParameterUpdateDto]
    ) -> Optional[Parameter]:
        result: Optional[Parameter] = self._call_endpoint(
            cmd="patch",
            endpoint=f"parameters/{quote_plus(str(parameter.id))}/",
            data=parameter,
            operation="parameter_update",
            model=Parameter,
        )
        return result


    def parameter_delete(self, id: int) -> Optional[str]:
        result: Optional[str] = self._call_endpoint(
            cmd="delete",
            endpoint=f"parameters/{quote_plus(str(id))}/",
            operation="parameter_delete",
            model=str,
        )
        return result


    #
    # Parameter Settings
    #

    def parameter_settings_get_one(self, id: str) -> Optional[ParameterSettings]:
        result: Optional[ParameterSettings] = self._call_endpoint(
            cmd="get",
            endpoint=f"parameter_settings/{quote_plus(str(id))}/",
            operation="parameter_settings_get_one",
            model=ParameterSettings,
        )
        return result


    def parameter_settings_create(
        self, dto: ParameterSettingsCreateDto
    ) -> ParameterSettings:
        result: Optional[ParameterSettings] = self._call_endpoint(
            cmd="post",
            endpoint=f"parameter_settings/",
            data=dto,
            operation="parameter_settings_create",
            model=ParameterSettings,
        )
        assert result is not None
        return result


    def parameter_settings_update(
        self,
        parameter_settings: Union[ParameterSettings, ParameterSettingsUpdateDto]
    ) -> Optional[ParameterSettings]:
        result: Optional[ParameterSettings] = self._call_endpoint(
            cmd="patch",
            endpoint=f"parameter_settings/{quote_plus(str(parameter_settings.id))}/",
            data=parameter_settings,
            operation="parameter_settings_update",
            model=ParameterSettings,
        )
        return result


    def parameter_settings_delete(self, id: str) -> Optional[str]:
        result: Optional[str] = self._call_endpoint(
            cmd="delete",
            endpoint=f"parameter_settings/{quote_plus(str(id))}/",
            operation="parameter_settings_delete",
            model=str,
        )
        return result


    #
    # Scan Types
    #

    def scan_type_get_one(self, slug: str) -> Optional[ScanType]:
        result: Optional[ScanType] = self._call_endpoint(
            cmd="get",
            endpoint=f"scantypes/{quote_plus(str(slug))}/",
            operation="scan_type_get_one",
            model=ScanType,
        )
        return result


    def scan_type_get_many(
        self,
        filter_fields: Optional[dict] = None,
        page: Optional[int] = None,
        order_by: Optional[str] = None,
    ) -> list[ScanType]:
        parameters = build_parameters(filter_fields, page, order_by)
        result: Optional[list[ScanType]] = self._call_endpoint(
            cmd="get",
            endpoint=f'scantypes/',
            operation="scan_type_get_many",
            parameters=parameters,
            paged=True,
            model=list[ScanType],
        )
        if result is None:
            return []
        return result


    def scan_type_get_many_details(
        self,
        filter_fields: Optional[dict] = None,
        order_by: Optional[str] = None,
    ) -> list[ScanTypeDetails]:
        parameters = build_parameters(filter_fields, None, order_by)
        result: Optional[list[ScanTypeDetails]] = self._call_endpoint(
            cmd="get",
            endpoint=f'scantypes/all_details/',
            operation="scan_type_get_many_details",
            parameters=parameters,
            paged=False,
            model=list[ScanTypeDetails],
        )
        if result is None:
            return []
        return result


    def scan_type_create(
        self, dto: ScanTypeCreateDto
    ) -> ScanType:
        result: Optional[ScanType] = self._call_endpoint(
            cmd="post",
            endpoint=f"scantypes/",
            data=dto,
            operation="scan_type_create",
            model=ScanType,
        )
        assert result is not None
        return result


    def scan_type_update(
        self,
        dto: Union[ScanType, ScanTypeUpdateDto]
    ) -> Optional[ScanType]:
        result: Optional[ScanType] = self._call_endpoint(
            cmd="patch",
            endpoint=f"scantypes/{quote_plus(str(dto.slug))}/",
            data=dto,
            operation="scan_type_update",
            model=ScanType,
        )
        return result


    def scan_type_delete(self, slug: str) -> Optional[str]:
        result: Optional[str] = self._call_endpoint(
            cmd="delete",
            endpoint=f"scantypes/{quote_plus(str(slug))}/",
            operation="scan_type_delete",
            model=str,
        )
        return result


    #
    # Sample Sets
    #

    def set_get_one(self, slug: str) -> Optional[SampleSetDto]:
        result: Optional[SampleSetDto] = self._call_endpoint(
            cmd="get",
            endpoint=f"sets/{quote_plus(str(slug))}/",
            operation="set_get_one",
            model=SampleSetDto,
        )
        return result


    def set_get_many(
        self,
        filter_fields: Optional[dict] = None,
        page: Optional[int] = None,
        order_by: Optional[str] = None,
    ) -> list[SampleSetDto]:
        parameters = build_parameters(filter_fields, page, order_by)
        result: Optional[list[SampleSetDto]] = self._call_endpoint(
            cmd="get",
            endpoint=f'sets/',
            operation="set_get_many",
            parameters=parameters,
            paged=True,
            model=list[SampleSetDto],
        )
        if result is None:
            return []
        return result


    def set_get_parameter_values(self, slug: str) -> list[SampleGetParameterValuesByNameDto]:
        result: Optional[list[SampleGetParameterValuesByNameDto]] = self._call_endpoint(
            cmd="get",
            endpoint=f"sets/{quote_plus(str(slug))}/parameter_values/",
            operation="set_get_parameter_values",
            model=list[SampleGetParameterValuesByNameDto],
        )
        if result is None:
            return []
        return result


    def set_get_by_esaf(self, slug: str) -> list[SampleSetDto]:
        return self.set_get_many(filter_fields={"esaf__slug": slug})


    def set_get_by_proposal(self, slug: str) -> list[SampleSetDto]:
        return self.set_get_many(filter_fields={"esaf__proposal__slug": slug})


    def set_get_by_beamline(self, slug: str) -> list[SampleSetDto]:
        return self.set_get_many(filter_fields={"esaf__beamline__slug": slug})


    def set_get_by_name(self, name: str) -> list[SampleSetDto]:
        return self.set_get_many(filter_fields={"name": name})


    def set_get_by_qr_code(self, qr_code: str) -> Optional[SampleSetDto]:
        #
        # Extracting the slug from the QR code
        #

        # QR codes coming from sample bars are formatted like this:
        # `${SAMPLE_TRACKER_URL}/SET/${SET_ID}`.toUpperCase();
        #     or
        # `${SAMPLE_TRACKER_URL}/SETS/${SET_ID}`.toUpperCase();
        # For example:
        # test_qr_code = "HTTPS://SAMPLE-TRACKER.DATAPORTAL.ALS.LBL.GOV/SETS/F049794D-4C79-4351-BCCD-734B66D522B4"

        # Extract the setId from the QR code
        qr_code = qr_code.lower()
        set_slug_match = re.search("/sets?/([0-9a-z/-]+)('|\"|$)", qr_code)
        if set_slug_match is None:
            self._logger.error(f"Couldn't find sample ID in QR code string: {qr_code}")
            return None
        set_slug: str = set_slug_match.group(1)

        return self.set_get_one(set_slug)


    def set_create(
        self, dto: SampleSetCreateDto
    ) -> SampleSetDto:
        result: Optional[SampleSetDto] = self._call_endpoint(
            cmd="post",
            endpoint=f"sets/",
            data=dto,
            operation="set_create",
            model=SampleSetDto,
        )
        assert result is not None
        return result


    def set_update(
        self,
        dto: Union[SampleSetDto, SampleSetUpdateDto]
    ) -> Optional[SampleSetDto]:
        result: Optional[SampleSetDto] = self._call_endpoint(
            cmd="patch",
            endpoint=f"sets/{quote_plus(str(dto.slug))}/",
            data=dto,
            operation="set_update",
            model=SampleSetDto,
        )
        return result


    def set_delete(self, slug: str) -> Optional[str]:
        result: Optional[str] = self._call_endpoint(
            cmd="delete",
            endpoint=f"sets/{quote_plus(str(slug))}/",
            operation="set_delete",
            model=str,
        )
        return result


    create_set = set_create
    get_set_by_id = set_get_one
    get_bar_by_id = set_get_one
    get_sets_by_proposal_id = set_get_by_proposal
    get_sets_by_name = set_get_by_name
    get_bar_by_qr_code = set_get_by_qr_code
    get_set_by_qrcode = set_get_by_qr_code
    

    #
    # Samples
    #

    def sample_get_one(self, slug: str) -> Optional[SampleDto]:
        result: Optional[SampleDto] = self._call_endpoint(
            cmd="get",
            endpoint=f"samples/{quote_plus(str(slug))}/",
            operation="sample_get_by_slug",
            model=SampleDto,
        )
        return result


    def sample_get_many(
        self,
        filter_fields: Optional[dict] = None,
        page: Optional[int] = None,
        order_by: Optional[str] = None,
    ) -> list[SampleDto]:
        parameters = build_parameters(filter_fields, page, order_by)
        result: Optional[list[SampleDto]] = self._call_endpoint(
            cmd="get",
            endpoint=f'samples/',
            operation="sample_get_many",
            parameters=parameters,
            paged=True,
            model=list[SampleDto],
        )
        if result is None:
            return []
        return result


    def sample_get_parameter_values(self, slug: str) -> Optional[SampleGetParameterValuesByNameDto]:
        result: Optional[SampleGetParameterValuesByNameDto] = self._call_endpoint(
            cmd="get",
            endpoint=f"samples/{quote_plus(str(slug))}/parameter_values/",
            operation="sample_get_parameter_values",
            model=SampleGetParameterValuesByNameDto,
        )
        return result


    def sample_get_by_set(self, set_slug: str) -> list[SampleDto]:
        return self.sample_get_many(filter_fields={"set__slug": set_slug})


    # Names are intended to be unique within sets, but this is not strictly enforced
    # So we could return more than one sample in this list.
    def sample_get_by_set_and_name(self, set_slug: str, name: str) -> list[SampleDto]:
        return self.sample_get_many(filter_fields={"set__slug": set_slug, "name": name})


    def sample_set_parameter_values_by_name(self, sample_slug: str, dto: SampleSetParameterValuesByNameDto) -> Optional[GenericMessageResponse]:
        result: Optional[GenericMessageResponse] = self._call_endpoint(
            cmd="post",
            endpoint=f"samples/{quote_plus(str(sample_slug))}/set_values_by_name/",
            data=dto,
            operation="sample_set_parameter_values_by_name",
            model=GenericMessageResponse,
        )
        return result


    def sample_create(
        self, dto: SampleCreateDto
    ) -> SampleDto:
        result: Optional[SampleDto] = self._call_endpoint(
            cmd="post",
            endpoint=f"samples/",
            data=dto,
            operation="sample_create",
            model=SampleDto,
        )
        assert result is not None
        return result


    def sample_update(
        self,
        dto: Union[SampleDto, SampleUpdateDto]
    ) -> Optional[SampleDto]:
        result: Optional[SampleDto] = self._call_endpoint(
            cmd="patch",
            endpoint=f"samples/{quote_plus(str(dto.slug))}/",
            data=dto,
            operation="sample_update",
            model=SampleDto,
        )
        return result


    def sample_delete(self, slug: str) -> Optional[str]:
        result: Optional[str] = self._call_endpoint(
            cmd="delete",
            endpoint=f"samples/{quote_plus(str(slug))}/",
            operation="sample_delete",
            model=str,
        )
        return result


    create_sample = sample_create
    update_sample = sample_update


def from_token(base_url: str, token: str):
    return SampleTrackerClient(base_url, token)


def from_credentials(base_url: str, username: str, password: str):
    return SampleTrackerClient(base_url, username, password)



