# Copied from MolecularFoundry/manual-synthesis-ui backend/fab_templates.py at c25ae5c.
# Process flow templates for the fabrication traveler.
# Transcribed from the QCMF wafer traveler sheet (WFR_04). Each step is a list
# of sub-step rows; each row has only its own fields, each with its own unit.
# Every field is editable per run; numeric fields are stored as numbers.


def num(key, label, unit=None, default=None):
    return {"key": key, "label": label, "unit": unit, "type": "number", "default": default}


def text(key, label, default=None):
    return {"key": key, "label": label, "unit": None, "type": "text", "default": default}


def row(key, process, *fields):
    """Every sub-step can take a comment; rows from the sheet that had one keep its text as the default."""
    fields = list(fields)
    if not any(f["key"] == "comment" for f in fields):
        fields.append(text("comment", "Comment"))
    return {"key": key, "process": process, "fields": fields}


# Field shorthands
def temp(v=None): return num("temp_c", "Temp", "°C", v)
def minutes(v=None): return num("time_min", "Time", "min", v)
def seconds(v=None): return num("time_s", "Time", "s", v)
def tool(v=None): return text("tool", "Tool", v)
def chem(v=None): return text("chemistry", "Chemistry", v)
def comment(v=None): return text("comment", "Comment", v)
def specs(v=None): return text("specs", "Tool specs", v)
def recipe(v=None): return text("recipe", "Recipe name", v)
def resist(v=None): return text("resist", "Resist", v)
def program(v=None): return num("program", "Program", None, v)
def program_name(v=None): return text("program", "Program", v)
def rpm(v=None): return num("spin_rpm", "Spin speed", "rpm", v)
def freq(v=None): return num("freq_khz", "Frequency", "kHz", v)
def power_pct(v=None): return num("power_pct", "Power", "%", v)
def thickness_nm(v=None): return num("thickness_nm", "Thickness", "nm", v)
def rate(v=None): return num("rate_a_s", "Rate", "A/s", v)
def accuracy(v=None): return num("accuracy_pct", "Accuracy", "%", v)
def pressure_torr(v=None): return num("pressure_torr", "Pressure", "Torr", v)


def sonicate(key, process, t, minutes_, f, p, tool_="Sonicator", note=None):
    fields = [temp(t), minutes(minutes_), tool(tool_), freq(f), power_pct(p)]
    if note:
        fields.append(comment(note))
    return row(key, process, *fields)


def blank(key, process):
    return row(key, process)


def chamber_clean_rows(minutes_=30):
    return [
        blank("load_cleaning_wafer", "Load cleaning wafer"),
        row("chamber_clean", "Chamber clean", minutes(minutes_), recipe("CHAMBER CLEAN WITH WAFER")),
        blank("microscope", "Microscope inspection"),
    ]


def descum_rows(tool_name):
    return [
        row("o2_descum", "O2 descum", recipe("YB_O2_Descum"), tool(tool_name),
            num("forward_power_w", "Forward power", "W", 30),
            num("icp_power_w", "ICP power", "W", 0),
            num("pressure_mtorr", "Pressure", "mTorr", 80),
            num("o2_flow_sccm", "O2 flow", "sccm", 100),
            num("strike_time_s", "Strike time", "s", 5),
            num("etch_time_s", "Etch time", "s", 20)),
        blank("unload_wafer", "Unload wafer"),
        *chamber_clean_rows(),
    ]


def step(id_, label, name, rows, tool_=None, optional=False, condition=None, action=None, allow_files=True):
    return {"id": id_, "label": label, "name": name, "optional": optional, "condition": condition,
            "tool": tool_, "action": action, "allow_files": allow_files, "rows": rows}


