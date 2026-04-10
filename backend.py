
import os
from dotenv import load_dotenv
load_dotenv()

# crucible
from crucible import CrucibleClient
cruc_client = CrucibleClient()

# als-scicat
from beamline_data_toolkit.sample_tracker import SampleTrackerClient
als_sc_client = SampleTrackerClient(
    scicat_base_url="https://dataportal-staging.als.lbl.gov/api/v3/",
    scicat_username="admin",
    scicat_password=os.environ.get('als_scicat_password')
)

# determine the next sample
def get_next_serial_sample(sample_prefix, project):
    project_samples = cruc_client.list_samples(project_id = project)
    filtered_samples = [x['sample_name'] for x in project_samples if x['sample_name'].startswith(sample_prefix)]
    sample_nums = [int(x.replace(sample_prefix, '')) for x in filtered_samples]
    sample_nums.sort()
    print(sample_nums)
    if len(sample_nums) == 0:
        return 1
    return sample_nums[-1] + 1


def recalc_positions(self):
    for i in range(1,15):
        new_mm = ((i-1)*self.settings['wafer_width'])+self.settings['offset_from_left_mm']
        self.update_lq(new_mm, f'pos{i}_distance_mm')


def apply_incidence_angle(self):
    for i in range(1,15):
        self.update_lq(self.settings['incidence_angle_all'], f'pos{i}_incidence_angle')



#==== callbacks
def on_enter_email(self):
    provided_email = self.settings.email.value.strip()
    user_info = cruc_client.get_user(email = provided_email)

    if user_info is None:
        return
    # update user info
    user_name = f'{user_info['first_name']}_{user_info['last_name']}'
    self.update_lq(user_name, 'user_name')
    self.update_lq(user_info['orcid'], 'orcid')

    # update project list
    projects = cruc_client.list_projects(user_info['orcid'])
    project_ids = [x['project_id'] for x in projects]
    project_ids.sort()
    self.update_lq_list(project_ids, project_ids[0], 'project')

def on_enter_bar_name(self):
    mfid = ''
    alsid = ''
    mf_bars = cruc_client.list_samples(sample_name=self.settings['bar_name'])
    print(mf_bars)
    if len(mf_bars) == 1:
        mfid = mf_bars[0]['unique_id']
        descrip =  mf_bars[0]['description']
        if descrip is not None:
            alsid = mf_bars[0]['description'].split('|| Set ID:')[-1].strip()      

    self.update_lq(mfid, 'bar_mf_uuid')
    self.update_lq(alsid, 'bar_als_uuid')