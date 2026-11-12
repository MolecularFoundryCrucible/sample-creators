// Shared logic for single-sample instrument pages (B30 SEM, B30 Raman): sample panel, upload,
// logbook. The page script defines INSTRUMENT_PAGE before DOMContentLoaded:
//   apiBase          e.g. '/b30-sem' (the blueprint's URL prefix)
//   logbookCols      column names returned by /api/recent-datasets
//   csvFilename      name of the logbook CSV route
//   selectedFiles()  File[] to upload with the dataset
//   ingestionFor(f)  {requested, ingestionClass?} per file
//   filesPreview()   [[label, value], ...] rows for the confirmation dialog
//   resetForm()      clears the page-specific parts of the form
//   init()           optional page-specific setup
// Element ids (sample panel, logbook, upload-progress, param-grid) are the same on every page.

document.addEventListener('DOMContentLoaded', async () => {
    await loadUserState();
    await loadInstrumentState();

    if (!document.getElementById('sample_barcode').value.trim()) {
        showSamplePanel('create');
    }
    initParamGridResponsive();
    document.getElementById('sample_barcode').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') lookupSample();
    });
    INSTRUMENT_PAGE.init?.();
});

const instrumentApi = (path) => `${INSTRUMENT_PAGE.apiBase}/api/${path}`;

// ========== State ==========

async function loadInstrumentState() {
    try {
        const state = await api(instrumentApi('state'));
        if (state.sample_unique_id) {
            document.getElementById('sample_barcode').value = state.sample_unique_id;
            populateSampleFields(state);
            setSampleStatus('found', state.sample_name);
            showSamplePanel('found');
        }
    } catch {
        // No state yet, that's fine
    }
}

// ========== Sample panel ==========

