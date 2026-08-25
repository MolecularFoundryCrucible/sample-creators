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

# BARCODE PRINTING
# "printers" is the allowlist: a print request naming anything else is rejected.
# The list is never sent to the browser — users type the name of the printer they are at.
PRINT_CONFIG = {
    "printer_topic_prefix": "crucible-printer",
    "printers": ["ucd1", "b30-113", "b67-1202", "print1"],
    # A batch is published synchronously, so max_batch * print_delay_s is the worst-case
    # request duration. Keep the product well under any proxy timeout.
    "max_batch": 100,
    "print_delay_s": 0.1,
}

# B30 SPUTTER CONFIG (AJA + Lesker)
TARGET_MATERIAL_OPTIONS = [
    "", "Ag", "Al", "Al2O3", "Au", "Bi2O3", "BVO", "C", "Co", "Co3O4", "Cu",
    "CuAlO2", "Fe", "Ga2O3", "Gd", "Ge", "In", "Ir", "ITO", "Mn", "Nb", "Ni",
    "Ni75Mo25", "Ni85Mo15", "Pd", "Pt", "Ru", "Sb", "SiO2", "Sn", "SnO2",
    "SrTiO3", "Ta", "Ta2O5", "Ti", "V", "W", "Zn", "Zr", "Other"
]

POWER_SOURCE_OPTIONS = [
    "RF 1-1", "RF 1-2", "RF 1-3", "RF 2-1", "RF 2-2", "RF 2-3",
    "DC 1", "DC 2", "DC 3", "DC 4", "Pulsed DC", "Other"
]

# Fields shown on the upload form. To add/remove fields, edit this list.
# Each entry: {"key": used in Crucible metadata, "label": shown to user, "type": html input type}
SPUTTER_DATASET_FIELDS = [
        {"key": "01_co_deposition_enabled", "label": "Enable Co-Deposition", "type": "checkbox"},
        {"key": "02_second_gas_enabled", "label": "Enable Second Gas", "type": "checkbox"},
        {"key": "03_gas1",       "label": "Gas 1",          "type": "select",  "options": ["Ar", "N2", "O2", "Other"]},
        {"key": "04_gas1_pc",       "label": "Gas 1 (%)",          "type": "number", "default": 100},
        {"key": "05_gas2",       "label": "Gas 2",          "type": "select",  "options": ["", "Ar", "N2", "O2", "Other"]},
        {"key": "06_gas2_pc",       "label": "Gas 2 (%)",          "type": "number", "default": ""},
        {"key": "07_pressure_mTorr", "label": "Deposition pressure (mTorr)", "type": "number", "default": 3},
        {"key": "08_substrates_temperature_C",        "label": "Substrate temperature (C)",             "type": "number", "default": 25},
        {"key": "09_target_material",           "label": "Target material",                "type": "select",  "options": TARGET_MATERIAL_OPTIONS},
        {"key": "10_power_source",           "label": "Power source",                "type": "select",  "options": POWER_SOURCE_OPTIONS},
        {"key": "11_power_W",        "label": "Power (W)",             "type": "number", "default": 150},
        {"key": "12_DC_voltage_V",          "label": "DC voltage (V)",               "type": "number"},
        {"key": "13_target_material_2", "label": "Target material 2", "type": "select", "options": TARGET_MATERIAL_OPTIONS},
        {"key": "14_power_source_2", "label": "Power source 2", "type": "select", "options": POWER_SOURCE_OPTIONS},
        {"key": "15_power_W_2", "label": "Power 2 (W)", "type": "number"},
        {"key": "16_DC_voltage_V_2", "label": "DC voltage 2 (V)", "type": "number"},
        {"key": "17_rate_A_s_1", "label": "Dep. rate Material 1 (Å/s)", "type": "number"},
        {"key": "18_rate_A_s_2", "label": "Dep. rate Material 2 (Å/s)", "type": "number"},
        {"key": "19_rate_A_s", "label": "Deposition rate (Å/s)",      "type": "number"},
        {"key": "20_layer_thickness_nm", "label": "Layer Thickness (nm)",      "type": "number"},
        {"key": "21_deposition_time_s",        "label": "Deposition time (s)",             "type": "number"},
        {"key": "22_comment",          "label": "Comment",               "type": "text"},
]

