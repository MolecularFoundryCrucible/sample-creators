// B30 GC-EC preview and upload script.

let currentPrimarySample = null;
let currentPreviewPacket = null;
let currentPreviewPrepareData = null;

document.addEventListener('DOMContentLoaded', async () => {
    await loadUserState();
    await populatePrinterSelect('printer-select');
});

// ========== Primary Sample Handling ==========

async function lookupPrimarySample() {
    const val = document.getElementById('sample_barcode').value.trim();
    const status = document.getElementById('sample-status');
    if (!val) {
        status.textContent = 'Enter a barcode or sample name';
        return;
    }
    status.textContent = 'Looking up…';
    try {
        const res = await api('/b30-gc-ec/api/lookup-sample', 'POST', {
            sample_unique_id: val,
            sample_name: val,
        });
        currentPrimarySample = res;
        status.textContent = `✓ Found: ${res.sample_name} (${res.unique_id})`;
        populatePrimarySampleFields(res);
        showPrimarySamplePanel('found');
    } catch (e) {
        if (e.status === 409 && e.data?.candidates) {
            showAmbiguousSampleModal(e.data.candidates, (selected) => {
                currentPrimarySample = selected;
                document.getElementById('sample_barcode').value = selected.unique_id;
                status.textContent = `✓ Selected: ${selected.sample_name} (${selected.unique_id})`;
                populatePrimarySampleFields(selected);
                showPrimarySamplePanel('found');
            });
            status.textContent = 'Multiple candidates found — select from popup.';
            return;
        }
        currentPrimarySample = null;
        status.textContent = 'Sample not found. Fill details below to create.';
        showPrimarySamplePanel('create');
    }
}

function clearPrimarySample() {
    currentPrimarySample = null;
    document.getElementById('sample_barcode').value = '';
    document.getElementById('sample_name').value = '';
    document.getElementById('sample_type').value = '';
    document.getElementById('sample_description').value = '';
    document.getElementById('sample-status').textContent = '';
    showPrimarySamplePanel('hidden');
}

function populatePrimarySampleFields(sample) {
    document.getElementById('sample_name').value = sample.sample_name || '';
    document.getElementById('sample_name_text').textContent = sample.sample_name || '';
    document.getElementById('sample_type').value = sample.sample_type || '';
    document.getElementById('sample_type_text').textContent = sample.sample_type || '';
    document.getElementById('sample_description').value = sample.description || '';
    document.getElementById('sample_description_text').textContent = sample.description || '';
}

