from dotenv import load_dotenv
from pycrucible import CrucibleClient
import os
from pycrucible.utils import get_tz_isoformat
from beamline_data_toolkit.sample_tracker import SampleTrackerClient

load_dotenv()
cruc_client = CrucibleClient(
    api_url="https://crucible.lbl.gov/testapi",
    api_key = os.environ.get("crucible_apikey")
)

# ================ ALS BEAMLINE SCICAT

als_sc_client = SampleTrackerClient(
    scicat_base_url="https://dataportal-staging.als.lbl.gov/api/v3/",
    scicat_username="admin",
    scicat_password=os.environ.get('als_scicat_password')
)

gwbars = cruc_client.list_samples(project_id = '10k_perovskites')

change_bars = [f'GWBAR{i:06d}' for i in range(3,13)]
gwbars = [x for x in gwbars if x['sample_name'] in change_bars]
gwbars = sorted(gwbars, key= lambda x: x['sample_name'])
als_set_ids = [x['description'].split("Set ID: ")[-1].strip("'") for x in gwbars]
als_sets = [als_sc_client.get_set_by_id(setid) for setid in als_set_ids]
