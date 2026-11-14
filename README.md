# Sample Data Entry Apps

Flask web apps for Molecular Foundry & ALS sample creation, fabrication tracking, and instrument data entry across three divisions:

- **ALS:** GIWAXS bar creator (`giwaxs`), RGA carrier creator (`rga`)
- **B30:** AJA & KJLesker Sputter (`b30_sputter`), E-beam (`b30_ebeam`), SEM (`b30_sem`), Raman (`b30_raman`), Electrolytes (`electrolyte`), Schema Forms (`schema_forms`), Barcode Printing (`print_only`)
- **B67:** Synthesis Upload (`synthesis`), Fabrication Traveler & GDS Chip Maps (`fabrication`, `chip_maps`)

## Run locally

```bash
git clone <repo>
# install uv: https://docs.astral.sh/uv/getting-started/installation/
uv sync
npm --prefix frontend ci
npm --prefix frontend run build
uv run flask run
```

Open https://crucible.lbl.gov/sample-creators/ (or `http://localhost:5000` locally).

## Test

```bash
uv run python -m unittest discover -s tests -v
npm --prefix frontend test
npm --prefix frontend run typecheck
```

## Making changes

| What to change | Where |
|---|---|
| Division / tool registry & instrument configs | `config.py`, `tool_registry.py` |
| Form fields / page layout | `templates/<page>.html` |
| Classic page client-side logic | `static/js/<page>.js` |
| TypeScript / React Vite bundles (`static/dist`) | `frontend/src/` (`npm --prefix frontend run build`) |
| Backend logic, Crucible / ALS API calls | `routes/<page>.py` |
| Styles | `static/css/style.css`, `frontend/src/manual-synthesis/styles/` |

Shared utilities live in `routes/shared.py` and `static/js/shared.js`:
- **Deposition tools** (`b30_sputter`, `b30_ebeam`) share sample handling, logbook, and CSV export via `routes/deposition_common.py` and `static/js/deposition_common.js`. `b30_sputter` registers one blueprint per entry in `SPUTTER_TOOLS` in `config.py`.
- **Single-sample file-upload instruments** (`b30_sem`, `b30_raman`) share routes and client logic via `routes/instrument_page.py`, `static/js/instrument_page.js`, and browser file parsers/direct-upload helpers in `frontend/src/parsers/` and `frontend/src/upload/`.
- **B67 React islands** (`synthesis`, `fabrication` traveler + chip maps) mount Vite bundles built from `frontend/src/manual-synthesis/` and `frontend/src/chip-map/`.
