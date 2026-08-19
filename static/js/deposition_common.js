// Sample handling shared by the B30 deposition data-entry pages (sputter, e-beam).
//
// Each page defines DEPOSITION_API_BASE (e.g. "/b30-ebeam") before loading this file; every
// request below is relative to it, so the same code drives both blueprints.

function depApi(path, method = 'GET', body = null) {
    return api(DEPOSITION_API_BASE + path, method, body);
}

// ========== State ==========

async function loadDepositionState() {
    let state;
    try {
        state = await depApi('/api/state');
    } catch {
        return null; // No state yet, that's fine
    }

    renderRunSamples(state.run_samples || []);

    if (state.sample_unique_id) {
        document.getElementById('sample_barcode').value = state.sample_unique_id;
        populateSampleFields(state);
        setSampleStatus('found', state.sample_name);
        showSamplePanel('found');
    }

    return state;
}

// ========== Sample Panel Mode ==========

function showSamplePanel(mode) {
    const panel = document.getElementById('sample-detail-panel');
    const header = document.getElementById('sample-panel-header');
    const createRow = document.getElementById('create-btn-row');
    const fieldIds = ['sample_name', 'sample_type', 'sample_description'];

    if (mode === 'hidden') {
        panel.classList.add('hidden');
        for (const id of fieldIds) {
            document.getElementById(id).classList.remove('hidden');
            document.getElementById(id + '_text').classList.add('hidden');
        }
        return;
    }

    panel.classList.remove('hidden');
    if (mode === 'found') {
        header.textContent = 'Sample Details';
        createRow.classList.add('hidden');
        for (const id of fieldIds) {
            const input = document.getElementById(id);
            const span = document.getElementById(id + '_text');
            span.textContent = input.value;
            input.classList.add('hidden');
            span.classList.remove('hidden');
        }
    } else {
        header.textContent = 'Add New';
        createRow.classList.remove('hidden');
        for (const id of fieldIds) {
            document.getElementById(id).classList.remove('hidden');
            document.getElementById(id + '_text').classList.add('hidden');
        }
    }
}

// ========== Sample Lookup ==========

async function lookupSample() {
    const barcode = document.getElementById('sample_barcode').value.trim();
    if (!barcode) {
        showAlert('error', 'Please scan or enter a barcode');
        return;
    }
    try {
        const data = await depApi('/api/lookup-sample', 'POST', { unique_id: barcode });
        if (data.found) {
            populateSampleFields(data);
            setSampleStatus('found', data.sample_name);
            showSamplePanel('found');
            renderRunSamples(data.run_samples);
            selectBarcodeForNextScan();
            showAlert('success', data.already_in_run
                ? `${data.sample_name} is already in this run`
                : `Found sample: ${data.sample_name} — added to this run`);
        } else {
            document.getElementById('sample_barcode').value = '';
            clearSampleFields();
            setSampleStatus('not-found', '');
            showSamplePanel('create');
            showAlert('info', 'Sample not found — enter details and click Create');
        }
    } catch (e) {
        showAlert('error', e.message);
    }
}

// ========== Sample Creation ==========

async function createSample() {
    const sampleName = document.getElementById('sample_name').value.trim();
    const sampleType = document.getElementById('sample_type').value.trim();
    const description = document.getElementById('sample_description').value.trim();

    if (!sampleName || !sampleType) {
        showAlert('error', 'Sample name and type are required');
        return;
    }
    try {
        await postCreateSample(sampleName, sampleType, description, false);
    } catch (e) {
        if (e.status === 409 && e.data && e.data.exists) {
            const ids = (e.data.existing_ids || []).map(escapeHtml).join('<br>');
            showModal(
                'Duplicate sample name',
                `<p>${escapeHtml(e.message)}</p>
                 <p>Existing:<br>${ids}</p>
                 <p>Creating another will give you two samples with the same name
                    and different barcodes.</p>`,
                () => postCreateSample(sampleName, sampleType, description, true)
                          .catch(err => showAlert('error', err.message)),
                'Create anyway'
            );
            return;
        }
        showAlert('error', e.message);
    }
}

