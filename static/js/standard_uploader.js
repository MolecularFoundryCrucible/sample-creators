// Standard uploader client-side controller (shared by insitu_pl, dfs_microscope, hip_microscope).

let TOOL_CONFIG = {};
let currentSample = null;

document.addEventListener('DOMContentLoaded', async () => {
    const configEl = document.getElementById('tool-config-json');
    if (configEl) {
        TOOL_CONFIG = JSON.parse(configEl.textContent);
    }
    await loadUserState();
    await populatePrinterSelect('printer-select');
});

// ========== Sample Handling ==========

async function lookupSample() {
    const val = document.getElementById('sample_barcode').value.trim();
    const status = document.getElementById('sample-status');
    if (!val) {
        status.textContent = 'Enter a barcode or sample name';
        return;
    }
    status.textContent = 'Looking up…';
    try {
        const res = await api(`${TOOL_CONFIG.url_prefix}/api/lookup-sample`, 'POST', {
            sample_unique_id: val,
            sample_name: val,
        });
        currentSample = res;
        status.textContent = `✓ Found: ${res.sample_name} (${res.unique_id})`;
        populateSampleFields(res);
        showSamplePanel('found');
    } catch (e) {
        if (e.status === 409 && e.data?.candidates) {
            showAmbiguousSampleModal(e.data.candidates, (selected) => {
                currentSample = selected;
                document.getElementById('sample_barcode').value = selected.unique_id;
                status.textContent = `✓ Selected: ${selected.sample_name} (${selected.unique_id})`;
                populateSampleFields(selected);
                showSamplePanel('found');
            });
            status.textContent = 'Multiple candidates found — select from popup.';
            return;
        }
        currentSample = null;
        status.textContent = 'Sample not found. Fill details below to create.';
        showSamplePanel('create');
    }
}

function clearSample() {
    currentSample = null;
    document.getElementById('sample_barcode').value = '';
    document.getElementById('sample_name').value = '';
    document.getElementById('sample_type').value = '';
    document.getElementById('sample_description').value = '';
    document.getElementById('sample-status').textContent = '';
    showSamplePanel('hidden');
}

function populateSampleFields(sample) {
    document.getElementById('sample_name').value = sample.sample_name || '';
    document.getElementById('sample_name_text').textContent = sample.sample_name || '';
    document.getElementById('sample_type').value = sample.sample_type || '';
    document.getElementById('sample_type_text').textContent = sample.sample_type || '';
    document.getElementById('sample_description').value = sample.description || '';
    document.getElementById('sample_description_text').textContent = sample.description || '';
}

function showSamplePanel(mode) {
    const panel = document.getElementById('sample-detail-panel');
    const header = document.getElementById('sample-panel-header');
    const createRow = document.getElementById('create-btn-row');
    const fieldIds = ['sample_name', 'sample_type', 'sample_description'];

    if (mode === 'hidden') {
        panel.classList.add('hidden');
        return;
    }
    panel.classList.remove('hidden');
    if (mode === 'found') {
        header.textContent = 'Sample Details';
        createRow.classList.add('hidden');
        for (const id of fieldIds) {
            document.getElementById(id).classList.add('hidden');
            document.getElementById(id + '_text').classList.remove('hidden');
        }
    } else {
        header.textContent = 'Create New Sample';
        createRow.classList.remove('hidden');
        for (const id of fieldIds) {
            document.getElementById(id).classList.remove('hidden');
            document.getElementById(id + '_text').classList.add('hidden');
        }
    }
}

async function createSample() {
    const name = document.getElementById('sample_name').value.trim();
    const type = document.getElementById('sample_type').value.trim();
    const desc = document.getElementById('sample_description').value.trim();
    if (!name || !type) {
        showAlert('warning', 'Sample Name and Type are required');
        return;
    }
    try {
        const res = await api(`${TOOL_CONFIG.url_prefix}/api/create-sample`, 'POST', {
            sample_name: name,
            sample_type: type,
            description: desc,
        });
        currentSample = res;
        document.getElementById('sample_barcode').value = res.unique_id;
        document.getElementById('sample-status').textContent = `✓ Created: ${res.sample_name} (${res.unique_id})`;
        populateSampleFields(res);
        showSamplePanel('found');
        showAlert('success', `Created sample ${res.sample_name}`);
    } catch (e) {
        showAlert('error', `Sample creation failed: ${e.message}`);
    }
}

