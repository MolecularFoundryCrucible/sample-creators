import os
import logging
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

from flask import Blueprint

from beamline_data_toolkit.sample_tracker import SampleTrackerClient
from config import ALS_SAMPLE_TRACKER_URL, ALS_SAMPLE_TRACKER_USER

als_pw = os.environ.get('ALS_SAMPLE_TRACKER_PASSWORD', 'alsadmin')

als_sc_client = SampleTrackerClient(
    base_url=ALS_SAMPLE_TRACKER_URL,
    username=ALS_SAMPLE_TRACKER_USER,
    password=als_pw,
    timeout_seconds=100000,
    logger=logger,
)


als_shared_bp = Blueprint("als_shared", __name__)