async function postCreateSample(sampleName, sampleType, description, allowDuplicate) {
    const data = await depApi('/api/create-sample', 'POST', {
        sample_name: sampleName,
        sample_type: sampleType,
        description,
        allow_duplicate: allowDuplicate,
    });
    document.getElementById('sample_barcode').value = data.unique_id;
    populateSampleFields(data);
    setSampleStatus('created', data.sample_name);
    showSamplePanel('found');
    renderRunSamples(data.run_samples);
    selectBarcodeForNextScan();
    showAlert('success', `Created sample: ${data.sample_name} (${data.unique_id}) — added to this run`);
}

// The last sample's barcode stays in the box so it can still be printed, so select it —
// a scanner types into the field and would otherwise append to the previous ID.
function selectBarcodeForNextScan() {
    const el = document.getElementById('sample_barcode');
    el.focus();
    el.select();
}

function clearSample() {
    document.getElementById('sample_barcode').value = '';
    clearSampleFields();
    showSamplePanel('create');
    setSampleStatus('', '');
}

async function printSampleBarcode() {
    const barcode = document.getElementById('sample_barcode').value.trim();
    const name = document.getElementById('sample_name').value.trim();

    if (!barcode) {
        showAlert('error', 'No sample selected — scan or create a sample first');
        return;
    }
    try {
        await depApi('/api/print-barcode', 'POST', {
            sample_id: barcode,
            sample_name: name,
        });
        showAlert('success', `Sent barcode to printer: ${name || barcode}`);
    } catch (e) {
        showAlert('error', e.message);
    }
}

// ========== Samples linked to the run ==========

async function removeRunSample(uniqueId) {
    try {
        const data = await depApi('/api/run-samples/remove', 'POST', { unique_id: uniqueId });
        renderRunSamples(data.run_samples);
    } catch (e) {
        showAlert('error', e.message);
    }
}

async function clearRunSamples(silent = false) {
    try {
        const data = await depApi('/api/run-samples/clear', 'POST');
        renderRunSamples(data.run_samples);
        if (!silent) showAlert('info', 'Cleared samples from this run');
    } catch (e) {
        if (!silent) showAlert('error', e.message);
    }
}

function renderRunSamples(samples) {
    const body = document.getElementById('run-sample-body');
    const count = document.getElementById('run-sample-count');
    if (!body) return;

    const list = samples || [];
    if (count) count.textContent = String(list.length);

    body.innerHTML = '';
    if (!list.length) {
        body.innerHTML = '<tr><td>No samples yet.</td></tr>';
        return;
    }

    list.forEach(s => {
        const tr = document.createElement('tr');

        const nameTd = document.createElement('td');
        nameTd.dataset.runSampleId = s.unique_id;
        nameTd.textContent = s.sample_name || s.unique_id;
        nameTd.title = s.unique_id;

        const btnTd = document.createElement('td');
        btnTd.style.width = '1%';
        const btn = document.createElement('button');
        btn.className = 'btn';
        btn.type = 'button';
        btn.textContent = 'Remove';
        btn.addEventListener('click', () => removeRunSample(s.unique_id));
        btnTd.appendChild(btn);

        tr.appendChild(nameTd);
        tr.appendChild(btnTd);
        body.appendChild(tr);
    });
}

function getRunSampleNames() {
    return Array.from(document.querySelectorAll('#run-sample-body [data-run-sample-id]'))
                .map(el => el.textContent);
}

// ========== Dataset field collection ==========

// Every form control carrying a data-key contributes one scientific_metadata entry.
function collectDatasetFields() {
    const payload = {};
    document.querySelectorAll('[data-key]').forEach(el => {
        const val = el.type === 'checkbox'
            ? (el.checked ? 'true' : '')
            : (el.value ?? '').toString().trim();
        if (val) payload[el.dataset.key] = val;
    });
    return payload;
}

// ========== Layout ==========

function initDatasetGridResponsive() {
    const grid = document.getElementById('dataset-grid');
    if (!grid) return;

    function updateDatasetGridColumns() {
        grid.style.gridTemplateColumns =
            window.innerWidth <= 700 ? '1fr' : 'repeat(2, minmax(0, 1fr))';
    }

    updateDatasetGridColumns();
    window.addEventListener('resize', updateDatasetGridColumns);
}

// ========== Logbook shared bits ==========

