// TEM session folder uploader client-side controller.

let TOOL_CONFIG = {};

const PREPARE_CHUNK_SIZE = 25;
const LARGE_ITEM_THRESHOLD_BYTES = 64 * 1024 * 1024; // 64 MiB
const MAX_CONCURRENCY_SLOTS = 2;

let currentPlan = null;
let activeSession = null;
let itemStates = new Map();
let isUploading = false;
let activeAbortController = null;
let isScanningFolder = false;

document.addEventListener('DOMContentLoaded', async () => {
    TOOL_CONFIG = readToolConfig();
    initUploaderSampleInput();
    initFolderControls();
    if (typeof registerLogoutReset === 'function') {
        registerLogoutReset(() => {
            clearSample();
            if (!isUploading) {
                activeSession = null;
                updateActionButtons();
            }
        });
    }
    await loadUserState();
    await populatePrinterSelect('printer-select');
});

window.addEventListener('beforeunload', (event) => {
    if (isUploading) {
        event.preventDefault();
        event.returnValue = '';
    }
});

// ========== Folder Picker & Drag-and-Drop ==========

function initFolderControls() {
    const folderInput = document.getElementById('session-folder-input');
    const dropzone = document.getElementById('session-dropzone');

    if (folderInput) {
        folderInput.addEventListener('change', () => {
            if (isUploading) return;
            const files = Array.from(folderInput.files || []);
            if (!files.length) return;
            if (!window.InstrumentParsers?.filesToSessionInputs) {
                showAlert('error', 'Session planner bundle failed to load. Please reload the page.');
                return;
            }
            const inputs = window.InstrumentParsers.filesToSessionInputs(files);
            applySessionInputs(inputs);
        });
    }

    if (dropzone) {
        const stopEvent = (e) => {
            e.preventDefault();
            e.stopPropagation();
        };

        dropzone.addEventListener('dragenter', (e) => {
            stopEvent(e);
            if (!isUploading && !isScanningFolder) {
                dropzone.classList.add('is-dragover');
            }
        });

        dropzone.addEventListener('dragover', (e) => {
            stopEvent(e);
            if (!isUploading && !isScanningFolder) {
                dropzone.classList.add('is-dragover');
            }
        });

        dropzone.addEventListener('dragleave', (e) => {
            stopEvent(e);
            if (!dropzone.contains(e.relatedTarget)) {
                dropzone.classList.remove('is-dragover');
            }
        });

        dropzone.addEventListener('drop', async (e) => {
            stopEvent(e);
            dropzone.classList.remove('is-dragover');
            if (isUploading || isScanningFolder) return;
            await handleFolderDrop(e.dataTransfer);
        });
    }
}

function readAllDirectoryEntries(dirEntry) {
    return new Promise((resolve, reject) => {
        const reader = dirEntry.createReader();
        const allEntries = [];
        function readBatch() {
            reader.readEntries(
                (entries) => {
                    if (!entries.length) {
                        resolve(allEntries);
                        return;
                    }
                    allEntries.push(...entries);
                    readBatch();
                },
                (err) => reject(err)
            );
        }
        readBatch();
    });
}

function fileEntryToFile(fileEntry) {
    return new Promise((resolve, reject) => {
        fileEntry.file(resolve, reject);
    });
}

async function collectEntryFiles(entry, prefixPath, out) {
    const currentPath = prefixPath ? `${prefixPath}/${entry.name}` : entry.name;
    if (entry.isFile) {
        const file = await fileEntryToFile(entry);
        out.push({ file, relativePath: currentPath });
        return;
    }
    if (entry.isDirectory) {
        const children = await readAllDirectoryEntries(entry);
        for (const child of children) {
            await collectEntryFiles(child, currentPath, out);
        }
    }
}

async function handleFolderDrop(dataTransfer) {
    if (!dataTransfer) return;

    const dtItems = Array.from(dataTransfer.items || []);
    const entries = dtItems
        .map((item) => (typeof item.webkitGetAsEntry === 'function' ? item.webkitGetAsEntry() : null))
        .filter(Boolean);

    if (!entries.length) {
        showAlert('warning', 'Drag-and-drop directory inspection is unavailable in this browser. Please use the folder picker button.');
        return;
    }

    if (entries.length !== 1 || !entries[0].isDirectory) {
        showAlert('warning', 'Please drop a single session folder (not individual files or multiple folders).');
        return;
    }

    const scanStatus = document.getElementById('session-scan-status');
    isScanningFolder = true;
    if (scanStatus) {
        scanStatus.textContent = `Scanning folder "${entries[0].name}"...`;
        scanStatus.classList.remove('hidden');
    }

    try {
        const inputs = [];
        await collectEntryFiles(entries[0], '', inputs);
        const folderInput = document.getElementById('session-folder-input');
        if (folderInput) folderInput.value = '';
        applySessionInputs(inputs);
    } catch (e) {
        showAlert('error', `Failed reading dropped folder: ${e.message || e}`);
    } finally {
        isScanningFolder = false;
        if (scanStatus) {
            scanStatus.textContent = '';
            scanStatus.classList.add('hidden');
        }
    }
}

