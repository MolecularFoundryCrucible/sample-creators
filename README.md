# Sample Data Entry Apps

Flask web apps for beamline data entry (GIWAXS, RGA, B30 sputter).

## Run locally

```bash
git clone <repo>
# install uv: https://docs.astral.sh/uv/getting-started/installation/
uv sync
uv run flask run
```

Open https://crucible.lbl.gov/sample-creators/.

## Making changes

| What to change | Where |
|---|---|
| Form fields / page layout | `templates/<page>.html` |
| Client-side logic, form submission | `static/js/<page>.js` |
| Backend logic, API/DB calls | `routes/<page>.py` |
| Styles | `static/css/style.css` |
| New page | add `routes/newpage.py`, `templates/newpage.html`, `static/js/newpage.js` |

Pages: `giwaxs`, `rga`, `b30_sputter`. Shared utilities in `routes/shared.py` and `static/js/shared.js`.

`b30_sputter` serves one page per sputter tool (AJA, KJLesker) from the same code: the
blueprint is registered once per entry in `SPUTTER_TOOLS` in `config.py`, and each view
calls `_tool()` to get its own instrument, calibration sample, form fields and session
state. To add a tool, add an entry to `SPUTTER_TOOLS` — the nav links and home page cards
pick it up automatically. To let one tool's form diverge from the other, give that tool
its own `dataset_fields` list instead of the shared `SPUTTER_DATASET_FIELDS`.