function setRecentLoading(isLoading) {
    const el = document.getElementById('recent-loading');
    const fetchBtn = document.getElementById('recent-fetch-btn');
    const exportBtn = document.getElementById('recent-export-btn');
    if (el) el.classList.toggle('hidden', !isLoading);
    if (fetchBtn) fetchBtn.disabled = isLoading;
    if (exportBtn) exportBtn.disabled = isLoading;
}

function updateTargetOptionsFromRows(rows, preserveSelection = true) {
    const sel = document.getElementById('recent-target');
    if (!sel) return;

    const prev = preserveSelection ? (sel.value || 'All') : 'All';
    const mats = new Set();

    (rows || []).forEach(r => {
        const t = String(r["Target"] || "").trim();
        if (!t) return;
        // handles "Au + Cu"
        t.split("+").map(x => x.trim()).filter(Boolean).forEach(x => mats.add(x));
    });

    const options = ["All", ...Array.from(mats).sort((a, b) => a.localeCompare(b))];
    sel.innerHTML = "";
    options.forEach(opt => {
        const o = document.createElement("option");
        o.value = opt;
        o.textContent = opt;
        sel.appendChild(o);
    });

    sel.value = options.includes(prev) ? prev : "All";
}

function renderLogbookRows(cols, rows) {
    const tbody = document.getElementById('recent-table-body');
    if (!tbody) return;
    tbody.innerHTML = '';

    if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="${cols.length}">No datasets found.</td></tr>`;
        return;
    }

    rows.forEach((r, i) => {
        const tr = document.createElement('tr');
        tr.style.background = (i % 2 === 0) ? '#ffffff' : '#f2f2f2';
        cols.forEach(c => {
            const td = document.createElement('td');
            td.textContent = r[c] ?? '';
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

async function downloadLogbookCsv(path, params, fallbackName) {
    try {
        const base = (typeof BASE_URL !== 'undefined' ? BASE_URL : '');
        const qs = new URLSearchParams(params).toString();
        const res = await fetch(`${base}${DEPOSITION_API_BASE}${path}?${qs}`, { method: 'GET' });
        if (!res.ok) {
            let msg = 'Export failed';
            try {
                const err = await res.json();
                msg = err.error || msg;
            } catch {}
            throw new Error(msg);
        }

        const blob = await res.blob();
        const dlUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = dlUrl;

        const disposition = res.headers.get('Content-Disposition');
        const match = disposition && disposition.match(/filename="?([^"]+)"?/);
        a.download = match ? match[1] : fallbackName;

        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(dlUrl);
        showAlert('success', 'CSV downloaded');
    } catch (e) {
        showAlert('error', e.message);
    }
}

// ========== Helpers ==========

function populateSampleFields(data) {
    document.getElementById('sample_name').value = data.sample_name || '';
    document.getElementById('sample_type').value = data.sample_type || '';
    document.getElementById('sample_description').value = data.description || '';
}

function clearSampleFields() {
    document.getElementById('sample_name').value = '';
    document.getElementById('sample_type').value = '';
    document.getElementById('sample_description').value = '';
}

function setSampleStatus(state, name) {
    const el = document.getElementById('sample-status');
    if (state === 'found') {
        el.textContent = `✓ Loaded: ${name}`;
        el.style.color = 'var(--color-success, green)';
    } else if (state === 'created') {
        el.textContent = `✓ Created: ${name}`;
        el.style.color = 'var(--color-success, green)';
    } else if (state === 'not-found') {
        el.textContent = 'Sample not found — fill in details to create';
        el.style.color = 'var(--color-warning, orange)';
    } else {
        el.textContent = '';
    }
}

// Logging out has to drop the sample UI too, otherwise the next user inherits the previous
// user's run.
(function patchLogoutUserForDeposition() {
    if (typeof window.logoutUser !== 'function') return;

    const originalLogoutUser = window.logoutUser;

    window.logoutUser = async function (...args) {
        try {
            await originalLogoutUser.apply(this, args);
        } finally {
            clearSample();
            await clearRunSamples(true);
            // The sputter page tracks a created dataset for editing; the next user must not
            // inherit it and update someone else's record.
            if (typeof setDatasetSaved === 'function') setDatasetSaved(null, null);
        }
    };
})();