# One entry per sputter tool. Each tool gets its own page, session, rate-index cache and
# Crucible instrument, but they all run the same code in routes/b30_sputter.py.
#
# The tools share SPUTTER_DATASET_FIELDS today. When one tool's form needs to diverge,
# give that tool its own list here — nothing outside this file has to change.
# Adding a third tool: add an entry here and one register_blueprint line in app.py.
SPUTTER_TOOLS = {
    "aja": {
        "url_prefix": "/b30-aja-sputter",
        "nav_label": "B30 AJA Sputter",
        "page_title": "B30 - AJA Sputter Tool Data Entry and Logbook",
        "card_description": "Look up or create samples by barcode and upload AJA sputtering deposition parameters to Crucible.",
        "instrument_name": "b30 - aja sputter tool",
        "calibration_sample_id": "0tgfny1b35rwd000x35nr7a9d8",
        "printer_name": "crucible-printer/b30-113",
        "dataset_type": "Sputtering Parameters",
        "measurement": "Sputtering",
        "dataset_fields": SPUTTER_DATASET_FIELDS,
    },
    "kjlesker": {
        "url_prefix": "/b30-kjlesker-sputter",
        "nav_label": "B30 KJLesker Sputter",
        "page_title": "B30 - KJLesker Sputter Tool Data Entry and Logbook",
        "card_description": "Look up or create samples by barcode and upload KJLesker sputtering deposition parameters to Crucible.",
        "instrument_name": "b30 - kjlesker sputter tool",
        "calibration_sample_id": "",  # TODO: Crucible ID of the KJLesker calibration sample
        "printer_name": "crucible-printer/b30-113",
        "dataset_type": "Sputtering Parameters",
        "measurement": "Sputtering",
        "dataset_fields": SPUTTER_DATASET_FIELDS,
    },
}

# B30 EBEAM CONFIG
EBEAM_TARGET_MATERIAL_OPTIONS = [
    "", "Ag", "Al", "Au", "Cr", "Cu", "Ge", "Ni", "Pd", "Pt", "Sn", "Ti", "TiO2"
]

# Unlike the sputter app there is a single e-beam tool, so this config names one instrument
# directly instead of carrying a "tools" dict. There is no calibration sample either, so no
# deposition-rate autofill — the rate is typed in from the crystal monitor.
B30_EBEAM_CONFIG = {
    "dataset_type": "E-beam Evaporation Parameters",
    "measurement": "E-beam Evaporation",
    "instrument_name": "b30 - ebeam evaporator",
    "printer_name": "crucible-printer/b30-113",
    # Fields shown on the upload form. To add/remove fields, edit this list.
    # Each entry: {"key": used in Crucible metadata, "label": shown to user, "type": html input type}
    "dataset_fields": [
        {"key": "01_target_material",           "label": "Target material",            "type": "select", "options": EBEAM_TARGET_MATERIAL_OPTIONS},
        {"key": "02_power_W",                   "label": "Power (W)",                  "type": "number"},
        {"key": "03_rate_A_s",                  "label": "Deposition rate (Å/s)",      "type": "number"},
        {"key": "04_base_pressure_mTorr",       "label": "Base pressure (mTorr)",      "type": "number"},
        {"key": "05_deposition_pressure_mTorr", "label": "Deposition pressure (mTorr)", "type": "number"},
        {"key": "06_comment",                   "label": "Comment",                    "type": "text"},
    ],
}

# B30 SEM CONFIG
B30_SEM_CONFIG = {
    "dataset_name_prefix": "SEM Images for",
    "dataset_type": "SEM Images",
    "instrument_name": "b30 - FEI SEM",
    "measurement": "Scanning electron microscope",
    "printer_name": "crucible-printer/b30-122",
    # Fields shown on the upload form. To add/remove fields, edit this list.
    # Each entry: {"key": used in Crucible metadata, "label": shown to user, "type": html input type}
    "dataset_fields": [
        #SEM parameters -> are they saved in the file(s)?
        {"key": "images_saved",       "label": "Images Saved?",          "type": "checkbox"},
        {"key": "vacuum_level",       "label": "Vacuum Level",          "type": "select",  "options": ["High", "Low", "ESEM"]},
        {"key": "spot_size", "label": "Spot Size", "type": "number"},
        {"key": "high_voltage_V", "label": "High Voltage (V)", "type": "number"},
        {"key": "emission_current_A", "label": "Emission Current (A)", "type": "number"},
        {"key": "chamber_pressure_Torr", "label": "Chamber Pressure (Torr)", "type": "number"},
        {"key": "edx_used",       "label": "Edx Used?",          "type": "checkbox"},
        #EDX parameters -> are they saved in the file(s)?
        {"key": "primary_energy_keV", "label": "Primary Energy (keV)", "type": "number"},
        {"key": "comment",          "label": "Comment",               "type": "text"},
    ],
}