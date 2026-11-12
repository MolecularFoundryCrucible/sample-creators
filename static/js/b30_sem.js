// B30 SEM Data Entry - Page Logic

document.addEventListener('DOMContentLoaded', async () => {
    await loadUserState();
    await loadSemState();

    const hasLoadedSample = !!document.getElementById('sample_barcode').value.trim();
    if (!hasLoadedSample) {
        showSamplePanel('create');
    }

    initSemGridResponsive();

    document.getElementById('sample_barcode').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') lookupSample();
    });
});

// ========== State ==========

async function loadSemState() {
    try {
        const state = await api('/b30-sem/api/state');
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

// ========== Sample Panel Mode ==========

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

// ========== Sample Lookup ==========

async function lookupSample() {
    const barcode = document.getElementById('sample_barcode').value.trim();
    if (!barcode) {
        showAlert('error', 'Please scan or enter a barcode');
        return;
    }
    try {
        const data = await api('/b30-sem/api/lookup-sample', 'POST', { unique_id: barcode });
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
        const data = await api('/b30-sem/api/create-sample', 'POST', {
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
        await api('/b30-sem/api/print-barcode', 'POST', {
            sample_id: barcode,
            sample_name: name,
        });
        showAlert('success', `Sent barcode to printer: ${name || barcode}`);
    } catch (e) {
        showAlert('error', e.message);
    }
}

// ========== Images saved toggle ==========

function onImagesSavedChange() {
    const yes = document.getElementById('images-yes').checked;
    const uploadSection = document.getElementById('section-image-upload');

    if (yes) {
        uploadSection.classList.remove('hidden');
    } else {
        uploadSection.classList.add('hidden');
        // Clear file selection and hints
        document.getElementById('sem-image-files').value = '';
        document.getElementById('non-tiff-hint').style.display = 'none';
        const statusEl = document.getElementById('tiff-extract-status');
        statusEl.style.display = 'none';
        statusEl.textContent = '';
    }
}

async function onSemFilesSelected() {
    const input = document.getElementById('sem-image-files');
    const nonTiffHint = document.getElementById('non-tiff-hint');
    const statusEl = document.getElementById('tiff-extract-status');

    statusEl.style.display = 'none';
    statusEl.textContent = '';

    if (!input.files || input.files.length === 0) {
        nonTiffHint.style.display = 'none';
        return;
    }

    // Auto-extract from the first TIFF in the selection, if any
    const tiffFile = Array.from(input.files).find(f =>
        f.name.toLowerCase().endsWith('.tif') || f.name.toLowerCase().endsWith('.tiff')
    );

    if (tiffFile) {
        nonTiffHint.style.display = 'none';
        await extractTiffMetadata(tiffFile);
    } else {
        nonTiffHint.style.display = '';
    }
}

// ========== TIFF metadata extraction ==========

async function extractTiffMetadata(tiffFile) {
    const statusEl = document.getElementById('tiff-extract-status');
    statusEl.style.display = '';
    statusEl.textContent = 'Extracting metadata…';

    const formData = new FormData();
    formData.append('file', tiffFile);

    try {
        const base = (typeof BASE_URL !== 'undefined' ? BASE_URL : '');
        const res = await fetch(`${base}/b30-sem/api/extract-tiff-metadata`, {
            method: 'POST',
            body: formData,
        });
        const data = await res.json();

        if (!res.ok) {
            statusEl.textContent = '';
            showAlert('error', data.error || 'Extraction failed');
            return;
        }

        if (!data.found || !data.fields || Object.keys(data.fields).length === 0) {
            statusEl.textContent = 'No metadata found';
            showAlert('info', data.message || 'No FEI metadata found in this TIFF. Please fill in parameters manually.');
            return;
        }

        // Populate form fields
        const fields = data.fields;
        const fieldMap = {
            'vacuum_level':          'field_vacuum_level',
            'spot_size':             'field_spot_size',
            'high_voltage_V':        'field_high_voltage_V',
            'emission_current_A':    'field_emission_current_A',
            'chamber_pressure_Torr': 'field_chamber_pressure_Torr',
        };

        let filled = 0;
        for (const [key, elId] of Object.entries(fieldMap)) {
            if (fields[key] != null && fields[key] !== '') {
                const el = document.getElementById(elId);
                if (el) {
                    el.value = fields[key];
                    filled++;
                }
            }
        }

        statusEl.textContent = `✓ Filled ${filled} field(s)`;
        showAlert('success', `Metadata extracted: ${filled} field(s) auto-filled`);
    } catch (e) {
        statusEl.textContent = '';
        showAlert('error', `Extraction error: ${e.message}`);
    }
}

// ========== EDX toggle ==========

function onEdxToggle() {
    const checked = document.getElementById('field_edx_used').checked;
    const details = document.getElementById('edx-details');
    if (checked) {
        details.classList.remove('hidden');
    } else {
        details.classList.add('hidden');
        // Clear EDX fields when disabled
        document.getElementById('edx-image-files').value = '';
        document.getElementById('edx-spectrum-file').value = '';
        document.getElementById('field_primary_energy_keV').value = '';
        document.getElementById('edx-spectrum-status').textContent = '';
    }
}

async function onEdxSpectrumSelected() {
    const input = document.getElementById('edx-spectrum-file');
    const statusEl = document.getElementById('edx-spectrum-status');
    const file = input.files && input.files[0];
    if (!file) {
        statusEl.textContent = '';
        return;
    }
    statusEl.textContent = 'Reading spectrum…';
    try {
        const keV = await readBrukerPrimaryEnergy(file);
        if (keV === null) {
            statusEl.textContent = 'No primary energy found in this file. Please enter it manually.';
            return;
        }
        document.getElementById('field_primary_energy_keV').value = keV;
        statusEl.textContent = `✓ Primary energy ${keV} keV filled from the spectrum`;
    } catch (e) {
        statusEl.textContent = '';
        showAlert('error', `Could not read the spectrum: ${e.message}`);
    }
}

// ========== Bruker EDX parsing ==========

// Primary energy (keV) of the first spectrum in a Bruker Esprit .spx/.rtx export, or null.
// The value sits in each spectrum's TRTESMAHeader as e.g. <PrimaryEnergy>1E1</PrimaryEnergy>,
// and in .rtx projects with maps it can be tens of MB into the file, so read in chunks.
async function readBrukerPrimaryEnergy(file) {
    const CHUNK = 4 * 1024 * 1024;
    const OVERLAP = 256;
    const decoder = new TextDecoder('windows-1252');
    const pattern = /<PrimaryEnergy>\s*([^<\s]+)\s*<\/PrimaryEnergy>/;
    for (let offset = 0; offset < file.size; offset += CHUNK) {
        const start = Math.max(0, offset - OVERLAP);
        const text = decoder.decode(await file.slice(start, offset + CHUNK).arrayBuffer());
        const match = pattern.exec(text);
        if (match) {
            const keV = Number(match[1]);
            return Number.isFinite(keV) ? keV : null;
        }
    }
    return null;
}

// ========== Dataset Upload ==========

async function uploadDataset() {
    const barcode = document.getElementById('sample_barcode').value.trim();
    if (!barcode) {
        showAlert('error', 'No sample selected. Scan a barcode first.');
        return;
    }

    // Collect scalar metadata fields
    const metadata = {};
    document.querySelectorAll('[data-key]').forEach(el => {
        const key = el.dataset.key;
        let val;
        if (el.type === 'checkbox') {
            val = el.checked ? 'true' : '';
        } else {
            val = (el.value ?? '').toString().trim();
        }
        if (val) metadata[key] = val;
    });

    const sampleName = document.getElementById('sample_name').value || barcode;

    showModal(
        'Confirm Upload',
        buildUploadPreview(sampleName, metadata),
        async () => {
            await _doUpload(metadata);
        }
    );
}

// "direct": files go from the browser straight to storage (no size limit) and are ingested by
// the FEI SEM / Bruker EDX ingestors. "legacy": files are posted to this app, which forwards
// them (Cloud Run caps that request at 32 MB). ?upload=direct|legacy overrides the default.
function semUploadMode() {
    const requested = new URLSearchParams(window.location.search).get('upload');
    if (requested === 'direct' || requested === 'legacy') return requested;
    return typeof SEM_UPLOAD_MODE_DEFAULT !== 'undefined' ? SEM_UPLOAD_MODE_DEFAULT : 'legacy';
}

function selectedSemFiles() {
    const files = [];
    if (document.getElementById('images-yes').checked) {
        files.push(...document.getElementById('sem-image-files').files);
    }
    if (document.getElementById('field_edx_used').checked) {
        files.push(...document.getElementById('edx-image-files').files);
        files.push(...document.getElementById('edx-spectrum-file').files);
    }
    return files;
}

function semIngestion(file) {
    const name = file.name.toLowerCase();
    if (name.endsWith('.tif') || name.endsWith('.tiff')) {
        // Falls back to the generic TIFF ingestor if the file has no FEI metadata.
        return { requested: true, ingestionClass: 'FeiSemTifIngestor' };
    }
    if (name.endsWith('.spx') || name.endsWith('.rtx')) {
        return { requested: true, ingestionClass: 'BrukerEdxIngestor' };
    }
    return { requested: true };
}

async function _doDirectUpload(metadata, files) {
    if (!window.CrucibleUpload) {
        throw new Error('The upload module did not load. Reload the page and try again.');
    }
    const progressEl = document.getElementById('upload-progress');
    // Without files in the request, this only creates the dataset and links the sample.
    const dataset = await api('/b30-sem/api/upload-dataset', 'POST', metadata);

    const totalBytes = files.reduce((sum, f) => sum + f.size, 0);
    const uploaded = new Map();
    progressEl.textContent = `Uploading ${files.length} file(s)…`;
    let results;
    try {
        results = await window.CrucibleUpload.uploadFiles({
            datasetMfid: dataset.dataset_id,
            files,
            ingestion: semIngestion,
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
    let msg = `Dataset uploaded: ${dataset.dataset_name} (${dataset.dataset_id}) — ${ok.length} of ${files.length} file(s) attached`;
    showAlert(ok.length === files.length ? 'success' : 'error', msg);
    for (const r of results) {
        if (!r.ok) showAlert('error', `${r.file.name}: ${r.error}`);
        else if (r.ingestionError) showAlert('error', `${r.file.name} uploaded, but ingestion couldn't be requested: ${r.ingestionError}`);
    }
}

async function _doUpload(metadata) {
    const files = selectedSemFiles();
    const hasFiles = files.length > 0;
    const imagesSaved = document.getElementById('images-yes').checked;
    const edxUsed = document.getElementById('field_edx_used').checked;

    try {
        if (hasFiles && semUploadMode() === 'direct') {
            await _doDirectUpload(metadata, files);
            return;
        }
        let result;
        if (hasFiles) {
            // Use multipart upload
            const formData = new FormData();
            formData.append('metadata', JSON.stringify(metadata));

            if (imagesSaved) {
                for (const f of document.getElementById('sem-image-files').files) {
                    formData.append('sem_images', f);
                }
            }
            if (edxUsed) {
                for (const f of document.getElementById('edx-image-files').files) {
                    formData.append('edx_images', f);
                }
                const spectrum = document.getElementById('edx-spectrum-file').files[0];
                if (spectrum) {
                    formData.append('edx_spectrum', spectrum);
                }
            }

            const base = (typeof BASE_URL !== 'undefined' ? BASE_URL : '');
            const res = await fetch(`${base}/b30-sem/api/upload-dataset`, {
                method: 'POST',
                body: formData,
            });
            result = await res.json();
            if (!res.ok) throw new Error(result.error || 'Upload failed');
        } else {
            result = await api('/b30-sem/api/upload-dataset', 'POST', metadata);
        }

        let msg = `Dataset uploaded: ${result.dataset_name} (${result.dataset_id})`;
        if (result.uploaded_files && result.uploaded_files.length > 0) {
            msg += ` — ${result.uploaded_files.length} file(s) attached`;
        }
        showAlert('success', msg);
    } catch (e) {
        showAlert('error', `Upload failed: ${e.message}`);
    }
}

function buildUploadPreview(sampleName, payload) {
    let html = `<p><strong>Sample:</strong> ${sampleName}</p>`;
    html += '<table class="preview-table"><thead><tr><th>Field</th><th>Value</th></tr></thead><tbody>';

    let shown = 0;
    for (const [k, v] of Object.entries(payload)) {
        html += `<tr><td>${k}</td><td>${v}</td></tr>`;
        shown++;
    }

    // Summarise attached files
    const semFiles = document.getElementById('sem-image-files').files;
    const edxImgFiles = document.getElementById('edx-image-files').files;
    const edxSpectrum = document.getElementById('edx-spectrum-file').files;

    if (semFiles.length > 0) {
        html += `<tr><td>SEM images</td><td>${semFiles.length} file(s)</td></tr>`;
    }
    if (edxImgFiles.length > 0) {
        html += `<tr><td>EDX images</td><td>${edxImgFiles.length} file(s)</td></tr>`;
    }
    if (edxSpectrum.length > 0) {
        html += `<tr><td>EDX spectrum</td><td>${edxSpectrum[0].name}</td></tr>`;
    }

    if (shown === 0 && semFiles.length === 0) {
        html += '<tr><td colspan="2">No fields filled in</td></tr>';
    }

    html += '</tbody></table>';
    return html;
}

// ========== Logbook ==========

function setRecentLoading(isLoading) {
    const el = document.getElementById('recent-loading');
    const fetchBtn = document.getElementById('recent-fetch-btn');
    const exportBtn = document.getElementById('recent-export-btn');
    if (el) el.classList.toggle('hidden', !isLoading);
    if (fetchBtn) fetchBtn.disabled = isLoading;
    if (exportBtn) exportBtn.disabled = isLoading;
}

async function fetchRecentDatasets() {
    setRecentLoading(true);
    try {
        const limit = document.getElementById('recent-limit')?.value || '100';
        const res = await api(`/b30-sem/api/recent-datasets?limit=${encodeURIComponent(limit)}`);
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
    tbody.innerHTML = '';

    const cols = [
        "Date", "User", "Vacuum", "Spot", "HV (V)",
        "Current (A)", "Pressure (Torr)", "EDX", "Energy (keV)", "Comment"
    ];

    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="10">No datasets found.</td></tr>';
        return;
    }

    rows.forEach((r, i) => {
        const tr = document.createElement('tr');
        tr.style.background = (i % 2 === 0) ? '#ffffff' : '#f2f2f2';
        tr.innerHTML = cols.map(c => `<td>${(r[c] ?? '')}</td>`).join('');
        tbody.appendChild(tr);
    });
}

async function exportRecentDatasets() {
    const limit = document.getElementById('recent-limit')?.value || '100';

    try {
        const base = (typeof BASE_URL !== 'undefined' ? BASE_URL : '');
        const url = `${base}/b30-sem/api/recent-datasets/b30_sem_recent_datasets.csv`
            + `?limit=${encodeURIComponent(limit)}`;

        const res = await fetch(url, { method: 'GET' });
        if (!res.ok) {
            let msg = 'Export failed';
            try { const err = await res.json(); msg = err.error || msg; } catch {}
            throw new Error(msg);
        }

        const blob = await res.blob();
        const dlUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = dlUrl;

        const disposition = res.headers.get('Content-Disposition');
        const match = disposition && disposition.match(/filename="?([^"]+)"?/);
        a.download = match ? match[1] : 'b30_sem_recent_datasets.csv';

        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(dlUrl);
        showAlert('success', 'CSV downloaded');
    } catch (e) {
        showAlert('error', e.message);
    }
}

// ========== Grid responsiveness ==========

function initSemGridResponsive() {
    const grid = document.getElementById('sem-param-grid');
    if (!grid) return;

    function update() {
        grid.style.gridTemplateColumns =
            window.innerWidth <= 700 ? '1fr' : 'repeat(2, minmax(0, 1fr))';
    }
    update();
    window.addEventListener('resize', update);
}

// ========== Shared helpers ==========

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

// ========== Form Reset ==========

function resetSemForm() {
    // Images section
    document.getElementById('images-yes').checked = false;
    document.getElementById('images-no').checked = false;
    document.getElementById('section-image-upload').classList.add('hidden');
    document.getElementById('sem-image-files').value = '';
    const tiffStatus = document.getElementById('tiff-extract-status');
    tiffStatus.style.display = 'none';
    tiffStatus.textContent = '';
    document.getElementById('non-tiff-hint').style.display = 'none';

    // SEM parameters
    resetFieldsToDefault('#sem-param-grid [data-key]');

    // EDX
    resetFieldsToDefault('#section-edx [data-key]');
    document.getElementById('edx-details').classList.add('hidden');
    document.getElementById('edx-image-files').value = '';
    document.getElementById('edx-spectrum-file').value = '';
    document.getElementById('edx-spectrum-status').textContent = '';

    // Comment
    resetFieldsToDefault('#section-comment [data-key]');

    document.getElementById('upload-status').textContent = '';
}

registerLogoutReset(() => {
    clearSample();
    resetSemForm();
});
