import os
import logging
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

from beamline_data_toolkit.sample_tracker import SampleTrackerClient
from config import ALS_SAMPLE_TRACKER_URL, ALS_SAMPLE_TRACKER_USER

als_pw = os.environ.get('ALS_SAMPLE_TRACKER_PASSWORD', 'alsadmin')


class _LazySampleTrackerClient:
    """Builds the real client, and logs in, on first use.

    SampleTrackerClient logs in from its constructor. Building it at import time meant a
    Sample Tracker outage stopped the whole app from starting — including the B30 pages,
    which never talk to Sample Tracker. Deferring it turns that into an error on the
    GIWAXS/RGA requests that actually need the beamline, which those routes already
    report back to the user.
    """

    def __init__(self):
        self._client = None

    def __getattr__(self, name):
        if self._client is None:
            self._client = SampleTrackerClient(
                base_url=ALS_SAMPLE_TRACKER_URL,
                username=ALS_SAMPLE_TRACKER_USER,
                password=als_pw,
                timeout_seconds=100000,
                logger=logger,
            )
        return getattr(self._client, name)


als_sc_client = _LazySampleTrackerClient()