function showSamplePanel(mode) {
    document.getElementById('sample_type_results')?.classList.add('hidden');
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

async function lookupSample() {
    const barcode = document.getElementById('sample_barcode').value.trim();
    if (!barcode) {
        showAlert('error', 'Please scan or enter a barcode');
        return;
    }
    try {
        const data = await api(instrumentApi('lookup-sample'), 'POST', { unique_id: barcode });
        if (data.found) {
            populateSampleFields(data);
            setSampleStatus('found', data.sample_name);
            showSamplePanel('found');
            showAlert('success', `Found sample: ${data.sample_name}`);
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

async function createSample() {
    const sampleName = document.getElementById('sample_name').value.trim();
    const sampleType = document.getElementById('sample_type').value.trim();
    const description = document.getElementById('sample_description').value.trim();

    if (!sampleName || !sampleType) {
        showAlert('error', 'Sample name and type are required');
        return;
    }
    try {
        const data = await api(instrumentApi('create-sample'), 'POST', {
            sample_name: sampleName,
            sample_type: sampleType,
            description,
        });
        document.getElementById('sample_barcode').value = data.unique_id;
        populateSampleFields(data);
        setSampleStatus('created', data.sample_name);
        showSamplePanel('found');
        showAlert('success', `Created sample: ${data.sample_name} (${data.unique_id})`);
    } catch (e) {
        showAlert('error', e.message);
    }
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
        await api(instrumentApi('print-barcode'), 'POST', { sample_id: barcode, sample_name: name });
        showAlert('success', `Sent barcode to printer: ${name || barcode}`);
    } catch (e) {
        showAlert('error', e.message);
    }
}

function populateSampleFields(data) {
    document.getElementById('sample_name').value = data.sample_name || '';
    document.getElementById('sample_type').value = data.sample_type || '';
    document.getElementById('sample_description').value = data.description || data.sample_description || '';
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

// ========== Upload ==========

// Form values keyed by data-key. Checkboxes give 'true' or nothing; two inputs sharing a key with
// data-range-index="0"/"1" give a [start, end] pair of numbers (only when both are filled).
function collectFormMetadata() {
    const metadata = {};
    const ranges = {};
    document.querySelectorAll('[data-key]').forEach(el => {
        const key = el.dataset.key;
        if (el.dataset.rangeIndex !== undefined) {
            (ranges[key] ??= [])[Number(el.dataset.rangeIndex)] = el.value.trim();
            return;
        }
        const val = el.type === 'checkbox' ? (el.checked ? 'true' : '') : (el.value ?? '').toString().trim();
        if (val) metadata[key] = val;
    });
    for (const [key, [start, end] = []] of Object.entries(ranges)) {
        if (start && end) metadata[key] = [Number(start), Number(end)];
    }
    return metadata;
}

function uploadDataset() {
    const barcode = document.getElementById('sample_barcode').value.trim();
    if (!barcode) {
        showAlert('error', 'No sample selected. Scan a barcode first.');
        return;
    }
    const metadata = collectFormMetadata();
    const sampleName = document.getElementById('sample_name').value || barcode;
    showModal('Confirm Upload', buildUploadPreview(sampleName, metadata), async () => {
        await doUpload(metadata);
    });
}

function buildUploadPreview(sampleName, metadata) {
    const rows = Object.entries(metadata).map(([k, v]) => [k, Array.isArray(v) ? v.join(' – ') : v]);
    rows.push(...INSTRUMENT_PAGE.filesPreview());
    let html = `<p><strong>Sample:</strong> ${escapeHtml(sampleName)}</p>`;
    html += '<table class="preview-table"><thead><tr><th>Field</th><th>Value</th></tr></thead><tbody>';
    html += rows.length
        ? rows.map(([k, v]) => `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(String(v))}</td></tr>`).join('')
        : '<tr><td colspan="2">No fields filled in</td></tr>';
    return html + '</tbody></table>';
}

// The dataset is created here from the form; files then go from the browser straight to storage
// (no size limit) and are ingested by the instrument's ingestors.
async function doUpload(metadata) {
    const files = INSTRUMENT_PAGE.selectedFiles();
    try {
        if (files.length && !window.CrucibleUpload) {
            throw new Error('The upload module did not load. Reload the page and try again.');
        }
        const dataset = await api(instrumentApi('upload-dataset'), 'POST', metadata);
        if (!files.length) {
            showAlert('success', `Dataset uploaded: ${dataset.dataset_name} (${dataset.dataset_id})`);
            return;
        }

        const progressEl = document.getElementById('upload-progress');
        const totalBytes = files.reduce((sum, f) => sum + f.size, 0);
        const uploaded = new Map();
        progressEl.textContent = `Uploading ${files.length} file(s)…`;
        let results;
        try {
            results = await window.CrucibleUpload.uploadFiles({
                datasetMfid: dataset.dataset_id,
                files,
                ingestion: INSTRUMENT_PAGE.ingestionFor,
                onProgress: (file, progress) => {
                    uploaded.set(file, progress.uploadedBytes);
                    let done = 0;
                    for (const bytes of uploaded.values()) done += bytes;
                    const pct = totalBytes ? Math.min(100, Math.floor((100 * done) / totalBytes)) : 100;
                    progressEl.textContent = `Uploading ${files.length} file(s): ${pct}%`;
                },
            });
        } finally {
            progressEl.textContent = '';
        }

        const ok = results.filter(r => r.ok);
        showAlert(ok.length === files.length ? 'success' : 'error',
            `Dataset uploaded: ${dataset.dataset_name} (${dataset.dataset_id}) — ${ok.length} of ${files.length} file(s) attached`);
        for (const r of results) {
            if (!r.ok) showAlert('error', `${r.file.name}: ${r.error}`);
            else if (r.ingestionError) showAlert('error', `${r.file.name} uploaded, but ingestion couldn't be requested: ${r.ingestionError}`);
        }
    } catch (e) {
        showAlert('error', `Upload failed: ${e.message}`);
    }
}

// ========== Logbook ==========

function setRecentLoading(isLoading) {
    document.getElementById('recent-loading')?.classList.toggle('hidden', !isLoading);
    for (const id of ['recent-fetch-btn', 'recent-export-btn']) {
        const btn = document.getElementById(id);
        if (btn) btn.disabled = isLoading;
    }
}

function recentLimit() {
    return encodeURIComponent(document.getElementById('recent-limit')?.value || '100');
}

async function fetchRecentDatasets() {
    setRecentLoading(true);
    try {
        const res = await api(`${instrumentApi('recent-datasets')}?limit=${recentLimit()}`);
        renderRecentDatasets(res.rows || []);
    } catch (e) {
        showAlert('error', `Failed to load recent datasets: ${e.message}`);
    } finally {
        setRecentLoading(false);
    }
}

function renderRecentDatasets(rows) {
    const tbody = document.getElementById('recent-table-body');
    if (!tbody) return;
    const cols = INSTRUMENT_PAGE.logbookCols;
    if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="${cols.length}">No datasets found.</td></tr>`;
        return;
    }
    tbody.innerHTML = rows.map((r, i) =>
        `<tr style="background:${i % 2 === 0 ? '#ffffff' : '#f2f2f2'}">`
        + cols.map(c => `<td>${escapeHtml(String(r[c] ?? ''))}</td>`).join('')
        + '</tr>').join('');
}

async function exportRecentDatasets() {
    try {
        const base = (typeof BASE_URL !== 'undefined' ? BASE_URL : '');
        const res = await fetch(`${base}${instrumentApi('recent-datasets/' + INSTRUMENT_PAGE.csvFilename)}?limit=${recentLimit()}`);
        if (!res.ok) {
            let msg = 'Export failed';
            try { msg = (await res.json()).error || msg; } catch {}
            throw new Error(msg);
        }
        const url = URL.createObjectURL(await res.blob());
        const a = document.createElement('a');
        a.href = url;
        const match = (res.headers.get('Content-Disposition') || '').match(/filename="?([^"]+)"?/);
        a.download = match ? match[1] : INSTRUMENT_PAGE.csvFilename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        showAlert('success', 'CSV downloaded');
    } catch (e) {
        showAlert('error', e.message);
    }
}

// ========== Layout ==========

function initParamGridResponsive() {
    const grid = document.getElementById('param-grid');
    if (!grid) return;
    const update = () => {
        grid.style.gridTemplateColumns = window.innerWidth <= 700 ? '1fr' : 'repeat(2, minmax(0, 1fr))';
    };
    update();
    window.addEventListener('resize', update);
}

registerLogoutReset(() => {
    clearSample();
    INSTRUMENT_PAGE.resetForm();
    document.getElementById('upload-status').textContent = '';
});
