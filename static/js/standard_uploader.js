// Standard uploader client-side controller (shared by insitu_pl, dfs_microscope, hip_microscope).

let TOOL_CONFIG = {};
let isStandardUploading = false;

window.addEventListener('beforeunload', (event) => {
    if (isStandardUploading) {
        event.preventDefault();
        event.returnValue = '';
    }
});

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

function safeHubUrl(url) {
    return typeof url === 'string' && /^(https?:\/\/|\/)/i.test(url) ? url : '';
}

function resolveSafeDatasetHubUrl(hubUrl, datasetMfid) {
    return safeHubUrl(hubUrl) || safeHubUrl(hubDatasetUrl(datasetMfid));
}

function getPendingStorageKey(project, toolKey, sha256Hash) {
    return `crucible_std_pending:${project || ''}:${toolKey || ''}:${sha256Hash || ''}`;
}

function getPendingDatasetMfid(project, toolKey, sha256Hash) {
    if (!project || !toolKey || !sha256Hash) return null;
    try {
        const val = localStorage.getItem(getPendingStorageKey(project, toolKey, sha256Hash));
        return typeof val === 'string' && /^[0-9a-hjkmnp-tv-z]{26}$/i.test(val.trim()) ? val.trim() : null;
    } catch {
        return null;
    }
}

function setPendingDatasetMfid(project, toolKey, sha256Hash, datasetMfid) {
    if (!project || !toolKey || !sha256Hash || !datasetMfid) return;
    try {
        localStorage.setItem(getPendingStorageKey(project, toolKey, sha256Hash), datasetMfid.trim());
    } catch {
        // Ignore storage errors
    }
}

function clearPendingDatasetMfid(project, toolKey, sha256Hash) {
    if (!project || !toolKey || !sha256Hash) return;
    try {
        localStorage.removeItem(getPendingStorageKey(project, toolKey, sha256Hash));
    } catch {
        // Ignore storage errors
    }
}

function renderTwoStepProgress(containerEl, opts = {}) {
    const step1LabelText = opts.step1Label || 'Step 1/2: Create Dataset';
    const step2LabelText = opts.step2Label || 'Step 2/2: Uploading';

    containerEl.innerHTML = `
        <div class="upload-active-notice" id="std-active-notice">
            Upload in progress -- please do not close or refresh this browser tab until the upload is finished.
        </div>
        <div class="upload-steps">
            <div class="upload-step is-active" id="step-1-card">
                <div class="upload-step-header">
                    <div>
                        <span class="upload-step-label">${escapeHtml(step1LabelText)}</span>
                        <div class="upload-step-detail" id="step-1-detail"></div>
                    </div>
                    <span class="upload-step-pct" id="step-1-pct">0%</span>
                </div>
                <div class="upload-step-bar">
                    <div class="upload-step-bar-fill is-active" id="step-1-fill" style="width: 0%;"></div>
                </div>
            </div>
            <div class="upload-step" id="step-2-card">
                <div class="upload-step-header">
                    <div>
                        <span class="upload-step-label">${escapeHtml(step2LabelText)}</span>
                        <div class="upload-step-detail" id="step-2-detail"></div>
                    </div>
                    <span class="upload-step-pct" id="step-2-pct">0%</span>
                </div>
                <div class="upload-step-bar">
                    <div class="upload-step-bar-fill" id="step-2-fill" style="width: 0%;"></div>
                </div>
            </div>
        </div>
    `;

    const noticeEl = containerEl.querySelector('#std-active-notice');
    const step1Card = containerEl.querySelector('#step-1-card');
    const step1Fill = containerEl.querySelector('#step-1-fill');
    const step1Pct = containerEl.querySelector('#step-1-pct');
    const step1Detail = containerEl.querySelector('#step-1-detail');

    const step2Card = containerEl.querySelector('#step-2-card');
    const step2Fill = containerEl.querySelector('#step-2-fill');
    const step2Pct = containerEl.querySelector('#step-2-pct');
    const step2Detail = containerEl.querySelector('#step-2-detail');

    const hideNotice = () => {
        if (noticeEl) noticeEl.style.display = 'none';
    };

    return {
        hideNotice,
        updateStep1({ percent, detail, isDone }) {
            const clamped = Math.max(0, Math.min(100, Math.round(percent ?? 0)));
            if (step1Fill) {
                step1Fill.style.width = `${clamped}%`;
                step1Fill.classList.toggle('is-done', Boolean(isDone));
                step1Fill.classList.toggle('is-active', !isDone);
            }
            if (step1Card) {
                step1Card.classList.toggle('is-active', !isDone);
            }
            if (step1Pct) {
                step1Pct.textContent = `${clamped}%`;
            }
            if (step1Detail && detail !== undefined) {
                step1Detail.textContent = detail;
            }
            if (isDone && step2Card && step2Fill && !step2Fill.classList.contains('is-done')) {
                step2Card.classList.add('is-active');
                step2Fill.classList.add('is-active');
            }
        },
        updateStep2({ percent, detail, isDone }) {
            const clamped = Math.max(0, Math.min(100, Math.round(percent ?? 0)));
            if (step2Fill) {
                step2Fill.style.width = `${clamped}%`;
                step2Fill.classList.toggle('is-done', Boolean(isDone));
                step2Fill.classList.toggle('is-active', !isDone);
            }
            if (step2Card) {
                step2Card.classList.toggle('is-active', !isDone);
            }
            if (step2Pct) {
                step2Pct.textContent = `${clamped}%`;
            }
            if (step2Detail && detail !== undefined) {
                step2Detail.textContent = detail;
            }
            if (isDone) {
                hideNotice();
            }
        },
    };
}

