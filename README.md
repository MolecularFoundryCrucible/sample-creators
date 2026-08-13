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

Pages: `giwaxs`, `rga`, `b30_sputter`, `print_only`. Shared utilities in `routes/shared.py` and `static/js/shared.js`.

Barcode printing goes over MQTT via `publish_barcode()` in `routes/shared.py`. Printers are
allowlisted in `PRINT_CONFIG["printers"]` in `config.py` — add new ones there.