QCMF_QUBIT_V1_STEPS = [
    step("rca_clean", "Step 1A", "Substrate cleaning (RCA)", tool_="Hotplate", condition={"wafer_type": "qubit"}, rows=[
        row("rca_1_clean", "RCA 1 clean", chem("NH4OH:H2O2:H2O 1:1:5"), temp(90), minutes(20), tool("Hotplate"),
            comment("20ml:20ml:100ml for 4 inch wafers. Pour NH4OH and DIW, bring to 90C, then add H2O2")),
        row("diw_beaker_1", "DIW beaker 1", temp(20), minutes(1)),
        row("diw_beaker_2", "DIW beaker 2", temp(20), minutes(1)),
        row("diw_rinse", "DIW rinse", temp(20), seconds(20)),
        blank("n2_blow_dry", "N2 blow dry"),
    ]),
    step("solvent_clean", "Step 1B", "Substrate cleaning (solvents)", tool_="Sonicator", condition={"wafer_type": "test"}, rows=[
        sonicate("acetone_1", "Acetone 1", 50, 5, 37, 100),
        sonicate("acetone_2", "Acetone 2", 50, 5, 80, 100),
        sonicate("ipa", "IPA", 50, 5, 80, 100),
        blank("ipa_rinse_n2_dry", "IPA rinse and N2 dry"),
    ]),
    step("native_oxide_removal", "Step 2", "Native oxide removal", tool_="HF Bench", rows=[
        row("boe_dip", "BOE dip", chem("10:1 mixture"), temp(20), minutes(1), tool("HF Bench")),
        row("diw_beaker_1", "DIW beaker 1", temp(20), minutes(1), tool("HF Bench")),
        row("diw_beaker_2", "DIW beaker 2", temp(20), minutes(1), tool("HF Bench")),
        row("ipa", "IPA", temp(20), seconds(30), tool("Solvent bench"),
            comment("Sample transferred to solvent bench for IPA and next steps")),
        row("n2_blow_dry", "N2 blow dry", tool("Solvent bench")),
        blank("transfer_glove_box", "Transfer to glove box"),
    ]),
    step("ebeam_evaporation", "Step 3A", "E-beam evaporation", tool_="E-beam evaporator", optional=True, rows=[
        blank("load_wafer", "Load wafer into loadlock"),
        row("chamber", "Recipe and chambers", recipe(),
            num("ox_chamber_pressure_torr", "Ox chamber pressure", "Torr"),
            num("evap_chamber_pressure_torr", "Evap chamber pressure", "Torr")),
        row("precondition", "Precondition", power_pct(7)),
        row("autotune", "Autotune", num("stability_factor", "Stability factor", None, 2)),
        row("stabilize", "Stabilize", rate(2), accuracy(5)),
        row("deposit", "Deposit", num("thickness_a", "Thickness", "A", 1000)),
        blank("postcondition", "Postcondition"),
    ]),
    step("sputtering", "Step 3B", "Sputtering", tool_="Sputter", optional=True, rows=[
        blank("load_wafer", "Load wafer"),
        row("deposition", "Deposition", recipe(), text("target", "Target"),
            text("power_supply", "Power supply / target position"),
            num("chamber_pressure", "Sputter chamber pressure"),
            num("deposition_temp_c", "Deposition temp", "°C"),
            num("ar_flow_sccm", "Ar flow", "sccm"),
            num("pressure_mtorr", "Pressure", "mTorr"),
            num("target_output_pct", "Target output", "%"),
            num("target_dc_bias_v", "Target DC bias", "V"),
            text("n2_flow_sccm", "N2 flow rate (min-max), sccm"),
            num("calibrated_rate_a_s", "Calibrated rate", "A/s"),
            num("tooling_factor", "Tooling factor"),
            thickness_nm(),
            num("target_substrate_distance", "Target-substrate distance")),
        blank("unload_wafer", "Unload wafer"),
    ]),
    step("resist_spin", "Step 4", "Resist spinning", tool_="CEE hotplate", rows=[
        row("bake_1", "Bake", temp(100), minutes(3), tool("CEE hotplate"), program_name("100C_180s")),
        row("n2_blow_dry", "N2 blow dry", comment("After placing in spinner")),
        row("spincoat", "Spincoat", resist("S1805"), rpm(6000), seconds(45), program(9)),
        row("bake_2", "Bake", temp(100), minutes(3), tool("CEE hotplate"), program_name("100C_180s")),
        blank("clean_spinner", "Clean up spinner"),
    ]),
    step("exposure", "Step 5", "Exposure", tool_="MLA", rows=[
        blank("calibrate_dose", "Calibrate dose"),
        row("expose", "Expose", tool("MLA"), num("dose_mj_cm2", "Dose", "mJ/cm2", 50),
            num("defocus", "Defocus", None, 4), comment("This can vary based on the dose test")),
    ]),
    step("development", "Step 6", "Development", tool_="Acid bench", rows=[
        row("mf26a", "MF 26A", temp(20), seconds(30), tool("Acid bench"), comment("Strong agitation during development")),
        row("diw", "DIW", temp(20), seconds(30)),
        blank("diw_rinse_n2_dry", "DIW rinse + N2 blow dry"),
        blank("microscope", "Microscope inspection"),
    ]),
    step("o2_descum", "Step 7", "O2 descum", tool_="Oxford ICP chlorine",
         rows=descum_rows("Oxford ICP chlorine")),
    step("wet_etch", "Step 8A", "Wet etch", tool_="Acid bench", optional=True, rows=[
        row("etchant", "Phosphoric acid / Al etchant", temp(20), minutes(7), tool("Acid bench"),
            specs("Aim 7 min etch time (6-8 min)"), comment("Etch rates vary based on thickness and sample size")),
        row("diw_1", "DIW 1", minutes(2), num("stirrer_rpm", "Magnetic stirrer", "rpm", 600)),
        row("diw_2", "DIW 2", comment("Use a second beaker of fresh DIW to wash out wafer")),
        blank("diw_rinse_n2_dry", "DIW rinse + N2 dry"),
    ]),
    step("dry_etch", "Step 8B", "Dry etch", tool_="Oxford ICP fluorine", optional=True, rows=[
        row("dry_etch", "Dry etch", recipe("MS_NbN etch"), tool("Oxford ICP fluorine"),
            num("forward_power_w", "Forward power", "W"),
            num("icp_power_w", "ICP power", "W"),
            num("pressure_mtorr", "Pressure", "mTorr"),
            num("cf4_flow_sccm", "CF4 flow", "sccm", 50),
            num("etch_time_s", "Etch time", "s"),
            comment("Calculated based on the etch rate and thickness")),
        blank("unload_wafer", "Unload wafer"),
        *chamber_clean_rows(minutes_=None),
    ]),
    # The sheet lists O2 descum values here; confirm the real trench recipe.
    step("wafer_trench", "Step 9", "Wafer trench", tool_="Oxford ICP fluorine", optional=True, rows=[
        row("trench_etch", "Trench etch", recipe("OPT_CF4_etch"), tool("Oxford ICP fluorine"),
            num("forward_power_w", "Forward power", "W", 30),
            num("icp_power_w", "ICP power", "W", 0),
            num("pressure_mtorr", "Pressure", "mTorr", 80),
            num("gas_flow_sccm", "Gas flow", "sccm", 100),
            num("etch1_time_s", "Etch step 1 time", "s", 5),
            num("etch2_time_s", "Etch step 2 time", "s", 20)),
        blank("unload_wafer", "Unload wafer"),
        *chamber_clean_rows(),
    ]),
    step("resist_strip_qubit", "Step 10A", "Photoresist stripping (qubit)", tool_="Hotplate / Sonicator",
         condition={"wafer_type": "qubit"}, rows=[
        row("nmp_1_hotplate", "NMP 1 (hotplate)", temp(80), minutes(20), tool("Hotplate")),
        sonicate("nmp_1_sonicate_1", "NMP 1 sonication 1", 65, 10, 37, 50),
        sonicate("nmp_1_sonicate_2", "NMP 1 sonication 2", 65, 10, 80, 50),
        sonicate("nmp_2", "NMP 2", 65, 5, 80, 50, note="New beaker of fresh NMP"),
        sonicate("ipa_1", "IPA 1", 50, 5, 80, 50),
        row("ipa_2", "IPA 2", temp(50), minutes(2), tool("Hotplate")),
        blank("ipa_rinse_n2_dry", "IPA rinse and N2 blow dry"),
    ]),
    step("resist_strip_test", "Step 10B", "Photoresist stripping (test)", tool_="Hotplate / Sonicator",
         condition={"wafer_type": "test"}, rows=[
        row("nmp_1_hotplate", "NMP 1 (hotplate)", temp(80), minutes(20), tool("Hotplate")),
        sonicate("nmp_1_sonicate_1", "NMP 1 sonication 1", 65, 10, 37, 50),
        sonicate("nmp_1_sonicate_2", "NMP 1 sonication 2", 65, 10, 80, 50),
        sonicate("ipa_1", "IPA 1", 50, 5, 80, 50),
        blank("ipa_rinse_n2_dry", "IPA rinse and N2 blow dry"),
    ]),
    step("jj_resist_spin", "Step 11", "JJ e-beam resist spin", tool_="E-beam spinner / Oven", rows=[
        row("dehydration_bake", "Dehydration bake", temp(100), minutes(3), tool("CEE hotplate"), program_name("100C_180s")),
        row("cooldown_1", "Wafer cooldown", minutes(1), comment("After placing in spinner")),
        row("spincoat_mma", "Spincoat MMA", resist("MMA"), rpm(4000), seconds(45), tool("ebeam spinner"), program(14)),
        row("bake_mma", "Bake", temp(180), minutes(5), tool("Oven")),
        row("cooldown_2", "Wafer cooldown", minutes(1)),
        row("spincoat_pmma", "Spincoat PMMA", resist("PMMA C2"), rpm(1000), seconds(45), tool("ebeam spinner"), program(4)),
        row("bake_pmma", "Bake", temp(180), minutes(5), tool("Oven")),
        row("cooldown_3", "Wafer cooldown", minutes(1)),
        blank("clean_spinner", "Clean spinner"),
    ]),
    step("jj_ebeam_exposure", "Step 12", "JJ e-beam exposure", tool_="E-beam writer", rows=[
        row("base_dose", "Base dose", num("dose_uc_cm2", "Dose", "uC/cm2", 1100)),
        row("undercut_dose", "Undercut dose", num("dose_pct_of_base", "Dose", "% of base", 25)),
        row("jj_layer", "JJ layer", text("layer", "Layer", "2/0")),
        row("undercut_layer", "Undercut layer", text("layer", "Layer", "10/0")),
    ]),
    step("jj_development", "Step 13", "JJ development", tool_="Solvent bench", rows=[
        row("mibk_ipa", "MIBK:IPA 1:3", temp(20), seconds(60), tool("Solvent bench"), comment("Mild agitation")),
        row("ipa", "IPA", temp(20), seconds(30)),
        row("ipa_rinse", "IPA rinse", comment("Mildly using wash bottle")),
        blank("n2_blow_dry", "N2 blow dry"),
        blank("microscope", "Microscope inspection"),
    ]),
    step("cut_chiplets", "Step 14", "Cut into chiplets", tool_="Dicing saw", optional=True, action="create_chiplets", rows=[
        row("cut", "Cut wafer into chiplets", tool("Dicing saw"), comment()),
    ]),
    step("jj_o2_descum", "Step 15", "JJ O2 descum", tool_="Oxford ICP chlorine",
         rows=descum_rows("Oxford ICP chlorine")),
    step("jj_native_oxide_removal", "Step 16", "JJ native oxide removal", tool_="HF Bench", optional=True, rows=[
        row("pad_etch", "Al PAD etch 639", temp(20), seconds(10), tool("HF Bench")),
        row("diw_beaker_1", "DIW beaker 1", temp(20), seconds(20), tool("HF Bench")),
        row("diw_beaker_2", "DIW beaker 2", temp(20), seconds(20), tool("HF Bench")),
        row("diw_rinse", "DIW rinse", temp(20), tool("HF Bench")),
        row("n2_blow_dry", "N2 blow dry", tool("HF Bench")),
        blank("transfer_glove_box", "Transfer to glove box"),
    ]),
    step("jj_deposition", "Step 17", "JJ deposition (pDolan)", tool_="Plassys", rows=[
        row("load_wafer", "Load wafer into loadlock", comment("With right orientation")),
        row("sequence", "Sequence", text("sequence_name", "Sequence name")),
        row("ar_milling", "Ar milling", num("voltage_v", "Acc. voltage", "V", 250),
            num("current_ma", "Current", "mA", 100), seconds(60), comment("Subject to change with recipe")),
        row("ti_gettering_1", "Ti gettering", thickness_nm(35), rate(2), accuracy(5)),
        row("lead_1", "Lead 1", num("tilt_deg", "Tilt", "deg", 60), thickness_nm(60), rate(2), accuracy(5)),
        row("oxidation", "Oxidation", pressure_torr(15), seconds(900), comment("Subject to change with recipe")),
        row("ti_gettering_2", "Ti gettering", thickness_nm(35), rate(2)),
        row("lead_2", "Lead 2", num("tilt_deg", "Tilt", "deg", 0), thickness_nm(70), rate(2), accuracy(5)),
        row("capping_oxide", "Capping oxide", pressure_torr(10), seconds(300)),
        blank("unload_wafer", "Unload wafer into loadlock"),
    ]),
    step("predicing_resist", "Step 18", "Resist coating (pre-dicing)", tool_="CEE hotplate", rows=[
        row("spincoat", "Spincoat", resist("S1805"), rpm(2000), seconds(45), program(5),
            comment("No prebake to avoid heating JJs")),
        row("bake", "Bake", temp(100), minutes(3), tool("CEE hotplate")),
        blank("clean_spinner", "Clean up spinner"),
    ]),
    step("dicing", "Step 19", "Dicing into chips", tool_="Dicing saw", action="create_chips", rows=[
        row("dicing", "Dicing", text("location", "Location", "Marvell"), tool("Dicing saw")),
    ]),
    step("jj_liftoff", "Step 20", "JJ liftoff", tool_="Hotplate / Sonicator", rows=[
        row("nmp_1_hotplate", "NMP 1 (hotplate)", temp(80), minutes(120), tool("Hotplate"),
            specs("Mild pipetting to remove metal"), comment("Remove metal with pipette and transfer to waste")),
        row("nmp_1_sonicate", "NMP 1 (sonicate)", temp(65), seconds(15), tool("Sonicator with double beaker"),
            freq(80), power_pct(30), comment("Using the same NMP beaker")),
        row("ipa_1", "IPA 1", temp(50), minutes(10), tool("Hotplate"),
            comment("First rinse in another IPA beaker to remove excess NMP before transferring to good IPA beaker")),
        blank("ipa_rinse_n2_dry", "IPA rinse and N2 blow dry"),
    ]),
    step("jj_post_clean", "Step 21", "JJ post clean", optional=True, rows=[
        row("post_clean", "Post clean", chem(), temp(), minutes(), tool(), comment()),
    ]),
]

