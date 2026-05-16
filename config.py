ALS_SAMPLE_TRACKER_URL = "https://sample-tracker.dataportal.als.lbl.gov"
ALS_SAMPLE_TRACKER_USER = "alsadmin"

GIWAXS_CONFIG = {
    "sample_prefix": "GWBAR",
    "name_format": "GWBAR{:06d}",
    "sample_type": "giwaxs bar",
    "beamline": "7-3-3",
    "proposal": "DD-00839",
    "default_esaf": "DD-00839-003",
    "scan_type": "GIWAXS",
    "scan_type_slug": "7-3-3-giwaxs_for_10k",  # was "7-3-3-giwaxs"
    "num_positions": 11,
    "default_offset_mm": 32.5,
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
    "scan_type_slug": "12-0-1-2-rga",
    "num_positions": 36,
    "default_shutter_open_s": 150,
    "default_mass_range_amu": 300,
}

RGA_POSITIONS = [f"{row}{col}" for row in "ABCDEF" for col in range(1, 7)]

COORDS_FILE = "coords_36sample.txt"

B30_SPUTTER_CONFIG = {
    "dataset_name_prefix": "Sputtering Parameters for",
    "dataset_type": "Sputtering Parameters",
    "instrument_name": "b30 - aja sputter tool",
    "measurement": "Sputtering",
    # Fields shown on the upload form. To add/remove fields, edit this list.
    # Each entry: {"key": used in Crucible metadata, "label": shown to user, "type": html input type}
    "dataset_fields": [
        {"key": "gas1",       "label": "Gas 1",          "type": "select",  "options": ["Ar", "N2", "O2", "Other"]},
        {"key": "gas1_pc",       "label": "Gas 1 (%)",          "type": "number", "default": 100},
        {"key": "gas2",       "label": "Gas 2",          "type": "select",  "options": ["", "Ar", "N2", "O2", "Other"]},
        {"key": "gas2_pc",       "label": "Gas 2 (%)",          "type": "number", "default": ""},
        {"key": "pressure_mtorr", "label": "Deposition pressure (mTorr)", "type": "number", "default": 3},
        {"key": "target_material",           "label": "Target material",                "type": "select",  "options": ["", "Ag", "Al", "Al2O3", "Au", "Bi2O3", "BVO", "C", "Co", "Co3O4", "Cu", "CuAlO2", "Fe", "Ga2O3", "Gd", "Ge", "In", "Ir", "ITO", "Mn", "Nb", "Ni", "Ni75Mo25", "Ni85Mo15", "Pd", "Pt", "Ru", "Sb", "SiO2", "Sn", "SnO2", "SrTiO3", "Ta", "Ta2O5", "Ti", "V", "W", "Zn", "Zr", "Other"]},
        {"key": "power_source",           "label": "Power source",                "type": "select",  "options": ["RF 1-1", "RF 1-2", "RF 1-3", "RF 2-1", "RF 2-2", "RF 2-3", "DC 1", "DC 2", "DC 3", "DC 4", "Pulsed DC", "Other"]},
        {"key": "power_w",        "label": "Power (W)",             "type": "number", "default": 150},
        {"key": "substrate_temperature_C",        "label": "Substrate temperature (C)",             "type": "number", "default": 25},
        {"key": "DC_voltage_V",          "label": "DC voltage (V)",               "type": "number"},
        {"key": "deposition_time_s",        "label": "Deposition time (s)",             "type": "number"},
        {"key": "rate_A_s", "label": "Deposition rate (Å/s)",      "type": "number"},
        {"key": "layer_thickness_nm", "label": "Layer Thickness (nm)",      "type": "number"},
        {"key": "comment",          "label": "Comment",               "type": "text"},
    ],
}
