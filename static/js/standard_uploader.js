// Standard uploader client-side controller (shared by insitu_pl, dfs_microscope, hip_microscope).

let TOOL_CONFIG = {};

document.addEventListener('DOMContentLoaded', async () => {
    TOOL_CONFIG = readToolConfig();
    initUploaderSampleInput();
    if (typeof registerLogoutReset === 'function') {
        registerLogoutReset(() => clearSample());
    }
    await loadUserState();
    await populatePrinterSelect('printer-select');
});

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
    const sampleUniqueId = getSelectedSampleUniqueId();

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
            showAlert('success', `Dataset ${datasetMfid} uploaded successfully`, { linkUrl: dsRes.hub_url || hubDatasetUrl(datasetMfid) });

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
            showAlert('success', `Uploaded ${results.length} datasets`, results.length === 1 ? { linkUrl: results[0].hubUrl || hubDatasetUrl(results[0].datasetMfid) } : { linkUrl: hubProjectUrl(currentUserState?.selected_project), linkText: 'Open Project in Crucible Hub \u2197' });
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