WAFER_SPEC_STEP = {
    "id": "wafer_spec", "label": "Step 0", "name": "Wafer specification",
    "optional": False, "condition": None, "tool": None, "action": None, "rows": [],
    "parameters": [
        text("substrate_material", "Substrate material", "Silicon 001"),
        text("substrate_spec", "Substrate specification", "Res >20000 kOhm DSP 550um thick SSP"),
        text("base_metal", "Base metal"),
        text("batch_number", "Batch number"),
        text("gds_file", "GDS file name / link"),
        text("mask_design", "Reviewed chip map"),
    ],
}

# "Template defaults": named sets of default values within one process
# template (e.g. per base metal, device type, person or project). Each lists
# only what it changes relative to the template's own defaults:
#     "overrides": {step_id: {row_key: {field_key: value}}}
QCMF_QUBIT_V1_DEFAULTS = {
    "standard": {"name": "Standard (WFR_04)", "overrides": {}},
}

FAB_TEMPLATES = {
    "QCMF_Qubit_v1": {
        "name": "QCMF qubit wafer",
        # Wafers go into their labeled box after this step.
        "label_after_step": "native_oxide_removal",
        "wafer_options": {
            "wafer_type": ["qubit", "test"],
        },
        "wafer_spec": WAFER_SPEC_STEP,
        "steps": QCMF_QUBIT_V1_STEPS,
        "template_defaults": QCMF_QUBIT_V1_DEFAULTS,
    },
}

