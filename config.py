ALS_SAMPLE_TRACKER_URL = "https://sample-tracker.dataportal.als.lbl.gov"
ALS_SAMPLE_TRACKER_USER = "alsadmin"

GIWAXS_CONFIG = {
    "sample_prefix": "GWBAR",
    "name_format": "GWBAR{:06d}",
    "sample_type": "giwaxs bar",
    "beamline": "7-3-3",
    "proposal": "DD-00839",
    "default_esaf": "DD-00839-001",
    "scan_type": "GIWAXS",
    "scan_type_slug": "7-3-3-giwaxs",
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
    "beamline": "12-0-1-2",
    "proposal": "PRT-00417",
    "default_esaf": "PRT-00417-001",
    "scan_type": "RGA",
    "scan_type_slug": "12-0-1-2-12-0-1-2-rga",
    "num_positions": 36,
    "default_shutter_open_s": 150,
    "default_mass_range_amu": 300,
}

RGA_POSITIONS = [f"{row}{col}" for row in "ABCDEF" for col in range(1, 7)]

COORDS_FILE = "coords_36sample.txt"
