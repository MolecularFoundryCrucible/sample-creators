// Shared client-side utilities for migrated uploaders.

let currentSample = null;

function readToolConfig() {
    const configEl = document.getElementById('tool-config-json');
    if (!configEl) return {};
    try {
        return JSON.parse(configEl.textContent) || {};
    } catch {
        return {};
    }
}

function getUploaderApiPrefix() {
    if (typeof TOOL_CONFIG !== 'undefined' && TOOL_CONFIG && TOOL_CONFIG.url_prefix) {
        return TOOL_CONFIG.url_prefix;
    }
    return readToolConfig().url_prefix || '';
}

function formatBytes(bytes) {
    const value = Number(bytes);
    if (!Number.isFinite(value) || value <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let size = value;
    let unitIdx = 0;
    while (size >= 1024 && unitIdx < units.length - 1) {
        size /= 1024;
        unitIdx += 1;
    }
    const decimals = unitIdx === 0 ? 0 : size >= 100 ? 0 : size >= 10 ? 1 : 2;
    return `${size.toFixed(decimals)} ${units[unitIdx]}`;
}

function switchTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabId);
    });
    document.querySelectorAll('.tab-panel').forEach(panel => {
        const isMatch = (panel.id === tabId);
        panel.classList.toggle('hidden', !isMatch);
        panel.style.display = isMatch ? '' : 'none';
    });
    if (tabId === 'tab-recent' && typeof loadRecentDatasets === 'function') {
        loadRecentDatasets();
    }
}

// Sample disambiguation modal when multiple samples match a sample name (HTTP 409)
function showAmbiguousSampleModal(candidates, onSelect) {
    let html = '<p class="help-text">Multiple samples found in this project. Please select one:</p>';
    html += '<div style="max-height:260px; overflow-y:auto; margin:10px 0;">';
    html += '<table class="preview-table" style="width:100%;">';
    html += '<thead><tr><th>Sample Name</th><th>MFID</th><th>Action</th></tr></thead><tbody>';
    candidates.forEach((c, idx) => {
        html += `<tr>
            <td><strong>${escapeHtml(c.sample_name || '')}</strong></td>
            <td><code>${escapeHtml(c.unique_id || '')}</code></td>
            <td><button class="btn btn-sm btn-primary" onclick="window._selectSampleCandidate(${idx})">Select</button></td>
        </tr>`;
    });
    html += '</tbody></table></div>';

    window._selectSampleCandidate = (idx) => {
        closeModal();
        onSelect(candidates[idx]);
    };

    showModal('Disambiguate Sample', html, () => {}, 'Close');
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// ========== Shared Sample Panel Controller ==========

function initUploaderSampleInput() {
    const input = document.getElementById('sample_barcode');
    if (!input) return;
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            lookupSample();
        }
    });
    input.addEventListener('input', () => {
        if (!currentSample) return;
        const val = input.value.trim();
        if (val !== currentSample.unique_id && val !== currentSample.sample_name) {
            currentSample = null;
        }
    });
}

function getSelectedSampleUniqueId() {
    const barcodeInput = document.getElementById('sample_barcode')?.value.trim() || '';
    if (currentSample?.unique_id) {
        if (!barcodeInput) {
            currentSample = null;
            return null;
        }
        return currentSample.unique_id;
    }
    return barcodeInput || null;
}

async function lookupSample() {
    const barcodeEl = document.getElementById('sample_barcode');
    const status = document.getElementById('sample-status');
    const val = barcodeEl ? barcodeEl.value.trim() : '';
    if (!val) {
        if (status) status.textContent = 'Enter a barcode or sample name';
        return;
    }
    if (status) status.textContent = 'Looking up...';
    const apiPrefix = getUploaderApiPrefix();
    try {
        const res = await api(`${apiPrefix}/api/lookup-sample`, 'POST', {
            sample_unique_id: val,
            sample_name: val,
        });
        currentSample = res;
        if (status) status.textContent = `\u2713 Found: ${res.sample_name} (${res.unique_id})`;
        populateSampleFields(res);
        showSamplePanel('found');
    } catch (e) {
        if (e.status === 409 && e.data?.candidates) {
            showAmbiguousSampleModal(e.data.candidates, (selected) => {
                currentSample = selected;
                if (barcodeEl) barcodeEl.value = selected.unique_id;
                if (status) status.textContent = `\u2713 Selected: ${selected.sample_name} (${selected.unique_id})`;
                populateSampleFields(selected);
                showSamplePanel('found');
            });
            if (status) status.textContent = 'Multiple candidates found -- select from popup.';
            return;
        }
        currentSample = null;
        if (status) status.textContent = 'Sample not found. Fill details below to create.';
        showSamplePanel('create');
    }
}