async function getFileIdentity(file, onHashProgress) {
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
            sha256Hash = await window.InstrumentParsers.computeBlobSha256(
                file,
                (hashed, total) => onHashProgress?.(hashed, total)
            );
        } catch (e) {
            console.warn('Could not compute SHA-256', e);
        }
    }
    return { embeddedDsid, sha256Hash };
}

async function startStandardUpload() {
    if (isStandardUploading) return;
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

    const uploadBtn = document.getElementById('btn-std-upload');
    isStandardUploading = true;
    if (uploadBtn) uploadBtn.disabled = true;

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
    try {
        progressSection.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' });
    } catch {
        // Ignore scroll errors
    }
    resultEl.innerHTML = '';

    showAlert('info', 'Starting upload...');

    let steps = null;

    try {
        if (groupAsOne) {
            // Group all files into a single dataset
            steps = renderTwoStepProgress(progressEl, {
                step1Label: 'Step 1/2: Create Dataset',
                step2Label: 'Step 2/2: Uploading',
            });
            steps.updateStep1({ percent: 0, detail: 'Computing file identity...' });
            steps.updateStep2({ percent: 0, detail: 'Waiting for dataset creation...' });

            const { embeddedDsid, sha256Hash } = await getFileIdentity(files[0], (hashed, total) => {
                const pct = total === 0 ? 95 : Math.round((hashed / total) * 95);
                const rawPct = total === 0 ? 100 : Math.round((hashed / total) * 100);
                steps.updateStep1({
                    percent: pct,
                    detail: `Computing SHA-256 (${rawPct}%)...`,
                });
            });

            steps.updateStep1({
                percent: 95,
                detail: 'Creating dataset record in Crucible...',
            });

            let targetEmbeddedDsid = embeddedDsid;
            let usedPendingDsid = false;
            if (!targetEmbeddedDsid && sha256Hash) {
                const pendingDsid = getPendingDatasetMfid(currentUserState.selected_project, TOOL_CONFIG.key, sha256Hash);
                if (pendingDsid) {
                    targetEmbeddedDsid = pendingDsid;
                    usedPendingDsid = true;
                }
            }

            const createPayload = {
                embedded_dsid: targetEmbeddedDsid,
                sha256_hash: sha256Hash,
                dataset_name: datasetNameOverride || null,
                session_name: sessionName || null,
                comments,
                keywords,
                sample_unique_id: sampleUniqueId,
            };

            let dsRes;
            try {
                dsRes = await api(`${TOOL_CONFIG.url_prefix}/api/create-dataset`, 'POST', createPayload);
            } catch (err) {
                if (usedPendingDsid && (err.status === 403 || err.status === 404)) {
                    clearPendingDatasetMfid(currentUserState.selected_project, TOOL_CONFIG.key, sha256Hash);
                    createPayload.embedded_dsid = null;
                    dsRes = await api(`${TOOL_CONFIG.url_prefix}/api/create-dataset`, 'POST', createPayload);
                } else {
                    throw err;
                }
            }

            const datasetMfid = dsRes.dataset_mfid;
            if (sha256Hash && datasetMfid) {
                setPendingDatasetMfid(currentUserState.selected_project, TOOL_CONFIG.key, sha256Hash, datasetMfid);
            }
            const step1Detail = dsRes.reused
                ? `Dataset ${datasetMfid} (reused existing)`
                : `Dataset ${datasetMfid} ready`;
            steps.updateStep1({
                percent: 100,
                detail: step1Detail,
                isDone: true,
            });

            // Step 2/2: Uploading
            const existingSet = new Set(Array.isArray(dsRes.existing_filenames) ? dsRes.existing_filenames : []);
            const filesToSend = files;
            const filesToUpload = dsRes.reused
                ? filesToSend.filter(f => !existingSet.has(f.name))
                : filesToSend;

            const totalBytes = filesToSend.reduce((acc, f) => acc + (f.size || 0), 0);
            const fileUploadedBytes = new Map();
            for (const f of filesToSend) {
                if (dsRes.reused && existingSet.has(f.name)) {
                    fileUploadedBytes.set(f, f.size || 0);
                }
            }

            const calcGroupPct = () => {
                if (totalBytes === 0) return 100;
                let sum = 0;
                for (const b of fileUploadedBytes.values()) {
                    sum += b;
                }
                return Math.min(100, Math.round((sum / totalBytes) * 100));
            };

            if (filesToUpload.length === 0) {
                clearPendingDatasetMfid(currentUserState.selected_project, TOOL_CONFIG.key, sha256Hash);
                steps.updateStep2({
                    percent: 100,
                    detail: 'Already uploaded (reused existing dataset)',
                    isDone: true,
                });
            } else {
                steps.updateStep2({
                    percent: calcGroupPct(),
                    detail: `Uploading ${filesToUpload.length} file(s)...`,
                });

                const uploadResults = await window.CrucibleUpload.uploadFiles({
                    datasetMfid,
                    files: filesToUpload,
                    ingestion: () => ({
                        requested: Boolean(ingestor),
                        ...(ingestor ? { ingestionClass: ingestor } : {}),
                    }),
                    onProgress: (file, p) => {
                        fileUploadedBytes.set(file, Math.min(file.size || 0, p.uploadedBytes || 0));
                        const pct = calcGroupPct();
                        steps.updateStep2({
                            percent: pct,
                            detail: `Uploading ${file.name} (${pct}%)...`,
                        });
                    },
                });

                const allOk = uploadResults.every(r => r.ok);
                if (!allOk) {
                    const failed = uploadResults.filter(r => !r.ok);
                    throw new Error(`Failed uploading ${failed.length} file(s)`);
                }

                clearPendingDatasetMfid(currentUserState.selected_project, TOOL_CONFIG.key, sha256Hash);

                steps.updateStep2({
                    percent: 100,
                    detail: `Upload complete (${filesToSend.length} file(s))`,
                    isDone: true,
                });
            }

            // Post-processing
            let postprocessMsg = '';
            if (TOOL_CONFIG.post_processing && TOOL_CONFIG.post_processing.length > 0) {
                steps.updateStep2({
                    percent: 100,
                    detail: `Requesting post-processing (${TOOL_CONFIG.post_processing.join(', ')})...`,
                    isDone: true,
                });
                await api(`${TOOL_CONFIG.url_prefix}/api/postprocess`, 'POST', {
                    dataset_id: datasetMfid,
                });
                postprocessMsg = ` Post-processing requested: ${TOOL_CONFIG.post_processing.join(', ')}.`;
                steps.updateStep2({
                    percent: 100,
                    detail: `Post-processing requested (${TOOL_CONFIG.post_processing.join(', ')})`,
                    isDone: true,
                });
            }

            steps.hideNotice();

            const safeUrl = resolveSafeDatasetHubUrl(dsRes.hub_url, datasetMfid);
            const hubLinkHtml = safeUrl
                ? `<br><a href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer" style="font-weight:700; color:#1a365d; text-decoration:underline;">View Dataset in Crucible Hub &rarr;</a>`
                : '';

            resultEl.innerHTML = `<div class="alert alert-success" style="margin-top:10px;">
                <strong>Upload Complete!</strong> Dataset: <code>${escapeHtml(datasetMfid)}</code>.${escapeHtml(postprocessMsg)}${hubLinkHtml}
            </div>`;
            showAlert('success', `Dataset ${datasetMfid} uploaded successfully`, safeUrl ? { linkUrl: safeUrl } : undefined);

        } else {
            // Independent dataset per file
            const results = [];
            for (let i = 0; i < files.length; i++) {
                const file = files[i];
                const fileIdxLabel = `[${i + 1}/${files.length}]`;
                steps = renderTwoStepProgress(progressEl, {
                    step1Label: `${fileIdxLabel} Step 1/2: Create Dataset (${file.name})`,
                    step2Label: `${fileIdxLabel} Step 2/2: Uploading (${file.name})`,
                });
                steps.updateStep1({ percent: 0, detail: 'Computing file identity...' });
                steps.updateStep2({ percent: 0, detail: 'Waiting for dataset creation...' });

                const { embeddedDsid, sha256Hash } = await getFileIdentity(file, (hashed, total) => {
                    const pct = total === 0 ? 95 : Math.round((hashed / total) * 95);
                    const rawPct = total === 0 ? 100 : Math.round((hashed / total) * 100);
                    steps.updateStep1({
                        percent: pct,
                        detail: `Computing SHA-256 (${rawPct}%)...`,
                    });
                });

                steps.updateStep1({
                    percent: 95,
                    detail: 'Creating dataset record in Crucible...',
                });

                let targetEmbeddedDsid = embeddedDsid;
                let usedPendingDsid = false;
                if (!targetEmbeddedDsid && sha256Hash) {
                    const pendingDsid = getPendingDatasetMfid(currentUserState.selected_project, TOOL_CONFIG.key, sha256Hash);
                    if (pendingDsid) {
                        targetEmbeddedDsid = pendingDsid;
                        usedPendingDsid = true;
                    }
                }

                const dsName = datasetNameOverride ? `${datasetNameOverride}_${file.name}` : file.name;
                const createPayload = {
                    embedded_dsid: targetEmbeddedDsid,
                    sha256_hash: sha256Hash,
                    dataset_name: dsName,
                    session_name: sessionName || null,
                    comments,
                    keywords,
                    sample_unique_id: sampleUniqueId,
                };

                let dsRes;
                try {
                    dsRes = await api(`${TOOL_CONFIG.url_prefix}/api/create-dataset`, 'POST', createPayload);
                } catch (err) {
                    if (usedPendingDsid && (err.status === 403 || err.status === 404)) {
                        clearPendingDatasetMfid(currentUserState.selected_project, TOOL_CONFIG.key, sha256Hash);
                        createPayload.embedded_dsid = null;
                        dsRes = await api(`${TOOL_CONFIG.url_prefix}/api/create-dataset`, 'POST', createPayload);
                    } else {
                        throw err;
                    }
                }

                const datasetMfid = dsRes.dataset_mfid;
                if (sha256Hash && datasetMfid) {
                    setPendingDatasetMfid(currentUserState.selected_project, TOOL_CONFIG.key, sha256Hash, datasetMfid);
                }
                const step1Detail = dsRes.reused
                    ? `Dataset ${datasetMfid} (reused existing)`
                    : `Dataset ${datasetMfid} ready`;
                steps.updateStep1({
                    percent: 100,
                    detail: step1Detail,
                    isDone: true,
                });

                // Step 2/2: Uploading
                const existingSet = new Set(Array.isArray(dsRes.existing_filenames) ? dsRes.existing_filenames : []);
                const filesToSend = [file];
                const filesToUpload = dsRes.reused
                    ? filesToSend.filter(f => !existingSet.has(f.name))
                    : filesToSend;

                if (filesToUpload.length === 0) {
                    clearPendingDatasetMfid(currentUserState.selected_project, TOOL_CONFIG.key, sha256Hash);
                    steps.updateStep2({
                        percent: 100,
                        detail: 'Already uploaded (reused existing dataset)',
                        isDone: true,
                    });
                } else {
                    steps.updateStep2({
                        percent: 0,
                        detail: `Uploading ${file.name}...`,
                    });

                    const uploadResults = await window.CrucibleUpload.uploadFiles({
                        datasetMfid,
                        files: filesToUpload,
                        ingestion: () => ({
                            requested: Boolean(ingestor),
                            ...(ingestor ? { ingestionClass: ingestor } : {}),
                        }),
                        onProgress: (f, p) => {
                            const pct = f.size ? Math.min(100, Math.round(((p.uploadedBytes || 0) / f.size) * 100)) : 100;
                            steps.updateStep2({
                                percent: pct,
                                detail: `Uploading ${f.name} (${pct}%)...`,
                            });
                        },
                    });

                    if (!uploadResults[0]?.ok) {
                        throw new Error(uploadResults[0]?.error || `Failed uploading ${file.name}`);
                    }

                    clearPendingDatasetMfid(currentUserState.selected_project, TOOL_CONFIG.key, sha256Hash);

                    steps.updateStep2({
                        percent: 100,
                        detail: 'Upload complete',
                        isDone: true,
                    });
                }

                if (TOOL_CONFIG.post_processing && TOOL_CONFIG.post_processing.length > 0) {
                    steps.updateStep2({
                        percent: 100,
                        detail: `Requesting post-processing (${TOOL_CONFIG.post_processing.join(', ')})...`,
                        isDone: true,
                    });
                    await api(`${TOOL_CONFIG.url_prefix}/api/postprocess`, 'POST', {
                        dataset_id: datasetMfid,
                    });
                    steps.updateStep2({
                        percent: 100,
                        detail: `Post-processing requested (${TOOL_CONFIG.post_processing.join(', ')})`,
                        isDone: true,
                    });
                }

                results.push({ file: file.name, datasetMfid, hubUrl: dsRes.hub_url });
            }

            steps?.hideNotice?.();

            let resHtml = '<div class="alert alert-success" style="margin-top:10px;"><strong>Uploaded Datasets:</strong><ul style="margin:4px 0 0 16px;">';
            results.forEach(r => {
                const safeUrl = resolveSafeDatasetHubUrl(r.hubUrl, r.datasetMfid);
                const linkContent = safeUrl
                    ? `<a href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer"><code>${escapeHtml(r.datasetMfid)}</code></a>`
                    : `<code>${escapeHtml(r.datasetMfid)}</code>`;
                resHtml += `<li><code>${escapeHtml(r.file)}</code> &rarr; ${linkContent}</li>`;
            });
            resHtml += '</ul></div>';
            resultEl.innerHTML = resHtml;

            const firstSafeUrl = results.length === 1 ? resolveSafeDatasetHubUrl(results[0].hubUrl, results[0].datasetMfid) : '';
            showAlert(
                'success',
                `Uploaded ${results.length} datasets`,
                results.length === 1 && firstSafeUrl
                    ? { linkUrl: firstSafeUrl }
                    : { linkUrl: hubProjectUrl(currentUserState?.selected_project), linkText: 'Open Project in Crucible Hub \u2197' }
            );
        }

    } catch (e) {
        steps?.hideNotice?.();
        progressEl.innerHTML = `<div class="alert alert-error">Upload failed: ${escapeHtml(e.message)}</div>`;
        showAlert('error', `Upload failed: ${e.message}`);
    } finally {
        isStandardUploading = false;
        if (uploadBtn) uploadBtn.disabled = false;
    }
}

// ========== Logbook Functions ==========

async function loadRecentDatasets() {
    const tbody = document.getElementById('recent-table-body');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="7">Loading datasets...</td></tr>';
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
