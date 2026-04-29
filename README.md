# Sample Data Entry Apps

Flask web apps for beamline data entry (GIWAXS, RGA, B30 sputter).

## Run locally

```bash
git clone <repo>
# install uv: https://docs.astral.sh/uv/getting-started/installation/
uv sync
uv run flask run
```

Open http://localhost:5000.

## Making changes

| What to change | Where |
|---|---|
| Form fields / page layout | `templates/<page>.html` |
| Client-side logic, form submission | `static/js/<page>.js` |
| Backend logic, API/DB calls | `routes/<page>.py` |
| Styles | `static/css/style.css` |
| New page | add `routes/newpage.py`, `templates/newpage.html`, `static/js/newpage.js` |

Pages: `giwaxs`, `rga`, `b30_sputter`. Shared utilities in `routes/shared.py` and `static/js/shared.js`.