function showPrimarySamplePanel(mode) {
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

async function createPrimarySample() {
    const name = document.getElementById('sample_name').value.trim();
    const type = document.getElementById('sample_type').value.trim();
    const desc = document.getElementById('sample_description').value.trim();
    if (!name || !type) {
        showAlert('warning', 'Sample Name and Type are required');
        return;
    }
    try {
        const res = await api('/b30-gc-ec/api/create-sample', 'POST', {
            sample_name: name,
            sample_type: type,
            description: desc,
        });
        currentPrimarySample = res;
        document.getElementById('sample_barcode').value = res.unique_id;
        document.getElementById('sample-status').textContent = `✓ Created: ${res.sample_name} (${res.unique_id})`;
        populatePrimarySampleFields(res);
        showPrimarySamplePanel('found');
        showAlert('success', `Created sample ${res.sample_name}`);
    } catch (e) {
        showAlert('error', `Sample creation failed: ${e.message}`);
    }
}

async function printPrimarySampleBarcode() {
    const printer = document.getElementById('printer-select').value;
    if (!printer) {
        showAlert('warning', 'Please select a printer');
        return;
    }
    const sampleId = currentPrimarySample?.unique_id || document.getElementById('sample_barcode').value.trim();
    const sampleName = currentPrimarySample?.sample_name || '';
    if (!sampleId) {
        showAlert('warning', 'No sample to print');
        return;
    }
    try {
        await api('/b30-gc-ec/api/print-barcode', 'POST', {
            printer_id: printer,
            sample_id: sampleId,
            sample_name: sampleName,
        });
        showAlert('success', `Print job sent to ${printer}`);
    } catch (e) {
        showAlert('error', `Print failed: ${e.message}`);
    }
}

// ========== Required Material Samples Handling ==========

function gcMaterialChanged(kind) {
    const nameEl = document.getElementById(`gc-${kind}-name`);
    if (nameEl) {
        nameEl.textContent = 'Not looked up';
        nameEl.style.color = '#718096';
    }
}

async function gcLookupMaterial(kind) {
    const input = document.getElementById(`gc-${kind}-mfid`);
    const nameEl = document.getElementById(`gc-${kind}-name`);
    const val = input.value.trim();
    if (!val) return;
    if (!currentUserState?.selected_project) {
        showAlert('warning', 'Please select a project first.');
        return;
    }
    nameEl.textContent = 'Looking up…';
    nameEl.style.color = '#4a5568';
    try {
        const res = await api('/b30-gc-ec/api/lookup-sample', 'POST', {
            sample_unique_id: val,
        });
        input.value = res.unique_id;
        nameEl.textContent = `✓ ${res.sample_name}`;
        nameEl.style.color = '#22543d';
    } catch (e) {
        nameEl.textContent = `Lookup failed: ${e.message}`;
        nameEl.style.color = '#9b2c2c';
    }
}

// ========== Preview & Upload Flow ==========

async function startPreviewAndUpload() {
    if (!currentUserState || !currentUserState.selected_project) {
        showAlert('warning', 'Please login and select a project first.');
        return;
    }
    const fileInput = document.getElementById('gc-files');
    const files = Array.from(fileInput.files || []);
    if (!files.length) {
        showAlert('warning', 'Please select at least one file to upload.');
        return;
    }

    const anodeMfid = document.getElementById('gc-anode-mfid').value.trim();
    const cathodeMfid = document.getElementById('gc-cathode-mfid').value.trim();
    const electrolyteMfid = document.getElementById('gc-electrolyte-mfid').value.trim();

    if (!anodeMfid || !cathodeMfid || !electrolyteMfid) {
        showAlert('warning', 'All three material sample MFIDs (Anode, Cathode, Electrolyte) are required.');
        return;
    }

    const requestedIngestor = document.getElementById('gc-ingestor').value;
    const comments = document.getElementById('gc-comments').value.trim();
    const rawKeywords = document.getElementById('gc-keywords').value;
    const keywords = rawKeywords.split(',').map(s => s.trim()).filter(Boolean);

    showAlert('info', 'Reading files and generating preview…');

    try {
        // 1. Hash first file for dataset reuse check
        const firstSha = await window.InstrumentParsers.computeBlobSha256(files[0]);

        // 2. Parse files locally
        const parseRes = await window.InstrumentParsers.parseFilesForPreview(files, requestedIngestor);
        const { packet, collisions, per_file, skipped } = parseRes;

        // 3. Prepare preview on backend (read-only)
        const prepareRes = await api('/b30-gc-ec/api/prepare-preview', 'POST', {
            first_file_sha256: firstSha,
            anode_sample_mfid: anodeMfid,
            cathode_sample_mfid: cathodeMfid,
            electrolyte_sample_mfid: electrolyteMfid,
        });

        // 4. Merge resolved materials, comments, keywords into packet
        packet.scientific_metadata.anode_material = prepareRes.resolved_materials.anode_material;
        packet.scientific_metadata.cathode_material = prepareRes.resolved_materials.cathode_material;
        packet.scientific_metadata.electrolyte = prepareRes.resolved_materials.electrolyte;
        if (comments) {
            packet.scientific_metadata.comments = comments;
        }
        if (keywords.length) {
            packet.keywords = Array.from(new Set([...(packet.keywords || []), ...keywords]));
        }

        currentPreviewPacket = packet;
        currentPreviewPrepareData = prepareRes;

        // 5. Open rich Preview Modal
        renderPreviewModal({
            packet,
            collisions,
            per_file,
            skipped,
            prepareRes,
            files,
            anodeMfid,
            cathodeMfid,
            electrolyteMfid,
            requestedIngestor,
        });

    } catch (e) {
        showAlert('error', `Preview generation failed: ${e.message}`);
    }
}

function renderPreviewModal(opts) {
    const { packet, collisions, per_file, skipped, prepareRes, files, anodeMfid, cathodeMfid, electrolyteMfid, requestedIngestor } = opts;

    const datasetDescriptors = window.InstrumentParsers.buildDatasetFormDescriptor(packet.dataset_fields);
    const metadataDescriptors = window.InstrumentParsers.buildFormDescriptor(packet.scientific_metadata);
    const otherFields = window.InstrumentParsers.otherDatasetFields(packet.dataset_fields);

    let html = '<div class="preview-container" style="font-size:13px;">';

    // Status badge
    html += '<div style="margin-bottom:12px;">';
    if (prepareRes.reused_dataset) {
        html += `<span style="background:#feebc8; color:#744210; border:1px solid #ecc94b; padding:4px 10px; border-radius:4px; font-weight:600;">
            Will update existing dataset: ${escapeHtml(prepareRes.dsid)}
        </span>`;
    } else {
        html += `<span style="background:#bee3f8; color:#2a4365; border:1px solid #90cdf4; padding:4px 10px; border-radius:4px; font-weight:600;">
            New dataset will be created on confirm
        </span>`;
    }
    html += '</div>';

    // Per-file parser summary
    html += '<div style="margin-bottom:12px; background:#edf2f7; padding:8px 12px; border-radius:4px;">';
    html += '<strong>Files &amp; Ingestors:</strong><ul style="margin:4px 0 0 16px; padding:0;">';
    per_file.forEach(pf => {
        html += `<li><code>${escapeHtml(pf.file)}</code> &rarr; <em>${escapeHtml(pf.ingestion_class || 'auto')}</em></li>`;
    });
    html += '</ul></div>';

    // Skipped warning
    if (skipped && skipped.length) {
        html += `<div class="alert alert-warning" style="margin-bottom:12px;">
            <strong>Warning:</strong> ${skipped.length} file(s) could not be parsed: ${escapeHtml(skipped.join(', '))}
        </div>`;
    }

    // Collisions table
    if (collisions && collisions.length) {
        html += '<div style="margin-bottom:12px; border:1px solid #fed7d7; background:#fff5f5; padding:8px; border-radius:4px;">';
        html += '<strong style="color:#9b2c2c;">Metadata Collisions:</strong>';
        html += '<table class="preview-table" style="width:100%; margin-top:4px;">';
        html += '<thead><tr><th>Field</th><th>Kept</th><th>Discarded</th><th>File</th></tr></thead><tbody>';
        collisions.forEach(c => {
            html += `<tr>
                <td><code>${escapeHtml(c.field)}</code></td>
                <td>${escapeHtml(String(c.kept))}</td>
                <td>${escapeHtml(String(c.discarded))}</td>
                <td>${escapeHtml(c.file || '')}</td>
            </tr>`;
        });
        html += '</tbody></table></div>';
    }

    // Editable Dataset Fields
    html += '<h4 style="margin:14px 0 6px; color:#1a365d; border-bottom:1px solid #e2e8f0; padding-bottom:4px;">Dataset Fields</h4>';
    html += '<div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:14px;">';
    datasetDescriptors.forEach(desc => {
        const val = desc.value ?? '';
        html += `<div>
            <label style="font-weight:600; display:block; margin-bottom:2px;">${escapeHtml(desc.label)}</label>
            <input type="text" id="df_${escapeHtml(desc.key)}" value="${escapeHtml(String(val))}" style="width:100%; padding:5px; border:1px solid #cbd5e0; border-radius:4px;">
            <span style="font-size:11px; color:#718096;">${escapeHtml(desc.description)}</span>
        </div>`;
    });
    html += '</div>';

    // Group metadata descriptors by top-level group or section
    html += '<h4 style="margin:14px 0 6px; color:#1a365d; border-bottom:1px solid #e2e8f0; padding-bottom:4px;">Scientific Metadata</h4>';

    const groups = {};
    metadataDescriptors.forEach(desc => {
        const groupName = desc.group_labels.length ? desc.group_labels[0] : 'General';
        if (!groups[groupName]) groups[groupName] = [];
        groups[groupName].push(desc);
    });

    for (const [groupName, descs] of Object.entries(groups)) {
        html += `<details open style="margin-bottom:10px; border:1px solid #e2e8f0; border-radius:4px; padding:6px 10px; background:#fff;">
            <summary style="font-weight:700; cursor:pointer; color:#2d3748;">${escapeHtml(groupName)} (${descs.length} fields)</summary>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:8px;">`;

        descs.forEach(desc => {
            const isMaterialField = desc.key.startsWith('anode_material') ||
                                    desc.key.startsWith('cathode_material') ||
                                    desc.key.startsWith('electrolyte');
            const val = desc.value ?? '';
            const missingBadge = desc.missing
                ? '<span style="background:#feebc8; color:#7b341e; font-size:11px; padding:1px 5px; border-radius:3px; margin-left:4px;">Missing</span>'
                : '';
            const isReadonly = !desc.editable || isMaterialField;
            const inputVal = (desc.type === 'array' || typeof val === 'object') ? JSON.stringify(val) : String(val);
            const readonlyAttrs = isReadonly ? 'readonly ' : '';
            const styleAttr = isReadonly
                ? 'style="width:100%; padding:4px 6px; border:1px solid #cbd5e0; border-radius:4px; font-size:12px; background:#edf2f7; cursor:not-allowed;"'
                : 'style="width:100%; padding:4px 6px; border:1px solid #cbd5e0; border-radius:4px; font-size:12px;"';

            html += `<div>
                <label style="font-weight:600; display:block; font-size:12px; margin-bottom:2px;">
                    ${escapeHtml(desc.label)} ${missingBadge}
                </label>
                <input type="text" id="sm_${escapeHtml(desc.key)}" value="${escapeHtml(inputVal)}"
                       data-type="${escapeHtml(desc.type || 'string')}"
                       ${readonlyAttrs}${styleAttr}>
            </div>`;
        });

        html += '</div></details>';
    }

    // Material Samples Resolved Context
    html += '<div style="margin-top:14px; background:#f7fafc; padding:10px; border-radius:4px; border:1px solid #e2e8f0;">';
    html += '<strong>Linked Material Samples:</strong>';
    html += '<ul style="margin:4px 0 0 16px; padding:0;">';
    html += `<li><strong>Anode:</strong> ${escapeHtml(prepareRes.resolved_materials.anode_material.sample_name)} (<code>${escapeHtml(anodeMfid)}</code>)</li>`;
    html += `<li><strong>Cathode:</strong> ${escapeHtml(prepareRes.resolved_materials.cathode_material.sample_name)} (<code>${escapeHtml(cathodeMfid)}</code>)</li>`;
    html += `<li><strong>Electrolyte:</strong> ${escapeHtml(prepareRes.resolved_materials.electrolyte.sample_name)} (<code>${escapeHtml(electrolyteMfid)}</code>)</li>`;
    html += '</ul></div>';

    html += '</div>';

    // Show modal with enlarged style
    const modalEl = document.querySelector('.modal');
    if (modalEl) {
        if (!window._b30GcEcPrevModalStyle) {
            window._b30GcEcPrevModalStyle = {
                maxWidth: modalEl.style.maxWidth || '',
                width: modalEl.style.width || '',
                maxHeight: modalEl.style.maxHeight || '',
            };
        }
        modalEl.style.maxWidth = '900px';
        modalEl.style.width = '95%';
        modalEl.style.maxHeight = '90vh';
    }

    if (typeof window.closeModal === 'function' && !window._b30GcEcModalHooked) {
        const origCloseModal = window.closeModal;
        window.closeModal = function() {
            restoreModalStyle();
            return origCloseModal.apply(this, arguments);
        };
        window._b30GcEcModalHooked = true;
    }

    showModal('Preview & Confirm Upload', html, async () => {
        restoreModalStyle();
        await executeConfirmAndUpload({
            packet,
            prepareRes,
            datasetDescriptors,
            metadataDescriptors,
            files,
            anodeMfid,
            cathodeMfid,
            electrolyteMfid,
            requestedIngestor,
            per_file,
        });
    }, 'Confirm & Upload');
}

function restoreModalStyle() {
    const modalEl = document.querySelector('.modal');
    if (modalEl && window._b30GcEcPrevModalStyle) {
        modalEl.style.maxWidth = window._b30GcEcPrevModalStyle.maxWidth;
        modalEl.style.width = window._b30GcEcPrevModalStyle.width;
        modalEl.style.maxHeight = window._b30GcEcPrevModalStyle.maxHeight;
        window._b30GcEcPrevModalStyle = null;
    }
}

async function executeConfirmAndUpload(opts) {
    const { packet, prepareRes, datasetDescriptors, metadataDescriptors, files, anodeMfid, cathodeMfid, electrolyteMfid, requestedIngestor, per_file } = opts;

    // Collect edited dataset fields
    const datasetEdits = {};
    datasetDescriptors.forEach(desc => {
        const input = document.getElementById(`df_${desc.key}`);
        if (input) datasetEdits[desc.key] = input.value;
    });

    // Collect edited scientific metadata
    const metadataEdits = {};
    metadataDescriptors.forEach(desc => {
        const isMaterialField = desc.key.startsWith('anode_material') ||
                                desc.key.startsWith('cathode_material') ||
                                desc.key.startsWith('electrolyte');
        const input = document.getElementById(`sm_${desc.key}`);
        if (input && desc.editable && !isMaterialField) {
            let val = input.value;
            if (desc.type === 'number' || desc.type === 'integer') {
                const num = Number(val);
                if (!isNaN(num) && val.trim() !== '') val = num;
            } else if (desc.type === 'boolean') {
                val = (val.toLowerCase() === 'true');
            } else if (desc.type === 'array') {
                try {
                    val = JSON.parse(val);
                } catch (_) {}
            }
            metadataEdits[desc.key] = val;
        }
    });

    window.InstrumentParsers.applyDatasetFieldEdits(packet, datasetEdits);
    window.InstrumentParsers.applyMetadataEdits(packet, metadataEdits);

    // Attach parse_provenance
    packet.scientific_metadata.parse_provenance = {
        parsed_locally: true,
        parsed_at: new Date().toISOString(),
        reviewed_by: currentUserState.orcid || currentUserState.username || 'unknown',
        files: per_file,
    };

    // Re-attach authoritative material sample objects
    packet.scientific_metadata.anode_material = prepareRes.resolved_materials.anode_material;
    packet.scientific_metadata.cathode_material = prepareRes.resolved_materials.cathode_material;
    packet.scientific_metadata.electrolyte = prepareRes.resolved_materials.electrolyte;

    const primarySampleId = currentPrimarySample?.unique_id || document.getElementById('sample_barcode').value.trim() || null;

    const progressSection = document.getElementById('section-progress');
    const progressEl = document.getElementById('gc-upload-progress');
    const resultEl = document.getElementById('gc-upload-result');
    progressSection.classList.remove('hidden');
    progressEl.innerHTML = '<div class="info-text">Creating/updating dataset record in Crucible…</div>';
    resultEl.innerHTML = '';

    try {
        const confirmRes = await api('/b30-gc-ec/api/confirm-upload', 'POST', {
            dsid: prepareRes.dsid,
            dataset_fields: packet.dataset_fields,
            scientific_metadata: packet.scientific_metadata,
            keywords: packet.keywords,
            sample_unique_id: primarySampleId,
            anode_sample_mfid: anodeMfid,
            cathode_sample_mfid: cathodeMfid,
            electrolyte_sample_mfid: electrolyteMfid,
        });

        const datasetMfid = confirmRes.dataset_mfid;
        progressEl.innerHTML = `<div class="info-text">Dataset <code>${datasetMfid}</code> ready. Uploading ${files.length} file(s) to storage…</div>`;

        // Upload files directly to storage
        const uploadResults = await window.CrucibleUpload.uploadFiles({
            datasetMfid,
            files,
            ingestion: (file) => {
                if (requestedIngestor) {
                    return { requested: true, ingestionClass: requestedIngestor };
                }
                const name = file.name.toLowerCase();
                if (name.endsWith('.mpt')) {
                    return { requested: true, ingestionClass: 'BiologicMptIngestor' };
                }
                if (name.endsWith('.log')) {
                    return { requested: true, ingestionClass: 'GCLogIngestor' };
                }
                return { requested: true };
            },
            onProgress: (file, p) => {
                const pct = file.size ? Math.min(100, Math.round((p.uploadedBytes / file.size) * 100)) : 100;
                progressEl.innerHTML = `<div class="info-text">Uploading <code>${escapeHtml(file.name)}</code>: ${pct}%</div>`;
            },
        });

        const allOk = uploadResults.every(r => r.ok);
        if (allOk) {
            progressEl.innerHTML = '<div class="info-text" style="color:#22543d; font-weight:700;">✓ All files uploaded and ingestion requested!</div>';
            resultEl.innerHTML = `<div class="alert alert-success" style="margin-top:10px;">
                <strong>Upload Complete!</strong> Dataset: <code>${escapeHtml(datasetMfid)}</code><br>
                <a href="${escapeHtml(confirmRes.hub_url)}" target="_blank" style="font-weight:700; color:#1a365d; text-decoration:underline;">
                    View Dataset in Crucible Hub &rarr;
                </a>
            </div>`;
            showAlert('success', `Upload complete for dataset ${datasetMfid}`, { linkUrl: confirmRes.hub_url || hubDatasetUrl(datasetMfid) });
        } else {
            const failed = uploadResults.filter(r => !r.ok);
            progressEl.innerHTML = `<div class="alert alert-error">Failed uploading ${failed.length} file(s).</div>`;
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
        const rows = await fetchLogbookRows('/b30-gc-ec');
        const cols = ['Date', 'User', 'Dataset Name', 'Measurement', 'Data Type', 'Dataset ID', 'Comment'];
        renderLogbookTable(rows, 'recent-table-body', cols);
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="7">Failed to load datasets: ${escapeHtml(e.message)}</td></tr>`;
    }
}

function exportCsv() {
    downloadLogbookCsv('/b30-gc-ec', 'b30_gc_ec_recent_datasets.csv');
}