function applySessionInputs(inputs) {
    if (!window.InstrumentParsers?.planTemSessionUploads) {
        showAlert('error', 'Session planner bundle failed to load. Please reload the page.');
        return;
    }

    const acceptable = Array.isArray(TOOL_CONFIG.acceptable_file_types) && TOOL_CONFIG.acceptable_file_types.length
        ? TOOL_CONFIG.acceptable_file_types
        : undefined;

    try {
        const plan = window.InstrumentParsers.planTemSessionUploads(inputs, {
            ...(acceptable ? { acceptableExtensions: acceptable } : {}),
        });
        currentPlan = plan;
        activeSession = null;
        itemStates = new Map();
        renderManifestCard(plan);
        resetProgressSection();
        updateActionButtons();
    } catch (e) {
        currentPlan = null;
        activeSession = null;
        itemStates = new Map();
        hideManifestCard();
        resetProgressSection();
        updateActionButtons();
        showAlert('warning', e.message || 'Could not plan session folder.');
    }
}

function clearSessionFolder() {
    if (isUploading) return;
    currentPlan = null;
    activeSession = null;
    itemStates = new Map();
    const folderInput = document.getElementById('session-folder-input');
    if (folderInput) folderInput.value = '';
    hideManifestCard();
    resetProgressSection();
    updateActionButtons();
}

function hideManifestCard() {
    document.getElementById('session-manifest-card')?.classList.add('hidden');
}

function renderManifestCard(plan) {
    const card = document.getElementById('session-manifest-card');
    if (!card) return;
    card.classList.remove('hidden');

    const instLabel = TOOL_CONFIG.name || TOOL_CONFIG.nav_label || TOOL_CONFIG.key || 'TEM';
    const titleEl = document.getElementById('manifest-session-title');
    if (titleEl) titleEl.textContent = `${instLabel} session: ${plan.folderName}`;

    document.getElementById('manifest-child-count').textContent = String(plan.items.length);
    document.getElementById('manifest-sidecar-count').textContent = String(plan.companionCount);
    document.getElementById('manifest-ignored-count').textContent = String(plan.ignoredCount);
    document.getElementById('manifest-total-size').textContent = formatBytes(plan.totalUploadBytes);

    const warningsEl = document.getElementById('session-manifest-warnings');
    if (!warningsEl) return;

    const warningBlocks = [];

    if (plan.items.length === 0) {
        warningBlocks.push(
            '<div class="session-warning-box"><strong>No uploadable TEM datasets found</strong> in this folder.</div>'
        );
    }

    if (plan.emptyFiles.length > 0) {
        warningBlocks.push(renderPathWarningBox(
            `${plan.emptyFiles.length} empty (0-byte) file(s) detected -- affected dataset(s) excluded from upload:`,
            plan.emptyFiles
        ));
    }

    if (plan.oversizedFiles.length > 0) {
        warningBlocks.push(renderPathWarningBox(
            `${plan.oversizedFiles.length} file(s) exceed the 500 GiB limit -- affected dataset(s) excluded from upload:`,
            plan.oversizedFiles
        ));
    }

    const itemsWithWarnings = plan.items.filter((item) => item.warning);
    if (itemsWithWarnings.length > 0) {
        warningBlocks.push(renderPathWarningBox(
            `${itemsWithWarnings.length} .ser file(s) are missing a paired .emi sidecar (non-blocking; they will still upload):`,
            itemsWithWarnings.map((item) => `${item.relativePath} (${item.warning})`)
        ));
    }

    if (warningBlocks.length > 0) {
        warningsEl.innerHTML = warningBlocks.join('');
        warningsEl.classList.remove('hidden');
    } else {
        warningsEl.innerHTML = '';
        warningsEl.classList.add('hidden');
    }
}

function renderPathWarningBox(heading, lines) {
    const maxShown = 10;
    const shown = lines.slice(0, maxShown).map((line) => `<li><code>${escapeHtml(line)}</code></li>`).join('');
    const remainder = lines.length > maxShown
        ? `<li>... and ${lines.length - maxShown} more</li>`
        : '';
    return `<div class="session-warning-box"><strong>${escapeHtml(heading)}</strong><ul>${shown}${remainder}</ul></div>`;
}

// ========== Upload Lifecycle & Existing-Session Modal ==========

