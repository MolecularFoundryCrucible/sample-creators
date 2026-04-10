ALS_SCICAT_URL = "https://dataportal-staging.als.lbl.gov/api/v3/"
ALS_SCICAT_USER = "admin"
ALS_SAMPLE_TRACKER_URL = "HTTPS://DATAPORTAL-STAGING.ALS.LBL.GOV/SAMPLE-TRACKING"

GIWAXS_CONFIG = {
    "sample_prefix": "GWBAR",
    "name_format": "GWBAR{:06d}",
    "sample_type": "giwaxs bar",
    "group_id": "733",
    "proposal_id": "DD-00839",
    "scan_type": "GIWAXS",
    "num_positions": 14,
    "default_offset_mm": 20.0,
    "default_wafer_width_mm": 15.0,
    "default_incidence_angle": "1.0",
    "default_sample_parameters": {
        "measurement_spots": "1",
        "exposure_time": "auto",
        "exposure_max": "5",
        "image_type": "single",
    },
}

RGA_CONFIG = {
    "sample_prefix": "RGA",
    "name_format": "RGA{:06d}",
    "sample_type": "rga carrier",
    "group_id": "1201",
    "proposal_id": "PRT-00417",
    "scan_type": "RGA",
    "num_positions": 36,
    "default_shutter_open_s": 150,
    "default_mass_range_amu": 300,
}

RGA_POSITIONS = [f"{row}{col}" for row in "ABCDEF" for col in range(1, 7)]

COORDS_FILE = "coords_36sample.txt"