DEFAULT_TEMPLATE_DEFAULT = "standard"


def check_template_defaults(template_id):
    """Fail at import if a template default names a step, row or field that doesn't exist."""
    template = FAB_TEMPLATES[template_id]
    steps = {s["id"]: s for s in template["steps"]}
    for default_id, default in template["template_defaults"].items():
        for step_id, rows in default["overrides"].items():
            if step_id not in steps:
                raise ValueError(f"{template_id}/{default_id}: unknown step '{step_id}'")
            step_rows = {r["key"]: r for r in steps[step_id]["rows"]}
            for row_key, fields in rows.items():
                if row_key not in step_rows:
                    raise ValueError(f"{template_id}/{default_id}: unknown row '{step_id}.{row_key}'")
                field_keys = {f["key"] for f in step_rows[row_key]["fields"]}
                for field_key in fields:
                    if field_key not in field_keys:
                        raise ValueError(f"{template_id}/{default_id}: unknown field '{step_id}.{row_key}.{field_key}'")


def get_step(template_id, step_id):
    template = FAB_TEMPLATES[template_id]
    if step_id == WAFER_SPEC_STEP["id"]:
        return template["wafer_spec"]
    return next((s for s in template["steps"] if s["id"] == step_id), None)


def step_applies(step, wafer_options):
    condition = step.get("condition") or {}
    return all(wafer_options.get(k) == v for k, v in condition.items())


for _template_id in FAB_TEMPLATES:
    check_template_defaults(_template_id)