function updateActionButtons() {
    const uploadBtn = document.getElementById('btn-session-upload');
    const cancelBtn = document.getElementById('btn-session-cancel');
    const retryBtn = document.getElementById('btn-session-retry');
    const clearBtn = document.getElementById('btn-session-clear');
    const dropzone = document.getElementById('session-dropzone');
    const folderInput = document.getElementById('session-folder-input');

    const hasItems = Boolean(currentPlan && currentPlan.items.length > 0);
    const failedOrCancelledCount = countItemsByStatus(['failed', 'cancelled']);

    if (uploadBtn) {
        uploadBtn.disabled = isUploading || !hasItems;
    }
    if (cancelBtn) {
        cancelBtn.classList.toggle('hidden', !isUploading);
        cancelBtn.disabled = !isUploading;
    }
    if (retryBtn) {
        const canRetry = !isUploading && Boolean(activeSession) && failedOrCancelledCount > 0;
        retryBtn.classList.toggle('hidden', !canRetry);
        retryBtn.disabled = !canRetry;
        if (canRetry) {
            retryBtn.textContent = `Retry Failed Items (${failedOrCancelledCount})`;
        }
    }
    if (clearBtn) {
        clearBtn.disabled = isUploading;
    }
    if (dropzone) {
        dropzone.classList.toggle('is-disabled', isUploading);
    }
    if (folderInput) {
        folderInput.disabled = isUploading;
    }
}

async function startSessionUpload() {
    if (isUploading) return;
    if (!currentUserState || !currentUserState.selected_project) {
        showAlert('warning', 'Please login and select a project first.');
        return;
    }
    if (!currentPlan || !currentPlan.items.length) {
        showAlert('warning', 'Please select a session folder with at least one valid TEM file.');
        return;
    }

    const uploadBtn = document.getElementById('btn-session-upload');
    if (uploadBtn) uploadBtn.disabled = true;

    try {
        const checkRes = await api(`${TOOL_CONFIG.url_prefix}/api/session/check`, 'POST', {
            folder_name: currentPlan.folderName,
        });
        const matches = Array.isArray(checkRes.matches) ? checkRes.matches : [];
        if (matches.length > 0) {
            if (uploadBtn) uploadBtn.disabled = false;
            showExistingSessionModal(checkRes, matches);
            return;
        }
        await executeSessionStartAndUpload(null);
    } catch (e) {
        showAlert('error', `Failed checking existing sessions: ${e.message}`);
        updateActionButtons();
    }
}

function safeHubUrl(url) {
    return typeof url === 'string' && /^(https?:\/\/|\/)/i.test(url) ? url : '';
}