async function printSampleBarcode() {
    const printer = document.getElementById('printer-select').value;
    if (!printer) {
        showAlert('warning', 'Please select a printer');
        return;
    }
    const sampleId = currentSample?.unique_id || document.getElementById('sample_barcode').value.trim();
    const sampleName = currentSample?.sample_name || '';
    if (!sampleId) {
        showAlert('warning', 'No sample to print');
        return;
    }
    try {
        await api(`${TOOL_CONFIG.url_prefix}/api/print-barcode`, 'POST', {
            printer_id: printer,
            sample_id: sampleId,
            sample_name: sampleName,
        });
        showAlert('success', `Print job sent to ${printer}`);
    } catch (e) {
        showAlert('error', `Print failed: ${e.message}`);
    }
}

// ========== Upload Workflow ==========

async function getFileIdentity(file) {
    let embeddedDsid = null;
    if (file.name.toLowerCase().endsWith('.h5')) {
        try {
            if (window.InstrumentParsers?.readH5EmbeddedInfo) {
                const info = await window.InstrumentParsers.readH5EmbeddedInfo(file, file.name);
                if (info?.dsid) embeddedDsid = info.dsid;
            }
        } catch (e) {
            console.warn('Could not read embedded H5 info', e);
        }
    }
    let sha256Hash = null;
    if (!embeddedDsid && window.InstrumentParsers?.computeBlobSha256) {
        try {
            sha256Hash = await window.InstrumentParsers.computeBlobSha256(file);
        } catch (e) {
            console.warn('Could not compute SHA-256', e);
        }
    }
    return { embeddedDsid, sha256Hash };
}