function clearSample() {
    currentSample = null;
    const ids = ['sample_barcode', 'sample_name', 'sample_type', 'sample_description'];
    for (const id of ids) {
        const el = document.getElementById(id);
        if (el) el.value = '';
    }
    const status = document.getElementById('sample-status');
    if (status) status.textContent = '';
    showSamplePanel('hidden');
}

function populateSampleFields(sample) {
    const setPair = (id, value) => {
        const input = document.getElementById(id);
        const text = document.getElementById(id + '_text');
        if (input) input.value = value || '';
        if (text) text.textContent = value || '';
    };
    setPair('sample_name', sample.sample_name);
    setPair('sample_type', sample.sample_type);
    setPair('sample_description', sample.description);
}

function showSamplePanel(mode) {
    const panel = document.getElementById('sample-detail-panel');
    const header = document.getElementById('sample-panel-header');
    const createRow = document.getElementById('create-btn-row');
    const fieldIds = ['sample_name', 'sample_type', 'sample_description'];
    if (!panel) return;

    if (mode === 'hidden') {
        panel.classList.add('hidden');
        return;
    }
    panel.classList.remove('hidden');
    if (mode === 'found') {
        if (header) header.textContent = 'Sample Details';
        if (createRow) createRow.classList.add('hidden');
        for (const id of fieldIds) {
            document.getElementById(id)?.classList.add('hidden');
            document.getElementById(id + '_text')?.classList.remove('hidden');
        }
    } else {
        if (header) header.textContent = 'Create New Sample';
        if (createRow) createRow.classList.remove('hidden');
        for (const id of fieldIds) {
            document.getElementById(id)?.classList.remove('hidden');
            document.getElementById(id + '_text')?.classList.add('hidden');
        }
    }
}

async function createNewSample() {
    const name = document.getElementById('sample_name')?.value.trim() || '';
    const type = document.getElementById('sample_type')?.value.trim() || '';
    const desc = document.getElementById('sample_description')?.value.trim() || '';
    if (!name || !type) {
        showAlert('warning', 'Sample Name and Type are required');
        return;
    }
    const apiPrefix = getUploaderApiPrefix();
    try {
        const res = await api(`${apiPrefix}/api/create-sample`, 'POST', {
            sample_name: name,
            sample_type: type,
            description: desc,
        });
        currentSample = res;
        const barcodeEl = document.getElementById('sample_barcode');
        if (barcodeEl) barcodeEl.value = res.unique_id;
        const status = document.getElementById('sample-status');
        if (status) status.textContent = `\u2713 Created: ${res.sample_name} (${res.unique_id})`;
        populateSampleFields(res);
        showSamplePanel('found');
        showAlert('success', `Created sample ${res.sample_name}`);
    } catch (e) {
        showAlert('error', `Sample creation failed: ${e.message}`);
    }
}

// Keep existing inline onclick="createSample()" handlers working identically.
function createSample() {
    return createNewSample();
}

async function printSampleBarcode() {
    const printer = document.getElementById('printer-select')?.value || '';
    if (!printer) {
        showAlert('warning', 'Please select a printer');
        return;
    }
    const sampleId = getSelectedSampleUniqueId();
    const sampleName = currentSample?.sample_name || '';
    if (!sampleId) {
        showAlert('warning', 'No sample to print');
        return;
    }
    const apiPrefix = getUploaderApiPrefix();
    try {
        await api(`${apiPrefix}/api/print-barcode`, 'POST', {
            printer_id: printer,
            sample_id: sampleId,
            sample_name: sampleName,
        });
        showAlert('success', `Print job sent to ${printer}`);
    } catch (e) {
        showAlert('error', `Print failed: ${e.message}`);
    }
}

// ========== Logbook Helpers ==========

async function fetchLogbookRows(apiBase, limit = 100) {
    const res = await api(`${apiBase}/api/recent-datasets?limit=${limit}`);
    return res.rows || [];
}

function renderLogbookTable(rows, tableBodyId, columns) {
    const tbody = document.getElementById(tableBodyId);
    if (!tbody) return;
    if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="${columns.length}">No datasets found in selected project.</td></tr>`;
        return;
    }
    let html = '';
    for (const row of rows) {
        html += '<tr>';
        for (const col of columns) {
            const val = row[col] || '';
            if (col === 'Dataset ID' && val) {
                html += `<td><code>${escapeHtml(val)}</code></td>`;
            } else {
                html += `<td>${escapeHtml(val)}</td>`;
            }
        }
        html += '</tr>';
    }
    tbody.innerHTML = html;
}

function downloadLogbookCsv(apiBase, filename) {
    const base = typeof BASE_URL !== 'undefined' ? BASE_URL : '';
    window.location.href = `${base}${apiBase}/api/recent-datasets/${filename}`;
}