function showExistingSessionModal(checkRes, matches) {
    let selectedSessionDsid = matches[0].unique_id;

    let html = `<p class="help-text">Found ${matches.length} existing session dataset(s) matching <strong>${escapeHtml(checkRes.session_dataset_name || currentPlan.folderName)}</strong> in this project.</p>`;
    html += '<div class="existing-session-list">';
    matches.forEach((match, idx) => {
        const checked = idx === 0 ? 'checked' : '';
        const timestamp = match.modification_time || match.creation_time || '';
        const hubUrl = safeHubUrl(match.hub_url || hubDatasetUrl(match.unique_id));
        html += `<label class="existing-session-option">
            <input type="radio" name="existing-session-choice" value="${escapeHtml(match.unique_id)}" ${checked}
                onchange="window._setSelectedExistingSession(this.value)">
            <div style="flex:1; min-width:0;">
                <div style="font-weight:600; color:#1a365d; word-break:break-word;">${escapeHtml(match.dataset_name || match.unique_id)}</div>
                <div style="font-size:12px; color:#4a5568; margin-top:2px;">
                    <code>${escapeHtml(match.unique_id)}</code>
                    ${timestamp ? ` - ${escapeHtml(timestamp)}` : ''}
                    ${hubUrl ? ` - <a href="${escapeHtml(hubUrl)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">Open in Hub &#8599;</a>` : ''}
                </div>
            </div>
        </label>`;
    });
    html += '</div>';

    window._setSelectedExistingSession = (dsid) => {
        selectedSessionDsid = dsid;
    };

    showModal(
        'Existing Session Found',
        html,
        () => {
            const checkedEl = document.querySelector('input[name="existing-session-choice"]:checked');
            const chosen = checkedEl ? checkedEl.value : selectedSessionDsid;
            executeSessionStartAndUpload(chosen || matches[0].unique_id);
        },
        'Resume / Append to Existing Session',
        {
            label: 'Create New Session',
            onClick: () => {
                executeSessionStartAndUpload(null);
            },
        }
    );
}

async function executeSessionStartAndUpload(existingSessionDsid) {
    if (isUploading || !currentPlan) return;

    const sampleUniqueId = getSelectedSampleUniqueId();
    const comments = document.getElementById('session-comments')?.value.trim() || '';
    const rawKeywords = document.getElementById('session-keywords')?.value || '';
    const keywords = rawKeywords.split(',').map((s) => s.trim()).filter(Boolean);
    const ingestor = document.getElementById('session-ingestor')?.value.trim() || TOOL_CONFIG.ingestor || '';

    activeSession = null;
    isUploading = true;
    activeAbortController = new AbortController();
    updateActionButtons();

    try {
        showAlert('info', existingSessionDsid ? 'Resuming existing session...' : 'Creating session parent dataset...');
        const startRes = await api(`${TOOL_CONFIG.url_prefix}/api/session/start`, 'POST', {
            folder_name: currentPlan.folderName,
            existing_session_dsid: existingSessionDsid || null,
            sample_unique_id: sampleUniqueId,
            comments,
            keywords,
        });

        activeSession = {
            sessionDsid: startRes.session_dsid,
            sessionName: startRes.session_name || currentPlan.folderName,
            datasetName: startRes.dataset_name || `${TOOL_CONFIG.name || TOOL_CONFIG.key} session: ${currentPlan.folderName}`,
            reused: Boolean(startRes.reused),
            hubUrl: safeHubUrl(startRes.hub_url || hubDatasetUrl(startRes.session_dsid)),
            sampleUniqueId,
            comments,
            keywords,
            ingestor,
        };

        initializeProgressTable(currentPlan.items);
        renderParentSessionBanner(activeSession);

        if (activeAbortController.signal.aborted) {
            markRemainingCancelled(currentPlan.items);
            return;
        }

        await runChildUploadPipeline(currentPlan.items, activeAbortController.signal);
    } catch (e) {
        showAlert('error', `Failed starting session upload: ${e.message}`);
    } finally {
        finishUploadRun();
    }
}

async function retryFailedSessionItems() {
    if (isUploading || !currentPlan || !activeSession) return;

    const retryItems = currentPlan.items.filter((item) => {
        const state = itemStates.get(item.clientId);
        return state && (state.status === 'failed' || state.status === 'cancelled');
    });

    if (!retryItems.length) {
        showAlert('info', 'There are no failed or cancelled items to retry.');
        return;
    }

    // Allow operator to adjust ingestor override before retrying if desired.
    const latestIngestor = document.getElementById('session-ingestor')?.value.trim();
    if (latestIngestor !== undefined) {
        activeSession.ingestor = latestIngestor || TOOL_CONFIG.ingestor || '';
    }

    for (const item of retryItems) {
        const prev = itemStates.get(item.clientId) || {};
        setItemState(item.clientId, {
            ...prev,
            status: 'queued',
            phase: null,
            percent: 0,
            error: null,
        });
    }

    isUploading = true;
    activeAbortController = new AbortController();
    updateActionButtons();
    showAlert('info', `Retrying ${retryItems.length} item(s) in session ${activeSession.sessionDsid}...`);

    try {
        await runChildUploadPipeline(retryItems, activeAbortController.signal);
    } catch (e) {
        showAlert('error', `Retry failed: ${e.message}`);
    } finally {
        finishUploadRun();
    }
}

function cancelSessionUpload() {
    if (!isUploading || !activeAbortController) return;
    activeAbortController.abort();
    for (const [clientId, state] of itemStates.entries()) {
        if (state.status === 'queued' || state.status === 'hashing' || state.status === 'preparing') {
            setItemState(clientId, {
                ...state,
                status: 'cancelled',
                error: null,
            });
        }
    }
    showAlert('warning', 'Cancelling active uploads...');
}

function finishUploadRun() {
    isUploading = false;
    activeAbortController = null;
    updateOverallProgress();
    updateActionButtons();

    if (!activeSession || !currentPlan) return;

    const completed = countItemsByStatus(['completed']);
    const failed = countItemsByStatus(['failed']);
    const cancelled = countItemsByStatus(['cancelled']);
    const total = currentPlan.items.length;

    const alertOpts = {
        linkUrl: activeSession.hubUrl,
        linkText: 'Open Session in Crucible Hub \u2197',
    };

    if (failed === 0 && cancelled === 0 && completed === total) {
        showAlert('success', `Session upload complete (${completed}/${total} child datasets).`, alertOpts);
    } else if (failed === 0 && cancelled > 0) {
        showAlert(
            'warning',
            `Session upload cancelled (${completed}/${total} completed, ${cancelled} cancelled). Use Retry Failed Items to resume.`,
            alertOpts
        );
    } else if (failed > 0) {
        showAlert(
            'warning',
            `Session upload finished with errors (${completed}/${total} completed, ${failed} failed${cancelled ? `, ${cancelled} cancelled` : ''}). Use Retry Failed Items to resume.`,
            alertOpts
        );
    }
}

// ========== Chunked Prepare & Concurrency-Capped Upload Engine ==========

function isHeavySessionItem(item) {
    return item.companionFiles.length > 0 || item.totalBytes >= LARGE_ITEM_THRESHOLD_BYTES;
}

async function runWithSessionConcurrency(items, workerFn, signal) {
    let cursor = 0;
    let usedSlots = 0;
    let activeCount = 0;

    return new Promise((resolve) => {
        const launchNext = () => {
            if (signal.aborted) {
                while (cursor < items.length) {
                    const skipped = items[cursor++];
                    const st = itemStates.get(skipped.clientId);
                    if (st && st.status !== 'completed' && st.status !== 'failed') {
                        setItemState(skipped.clientId, { ...st, status: 'cancelled', error: null });
                    }
                }
                if (activeCount === 0) resolve();
                return;
            }

            while (cursor < items.length) {
                const candidate = items[cursor];
                const neededSlots = isHeavySessionItem(candidate) ? MAX_CONCURRENCY_SLOTS : 1;
                if (usedSlots + neededSlots > MAX_CONCURRENCY_SLOTS) {
                    break;
                }
                cursor += 1;
                usedSlots += neededSlots;
                activeCount += 1;

                Promise.resolve()
                    .then(() => workerFn(candidate))
                    .finally(() => {
                        usedSlots -= neededSlots;
                        activeCount -= 1;
                        launchNext();
                    });
            }

            if (cursor >= items.length && activeCount === 0) {
                resolve();
            }
        };

        launchNext();
    });
}

async function runChildUploadPipeline(itemsToProcess, signal) {
    for (let offset = 0; offset < itemsToProcess.length; offset += PREPARE_CHUNK_SIZE) {
        if (signal.aborted) {
            markRemainingCancelled(itemsToProcess.slice(offset));
            break;
        }

        const chunk = itemsToProcess.slice(offset, offset + PREPARE_CHUNK_SIZE);

        // Reuse existing datasetMfid on retry so unhashed items never create duplicates.
        const needPrepare = chunk.filter((item) => !itemStates.get(item.clientId)?.datasetMfid);

        if (needPrepare.length > 0) {
            const preparedPayloadItems = [];

            for (const item of needPrepare) {
                if (signal.aborted) break;

                let sha256Hash = null;
                if (activeSession?.reused && window.InstrumentParsers?.computeBlobSha256) {
                    setItemState(item.clientId, {
                        ...(itemStates.get(item.clientId) || {}),
                        status: 'hashing',
                        percent: 0,
                        error: null,
                    });
                    try {
                        sha256Hash = await window.InstrumentParsers.computeBlobSha256(
                            item.primaryFile,
                            (hashedBytes, totalBytes) => {
                                if (signal.aborted) return;
                                const pct = totalBytes > 0
                                    ? Math.min(100, Math.round((hashedBytes / totalBytes) * 100))
                                    : 100;
                                setItemState(item.clientId, {
                                    ...(itemStates.get(item.clientId) || {}),
                                    status: 'hashing',
                                    percent: pct,
                                    error: null,
                                });
                            },
                            signal
                        );
                    } catch (e) {
                        if (signal.aborted) {
                            break;
                        }
                        console.warn(`Could not pre-hash ${item.relativePath}:`, e);
                    }
                }

                if (signal.aborted) break;

                preparedPayloadItems.push({
                    client_id: item.clientId,
                    dataset_name: item.datasetName,
                    sha256_hash: sha256Hash,
                    data_format: item.dataFormat,
                });
            }

            if (signal.aborted) {
                markRemainingCancelled(itemsToProcess.slice(offset));
                break;
            }

            for (const item of needPrepare) {
                setItemState(item.clientId, {
                    ...(itemStates.get(item.clientId) || {}),
                    status: 'preparing',
                    error: null,
                });
            }

            try {
                const excludeDsids = Array.from(itemStates.values()).map((s) => s?.datasetMfid).filter(Boolean);
                const prepRes = await api(`${TOOL_CONFIG.url_prefix}/api/session/prepare-children`, 'POST', {
                    session_dsid: activeSession.sessionDsid,
                    session_name: activeSession.sessionName,
                    sample_unique_id: activeSession.sampleUniqueId,
                    comments: activeSession.comments,
                    keywords: activeSession.keywords,
                    items: preparedPayloadItems,
                    exclude_dsids: excludeDsids,
                });

                const byClientId = new Map();
                for (const child of prepRes.children || []) {
                    byClientId.set(child.client_id, child);
                }

                for (const item of needPrepare) {
                    const child = byClientId.get(item.clientId);
                    if (!child || !child.dataset_mfid) {
                        setItemState(item.clientId, {
                            ...(itemStates.get(item.clientId) || {}),
                            status: 'failed',
                            error: 'Backend did not return a dataset MFID for this item.',
                        });
                    } else {
                        const prev = itemStates.get(item.clientId) || {};
                        const uploadedFilenames = new Set(prev.uploadedFilenames || []);
                        if (Array.isArray(child.existing_filenames)) {
                            for (const fname of child.existing_filenames) {
                                if (typeof fname === 'string' && fname) {
                                    uploadedFilenames.add(fname);
                                }
                            }
                        }
                        setItemState(item.clientId, {
                            ...prev,
                            status: 'queued',
                            datasetMfid: child.dataset_mfid,
                            reused: Boolean(child.reused),
                            hubUrl: safeHubUrl(child.hub_url || hubDatasetUrl(child.dataset_mfid)),
                            uploadedFilenames,
                            error: null,
                        });
                    }
                }
            } catch (e) {
                if (signal.aborted) {
                    markRemainingCancelled(itemsToProcess.slice(offset));
                    break;
                }
                for (const item of needPrepare) {
                    setItemState(item.clientId, {
                        ...(itemStates.get(item.clientId) || {}),
                        status: 'failed',
                        error: `Prepare failed: ${e.message}`,
                    });
                }
                continue;
            }
        }

        const readyToUpload = chunk.filter((item) => {
            const st = itemStates.get(item.clientId);
            return st && st.datasetMfid && st.status !== 'failed' && st.status !== 'completed';
        });

        await runWithSessionConcurrency(
            readyToUpload,
            (item) => uploadSingleChildItem(item, signal),
            signal
        );
    }
}

function markRemainingCancelled(items) {
    for (const item of items) {
        const st = itemStates.get(item.clientId);
        if (st && st.status !== 'completed' && st.status !== 'failed') {
            setItemState(item.clientId, { ...st, status: 'cancelled', error: null });
        }
    }
}

async function uploadSingleChildItem(item, signal) {
    const state = itemStates.get(item.clientId);
    if (!state || !state.datasetMfid) return;

    if (signal.aborted) {
        setItemState(item.clientId, { ...state, status: 'cancelled', error: null });
        return;
    }

    const uploadedFilenames = new Set(state.uploadedFilenames || []);
    const fileUploaded = new Map();

    // Pre-credit already-uploaded files (from resumed sessions or prior retry attempts).
    for (const compFile of item.companionFiles) {
        if (uploadedFilenames.has(compFile.name)) {
            fileUploaded.set(compFile, compFile.size);
        }
    }
    if (uploadedFilenames.has(item.primaryFile.name)) {
        fileUploaded.set(item.primaryFile, item.primaryFile.size);
    }

    const calcPct = () => {
        if (!item.totalBytes) return 100;
        let uploaded = 0;
        for (const bytes of fileUploaded.values()) {
            uploaded += bytes;
        }
        return Math.min(100, Math.round((uploaded / item.totalBytes) * 100));
    };

    try {
        // CRITICAL: Upload companion sidecars FIRST without triggering ingestion, so .emi / .rawtlt / .txt
        // are stored in GCS before server-side ingestion runs on the primary .ser or .mrc file.
        const pendingCompanions = item.companionFiles.filter(
            (compFile) => !uploadedFilenames.has(compFile.name)
        );
        if (pendingCompanions.length > 0) {
            setItemState(item.clientId, {
                ...itemStates.get(item.clientId),
                status: 'uploading',
                phase: 'sidecars',
                percent: calcPct(),
                uploadedFilenames,
                error: null,
            });

            const companionResults = await window.CrucibleUpload.uploadFiles({
                datasetMfid: state.datasetMfid,
                files: pendingCompanions,
                signal,
                onProgress: (file, progress) => {
                    fileUploaded.set(file, Math.min(file.size, progress.uploadedBytes));
                    setItemState(item.clientId, {
                        ...itemStates.get(item.clientId),
                        status: 'uploading',
                        phase: 'sidecars',
                        percent: calcPct(),
                        uploadedFilenames,
                    });
                },
            });

            // Record every succeeded sidecar before checking failures so retries skip them.
            for (const res of companionResults) {
                if (res.ok) {
                    uploadedFilenames.add(res.file.name);
                    fileUploaded.set(res.file, res.file.size);
                }
            }
            setItemState(item.clientId, {
                ...itemStates.get(item.clientId),
                uploadedFilenames,
            });

            const failedCompanions = companionResults.filter((r) => !r.ok);
            if (failedCompanions.length > 0) {
                const detail = failedCompanions.map((r) => `${r.file.name}: ${r.error}`).join('; ');
                throw new Error(`Sidecar upload failed (${detail})`);
            }
        }

        if (signal.aborted) {
            setItemState(item.clientId, {
                ...itemStates.get(item.clientId),
                status: 'cancelled',
                uploadedFilenames,
                error: null,
            });
            return;
        }

        if (!uploadedFilenames.has(item.primaryFile.name)) {
            setItemState(item.clientId, {
                ...itemStates.get(item.clientId),
                status: 'uploading',
                phase: 'primary',
                percent: calcPct(),
                uploadedFilenames,
                error: null,
            });

            const ingestor = activeSession.ingestor;
            const primaryResults = await window.CrucibleUpload.uploadFiles({
                datasetMfid: state.datasetMfid,
                files: [item.primaryFile],
                ingestion: () => ({
                    requested: true,
                    ...(ingestor ? { ingestionClass: ingestor } : {}),
                }),
                signal,
                onProgress: (file, progress) => {
                    fileUploaded.set(file, Math.min(file.size, progress.uploadedBytes));
                    setItemState(item.clientId, {
                        ...itemStates.get(item.clientId),
                        status: 'uploading',
                        phase: 'primary',
                        percent: calcPct(),
                        uploadedFilenames,
                    });
                },
            });

            const primaryRes = primaryResults[0];
            if (!primaryRes || !primaryRes.ok) {
                throw new Error(primaryRes?.error || `Failed uploading ${item.primaryFile.name}`);
            }

            // Record primary file completion even if ingestion failed so retries do not hit HTTP 409.
            uploadedFilenames.add(item.primaryFile.name);
            fileUploaded.set(item.primaryFile, item.primaryFile.size);
            setItemState(item.clientId, {
                ...itemStates.get(item.clientId),
                uploadedFilenames,
            });

            if (primaryRes.ingestionError) {
                throw new Error(`Uploaded file, but ingestion failed: ${primaryRes.ingestionError}`);
            }
        }

        setItemState(item.clientId, {
            ...itemStates.get(item.clientId),
            status: 'completed',
            phase: null,
            percent: 100,
            uploadedFilenames,
            error: null,
        });
    } catch (e) {
        if (signal.aborted || e?.name === 'AbortError' || e?.name === 'CanceledError') {
            setItemState(item.clientId, {
                ...itemStates.get(item.clientId),
                status: 'cancelled',
                phase: null,
                uploadedFilenames,
                error: null,
            });
            return;
        }
        setItemState(item.clientId, {
            ...itemStates.get(item.clientId),
            status: 'failed',
            phase: null,
            uploadedFilenames,
            error: e?.message || String(e),
        });
    }
}

// ========== Progress UI Rendering ==========

function resetProgressSection() {
    const section = document.getElementById('section-session-progress');
    if (section) section.classList.add('hidden');
    const banner = document.getElementById('session-parent-banner');
    if (banner) {
        banner.innerHTML = '';
        banner.classList.add('hidden');
    }
    const summary = document.getElementById('session-overall-summary');
    if (summary) summary.textContent = '';
    const fill = document.getElementById('session-overall-bar-fill');
    if (fill) fill.style.width = '0%';
    const tbody = document.getElementById('session-items-tbody');
    if (tbody) tbody.innerHTML = '';
}

function renderParentSessionBanner(sessionInfo) {
    const section = document.getElementById('section-session-progress');
    if (section) section.classList.remove('hidden');

    const banner = document.getElementById('session-parent-banner');
    if (!banner) return;

    const modeBadge = sessionInfo.reused ? 'Resumed Existing Session' : 'Created New Session';
    const safeUrl = safeHubUrl(sessionInfo.hubUrl);
    const linkHtml = safeUrl
        ? `<a href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer" class="btn btn-primary">
            Open Session in Crucible Hub &#8599;
        </a>`
        : '';
    banner.innerHTML = `
        <div>
            <div style="font-weight:700; color:#22543d;">${escapeHtml(sessionInfo.datasetName)}</div>
            <div style="font-size:13px; color:#2f855a; margin-top:2px;">
                ${escapeHtml(modeBadge)} &middot; Parent Session MFID: <code>${escapeHtml(sessionInfo.sessionDsid)}</code>
            </div>
        </div>
        ${linkHtml}
    `;
    banner.classList.remove('hidden');
}

function initializeProgressTable(items) {
    const section = document.getElementById('section-session-progress');
    if (section) section.classList.remove('hidden');

    const tbody = document.getElementById('session-items-tbody');
    if (!tbody) return;

    itemStates = new Map();
    const rowsHtml = [];

    for (const item of items) {
        itemStates.set(item.clientId, {
            status: 'queued',
            phase: null,
            percent: 0,
            datasetMfid: null,
            hubUrl: null,
            reused: false,
            uploadedFilenames: new Set(),
            error: null,
        });

        const sidecarText = item.companionFiles.length
            ? item.companionFiles.map((f) => `<code>${escapeHtml(f.name)}</code>`).join(', ')
            : '<span class="help-text" style="margin:0;">-</span>';
        const warningHtml = item.warning
            ? `<span class="session-item-warn">${escapeHtml(item.warning)}</span>`
            : '';

        rowsHtml.push(`
            <tr data-client-id="${escapeHtml(item.clientId)}">
                <td class="session-item-path">
                    <strong>${escapeHtml(item.datasetName)}</strong>
                    <div style="font-size:11px; color:#718096;">${escapeHtml(item.relativePath)}</div>
                    ${warningHtml}
                </td>
                <td>${sidecarText}</td>
                <td>${escapeHtml(formatBytes(item.totalBytes))}</td>
                <td data-col="status"><span class="status-badge status-queued">Queued</span></td>
                <td data-col="dataset"><span class="help-text" style="margin:0;">-</span></td>
            </tr>
        `);
    }

    tbody.innerHTML = rowsHtml.join('');
    updateOverallProgress();
}

function setItemState(clientId, nextState) {
    itemStates.set(clientId, nextState);
    updateItemRow(clientId, nextState);
    updateOverallProgress();
}

function updateItemRow(clientId, state) {
    const escapedId = (typeof CSS !== 'undefined' && typeof CSS.escape === 'function') ? CSS.escape(clientId) : clientId;
    const row = document.querySelector(`#session-items-tbody tr[data-client-id="${escapedId}"]`);
    if (!row) return;

    const statusCell = row.querySelector('[data-col="status"]');
    if (statusCell) {
        let label = 'Queued';
        let badgeClass = 'status-queued';

        if (state.status === 'hashing') {
            label = typeof state.percent === 'number' ? `Hashing ${state.percent}%` : 'Hashing';
            badgeClass = 'status-hashing';
        } else if (state.status === 'preparing') {
            label = 'Preparing';
            badgeClass = 'status-preparing';
        } else if (state.status === 'uploading') {
            const pct = typeof state.percent === 'number' ? state.percent : 0;
            label = state.phase === 'sidecars' ? `Sidecars ${pct}%` : `Uploading ${pct}%`;
            badgeClass = 'status-uploading';
        } else if (state.status === 'completed') {
            label = state.reused ? 'Completed (reused)' : 'Completed';
            badgeClass = 'status-completed';
        } else if (state.status === 'failed') {
            label = 'Failed';
            badgeClass = 'status-failed';
        } else if (state.status === 'cancelled') {
            label = 'Cancelled';
            badgeClass = 'status-cancelled';
        }

        const errorHtml = state.error
            ? `<span class="session-item-error">${escapeHtml(state.error)}</span>`
            : '';
        statusCell.innerHTML = `<span class="status-badge ${badgeClass}">${escapeHtml(label)}</span>${errorHtml}`;
    }

    const datasetCell = row.querySelector('[data-col="dataset"]');
    if (datasetCell && state.datasetMfid) {
        const link = safeHubUrl(state.hubUrl || hubDatasetUrl(state.datasetMfid));
        datasetCell.innerHTML = link
            ? `<a href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer"><code>${escapeHtml(state.datasetMfid)}</code> &#8599;</a>`
            : `<code>${escapeHtml(state.datasetMfid)}</code>`;
    }
}

function countItemsByStatus(statuses) {
    const set = new Set(statuses);
    let count = 0;
    for (const state of itemStates.values()) {
        if (set.has(state.status)) count += 1;
    }
    return count;
}

function updateOverallProgress() {
    const total = currentPlan ? currentPlan.items.length : 0;
    if (!total) return;

    const completed = countItemsByStatus(['completed']);
    const failed = countItemsByStatus(['failed']);
    const cancelled = countItemsByStatus(['cancelled']);
    const active = countItemsByStatus(['hashing', 'preparing', 'uploading']);

    const summaryEl = document.getElementById('session-overall-summary');
    if (summaryEl) {
        const parts = [`Completed: ${completed} / ${total}`];
        if (active) parts.push(`Active: ${active}`);
        if (failed) parts.push(`Failed: ${failed}`);
        if (cancelled) parts.push(`Cancelled: ${cancelled}`);
        summaryEl.textContent = parts.join('  |  ');
    }

    const fillEl = document.getElementById('session-overall-bar-fill');
    if (fillEl) {
        const pct = Math.round(((completed + failed + cancelled) / total) * 100);
        fillEl.style.width = `${pct}%`;
        fillEl.style.background = failed > 0 ? '#c53030' : completed === total ? '#2f855a' : '#2b6cb0';
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
