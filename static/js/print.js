// Print list is keyed by MFID, so the same sample can never be queued twice
// whether it arrived from a search, a paste, or an uploaded file.
const printList = new Map();

// Crucible IDs look like "0tgfny1b35rwd000x35nr7a9d8" — used to work out which
// column of a pasted row is the MFID when there is no header.
const MFID_RE = /^[0-9a-z]{20,}$/i;

// ========== Print list ==========

function renderPrintList() {
    const tbody = document.getElementById('print-list');
    document.getElementById('print-count').textContent = printList.size;

    if (!printList.size) {
        tbody.innerHTML = '<tr><td colspan="3">No samples selected yet.</td></tr>';
        return;
    }

    tbody.innerHTML = '';
    for (const [mfid, name] of printList) {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${escapeHtml(name)}</td>
            <td style="font-family:monospace;">${escapeHtml(mfid)}</td>
            <td><button class="btn btn-secondary" type="button" title="Remove">&times;</button></td>`;
        tr.querySelector('button').addEventListener('click', () => {
            printList.delete(mfid);
            renderPrintList();
            syncResultCheckboxes();
        });
        tbody.appendChild(tr);
    }
}

function clearPrintList() {
    printList.clear();
    renderPrintList();
    syncResultCheckboxes();
}

function syncResultCheckboxes() {
    document.querySelectorAll('#search-results input[type="checkbox"]').forEach(cb => {
        cb.checked = printList.has(cb.dataset.mfid);
    });
    const all = document.getElementById('select-all');
    const boxes = document.querySelectorAll('#search-results input[type="checkbox"]');
    all.checked = boxes.length > 0 && [...boxes].every(cb => cb.checked);
}

// ========== Search ==========

async function runSearch() {
    const loading = document.getElementById('search-loading');
    const summary = document.getElementById('search-summary');
    loading.classList.remove('hidden');
    summary.textContent = '';
    try {
        const data = await api('/print/api/search', 'POST', {
            sample_name: document.getElementById('search_name').value.trim(),
            sample_type: document.getElementById('search_type').value.trim(),
            exact: document.getElementById('search_exact').checked,
            date_from: document.getElementById('search_from').value,
            date_to: document.getElementById('search_to').value,
        });
        renderResults(data.rows);
        // 50 is the server's cap on loose matching — say so rather than quietly truncating.
        summary.textContent = (data.fuzzy && data.count >= 50)
            ? `${data.count} results (limit reached — narrow the search or use Exact match)`
            : `${data.count} result${data.count === 1 ? '' : 's'}`;
    } catch (e) {
        showAlert('error', e.message);
    } finally {
        loading.classList.add('hidden');
    }
}

function clearSearch() {
    for (const id of ['search_name', 'search_type', 'search_from', 'search_to']) {
        document.getElementById(id).value = '';
    }
    document.getElementById('search_exact').checked = false;
    document.getElementById('search-summary').textContent = '';
    document.getElementById('select-all').checked = false;
    document.getElementById('search-results').innerHTML =
        '<tr><td colspan="6">Log in and search to see samples.</td></tr>';
}

function renderResults(rows) {
    const tbody = document.getElementById('search-results');

    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="6">No samples matched.</td></tr>';
        document.getElementById('select-all').checked = false;
        return;
    }

    tbody.innerHTML = '';
    for (const row of rows) {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><input type="checkbox"></td>
            <td>${escapeHtml(row.sample_name)}</td>
            <td>${escapeHtml(row.sample_type)}</td>
            <td style="font-family:monospace;">${escapeHtml(row.unique_id)}</td>
            <td>${escapeHtml(row.description)}</td>
            <td>${escapeHtml(row.timestamp)}</td>`;
        tr.querySelector('input').dataset.mfid = row.unique_id;
        tr.querySelector('input').addEventListener('change', ev => {
            if (ev.target.checked) printList.set(row.unique_id, row.sample_name);
            else printList.delete(row.unique_id);
            renderPrintList();
            syncResultCheckboxes();
        });
        tbody.appendChild(tr);
    }
    syncResultCheckboxes();
}