async function startStandardUpload() {
    if (!currentUserState || !currentUserState.selected_project) {
        showAlert('warning', 'Please login and select a project first.');
        return;
    }
    const fileInput = document.getElementById('std-files');
    const files = Array.from(fileInput.files || []);
    if (!files.length) {
        showAlert('warning', 'Please select at least one file.');
        return;
    }

    const groupAsOne = document.getElementById('std-group-as-one').checked || files.length === 1;
    const ingestor = document.getElementById('std-ingestor').value.trim() || TOOL_CONFIG.ingestor || '';
    const datasetNameOverride = document.getElementById('std-dataset-name').value.trim();
    const sessionName = document.getElementById('std-session-name').value.trim();
    const comments = document.getElementById('std-comments').value.trim();
    const rawKeywords = document.getElementById('std-keywords').value;
    const keywords = rawKeywords.split(',').map(s => s.trim()).filter(Boolean);
    const sampleUniqueId = currentSample?.unique_id || document.getElementById('sample_barcode').value.trim() || null;

    const progressSection = document.getElementById('section-progress');
    const progressEl = document.getElementById('std-upload-progress');
    const resultEl = document.getElementById('std-upload-result');
    progressSection.classList.remove('hidden');
    resultEl.innerHTML = '';

    showAlert('info', 'Starting upload…');

    try {
        if (groupAsOne) {
            // Group all files into a single dataset
            progressEl.innerHTML = '<div class="info-text">Checking file identity &amp; creating dataset…</div>';
            const { embeddedDsid, sha256Hash } = await getFileIdentity(files[0]);

            const dsRes = await api(`${TOOL_CONFIG.url_prefix}/api/create-dataset`, 'POST', {
                embedded_dsid: embeddedDsid,
                sha256_hash: sha256Hash,
                dataset_name: datasetNameOverride || null,
                session_name: sessionName || null,
                comments,
                keywords,
                sample_unique_id: sampleUniqueId,
            });

            const datasetMfid = dsRes.dataset_mfid;
            progressEl.innerHTML = `<div class="info-text">Dataset <code>${datasetMfid}</code> prepared. Uploading ${files.length} file(s)…</div>`;

            const uploadResults = await window.CrucibleUpload.uploadFiles({
                datasetMfid,
                files,
                ingestion: () => ({
                    requested: Boolean(ingestor),
                    ...(ingestor ? { ingestionClass: ingestor } : {}),
                }),
                onProgress: (file, p) => {
                    const pct = file.size ? Math.min(100, Math.round((p.uploadedBytes / file.size) * 100)) : 100;
                    progressEl.innerHTML = `<div class="info-text">Uploading <code>${escapeHtml(file.name)}</code>: ${pct}%</div>`;
                },
            });

            const allOk = uploadResults.every(r => r.ok);
            if (!allOk) {
                const failed = uploadResults.filter(r => !r.ok);
                throw new Error(`Failed uploading ${failed.length} file(s)`);
            }

            // Post-processing
            let postprocessMsg = '';
            if (TOOL_CONFIG.post_processing && TOOL_CONFIG.post_processing.length > 0) {
                progressEl.innerHTML = `<div class="info-text">Requesting post-processing (${TOOL_CONFIG.post_processing.join(', ')})…</div>`;
                await api(`${TOOL_CONFIG.url_prefix}/api/postprocess`, 'POST', {
                    dataset_id: datasetMfid,
                });
                postprocessMsg = ` Post-processing requested: ${TOOL_CONFIG.post_processing.join(', ')}.`;
            }

            progressEl.innerHTML = '<div class="info-text" style="color:#22543d; font-weight:700;">✓ Upload complete!</div>';
            resultEl.innerHTML = `<div class="alert alert-success" style="margin-top:10px;">
                <strong>Upload Complete!</strong> Dataset: <code>${escapeHtml(datasetMfid)}</code>.${escapeHtml(postprocessMsg)}<br>
                <a href="${escapeHtml(dsRes.hub_url)}" target="_blank" style="font-weight:700; color:#1a365d; text-decoration:underline;">
                    View Dataset in Crucible Hub &rarr;
                </a>
            </div>`;
            showAlert('success', `Dataset ${datasetMfid} uploaded successfully`);

        } else {
            // Independent dataset per file
            const results = [];
            for (let i = 0; i < files.length; i++) {
                const file = files[i];
                progressEl.innerHTML = `<div class="info-text">[${i + 1}/${files.length}] Creating dataset for <code>${escapeHtml(file.name)}</code>…</div>`;

                const { embeddedDsid, sha256Hash } = await getFileIdentity(file);
                const dsName = datasetNameOverride ? `${datasetNameOverride}_${file.name}` : file.name;

                const dsRes = await api(`${TOOL_CONFIG.url_prefix}/api/create-dataset`, 'POST', {
                    embedded_dsid: embeddedDsid,
                    sha256_hash: sha256Hash,
                    dataset_name: dsName,
                    session_name: sessionName || null,
                    comments,
                    keywords,
                    sample_unique_id: sampleUniqueId,
                });

                const datasetMfid = dsRes.dataset_mfid;
                progressEl.innerHTML = `<div class="info-text">[${i + 1}/${files.length}] Uploading <code>${escapeHtml(file.name)}</code> to <code>${datasetMfid}</code>…</div>`;

                const uploadResults = await window.CrucibleUpload.uploadFiles({
                    datasetMfid,
                    files: [file],
                    ingestion: () => ({
                        requested: Boolean(ingestor),
                        ...(ingestor ? { ingestionClass: ingestor } : {}),
                    }),
                });

                if (!uploadResults[0]?.ok) {
                    throw new Error(`Failed uploading ${file.name}`);
                }

                if (TOOL_CONFIG.post_processing && TOOL_CONFIG.post_processing.length > 0) {
                    await api(`${TOOL_CONFIG.url_prefix}/api/postprocess`, 'POST', {
                        dataset_id: datasetMfid,
                    });
                }

                results.push({ file: file.name, datasetMfid, hubUrl: dsRes.hub_url });
            }

            progressEl.innerHTML = '<div class="info-text" style="color:#22543d; font-weight:700;">✓ All datasets uploaded successfully!</div>';
            let resHtml = '<div class="alert alert-success" style="margin-top:10px;"><strong>Uploaded Datasets:</strong><ul style="margin:4px 0 0 16px;">';
            results.forEach(r => {
                resHtml += `<li><code>${escapeHtml(r.file)}</code> &rarr; <a href="${escapeHtml(r.hubUrl)}" target="_blank"><code>${escapeHtml(r.datasetMfid)}</code></a></li>`;
            });
            resHtml += '</ul></div>';
            resultEl.innerHTML = resHtml;
            showAlert('success', `Uploaded ${results.length} datasets`);
        }

    } catch (e) {
        progressEl.innerHTML = `<div class="alert alert-error">Upload failed: ${escapeHtml(e.message)}</div>`;
        showAlert('error', `Upload failed: ${e.message}`);
    }
}

// ========== Logbook Functions ==========

async function loadRecentDatasets() {
    const tbody = document.getElementById('recent-table-body');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="7">Loading datasets…</td></tr>';
    try {
        const rows = await fetchLogbookRows(TOOL_CONFIG.url_prefix);
        const cols = ['Date', 'User', 'Dataset Name', 'Measurement', 'Data Type', 'Dataset ID', 'Comment'];
        renderLogbookTable(rows, 'recent-table-body', cols);
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="7">Failed to load datasets: ${escapeHtml(e.message)}</td></tr>`;
    }
}

function exportCsv() {
    downloadLogbookCsv(TOOL_CONFIG.url_prefix, `${TOOL_CONFIG.key}_recent_datasets.csv`);
}