function toggleSelectAll(el) {
    // Each click below re-runs syncResultCheckboxes, which rewrites el.checked, so the
    // intended state has to be captured before the loop starts.
    const target = el.checked;
    document.querySelectorAll('#search-results input[type="checkbox"]').forEach(cb => {
        if (cb.checked !== target) cb.click();
    });
    el.checked = target;
}

// ========== Paste / upload ==========

function parseRows(text) {
    const lines = String(text || '').split(/\r?\n/).map(l => l.trim()).filter(Boolean);
    if (!lines.length) return { rows: [], skipped: 0 };

    const delim = lines[0].includes('\t') ? '\t' : ',';
    const split = line => line.split(delim).map(c => c.trim().replace(/^"|"$/g, ''));

    const header = split(lines[0]).map(c => c.toLowerCase());
    const mfidIdx = header.findIndex(h => ['mfid', 'unique_id', 'id', 'barcode', 'sample_id'].includes(h));
    const nameIdx = header.findIndex(h => ['name', 'sample_name', 'sample name'].includes(h));
    const hasHeader = mfidIdx !== -1;

    const rows = [];
    let skipped = 0;

    for (let i = hasHeader ? 1 : 0; i < lines.length; i++) {
        const cells = split(lines[i]);
        let mfid, name;

        if (hasHeader) {
            mfid = cells[mfidIdx] || '';
            name = nameIdx !== -1 ? (cells[nameIdx] || '') : '';
        } else {
            const idx = cells.findIndex(c => MFID_RE.test(c));
            if (idx === -1) { skipped++; continue; }
            mfid = cells[idx];
            name = cells.filter((_, j) => j !== idx).find(Boolean) || '';
        }

        if (!mfid) { skipped++; continue; }
        rows.push({ mfid, name });
    }

    return { rows, skipped };
}

function addParsed(text) {
    const { rows, skipped } = parseRows(text);
    if (!rows.length) {
        showAlert('error', 'No rows with a recognizable MFID were found');
        return;
    }
    for (const row of rows) printList.set(row.mfid, row.name);
    renderPrintList();
    syncResultCheckboxes();

    const note = skipped ? ` (${skipped} row(s) skipped — no MFID)` : '';
    showAlert('success', `Added ${rows.length} row(s) to the print list${note}`);
}

function clearBulk() {
    document.getElementById('bulk_text').value = '';
    // Assigning '' is the only way to deselect a chosen file.
    document.getElementById('bulk_file').value = '';
}

function addBulkRows() {
    const file = document.getElementById('bulk_file').files[0];
    if (file) {
        if (document.getElementById('bulk_text').value.trim()) {
            showAlert('info', `Using ${file.name} — clear the file to use the pasted rows instead`);
        }
        const reader = new FileReader();
        reader.onload = () => addParsed(reader.result);
        reader.onerror = () => showAlert('error', `Could not read ${file.name}`);
        reader.readAsText(file);
        return;
    }
    addParsed(document.getElementById('bulk_text').value);
}

// ========== Printing ==========

function printAll() {
    const printer = document.getElementById('printer_name').value.trim();
    const items = [...printList.entries()].map(([mfid, name]) => ({ mfid, name }));

    if (!printer) {
        showAlert('error', 'Enter a printer name');
        return;
    }
    if (!items.length) {
        showAlert('error', 'The print list is empty');
        return;
    }

    showModal(
        'Print barcodes',
        `<p>Print <strong>${items.length}</strong> barcode(s) on
         <strong>${escapeHtml(printer)}</strong>?</p>`,
        () => sendPrintJob(printer, items),
        'Print'
    );
}

async function sendPrintJob(printer, items) {
    try {
        const res = await api('/print/api/print-batch', 'POST', { printer, items });
        if (res.printed) {
            showAlert('success', `Sent ${res.printed} barcode(s) to ${res.printer}`);
        }
        for (const r of res.results.filter(x => !x.ok)) {
            showAlert('error', `${r.name || r.mfid}: ${r.error}`);
        }
    } catch (e) {
        showAlert('error', e.message);
    }
}

// ========== Init ==========

document.addEventListener('DOMContentLoaded', async () => {
    await loadUserState();
    renderPrintList();
});
