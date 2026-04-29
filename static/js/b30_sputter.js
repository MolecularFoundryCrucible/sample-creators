// B30 Sputter Data Entry - Page Logic

document.addEventListener('DOMContentLoaded', async () => {
    await loadUserState();
    await loadB30State();

    // Allow barcode field to trigger lookup on Enter
    document.getElementById('sample_barcode').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') lookupSample();
    });
});

// ========== State ==========

async function loadB30State() {
    try {
        const state = await api('/b30-sputter/api/state');
        if (state.sample_unique_id) {
            populateSampleFields(state);
            setSampleStatus('found', state.sample_name);
        }
    } catch {
        // No state yet, that's fine
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
        const data = await api('/b30-sputter/api/lookup-sample', 'POST', { unique_id: barcode });
        if (data.found) {
            populateSampleFields(data);
            setSampleStatus('found', data.sample_name);
            lockSampleFields(true);
            showAlert('success', `Found sample: ${data.sample_name}`);
        } else {
            clearSampleFields();
            lockSampleFields(false);
            setSampleStatus('not-found', '');
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
        const data = await api('/b30-sputter/api/create-sample', 'POST', {
            sample_name: sampleName,
            sample_type: sampleType,
            description,
        });
        document.getElementById('sample_barcode').value = data.unique_id;
        populateSampleFields(data);
        lockSampleFields(true);
        setSampleStatus('created', data.sample_name);
        showAlert('success', `Created sample: ${data.sample_name} (${data.unique_id})`);
    } catch (e) {
        showAlert('error', e.message);
    }
}

function clearSample() {
    document.getElementById('sample_barcode').value = '';
    clearSampleFields();
    lockSampleFields(false);
    setSampleStatus('', '');
}

// ========== Dataset Upload ==========

async function uploadDataset() {
    const barcode = document.getElementById('sample_barcode').value.trim();
    if (!barcode) {
        showAlert('error', 'No sample selected. Scan a barcode first.');
        return;
    }

    // Collect dataset field values by their Crucible metadata key
    const payload = {};
    document.querySelectorAll('[data-key]').forEach(el => {
        const key = el.getAttribute('data-key');
        const val = el.value.trim();
        if (val) payload[key] = val;
    });

    const sampleName = document.getElementById('sample_name').value || barcode;

    showModal(
        'Confirm Upload',
        buildUploadPreview(sampleName, payload),
        async () => {
            try {
                const result = await api('/b30-sputter/api/upload-dataset', 'POST', payload);
                showAlert('success', `Dataset uploaded: ${result.dataset_name} (${result.dataset_id})`);
            } catch (e) {
                showAlert('error', `Upload failed: ${e.message}`);
            }
        }
    );
}

function buildUploadPreview(sampleName, payload) {
    let html = `<p><strong>Sample:</strong> ${sampleName}</p>`;
    html += '<table class="preview-table"><thead><tr><th>Field</th><th>Value</th></tr></thead><tbody>';
    for (const [k, v] of Object.entries(payload)) {
        html += `<tr><td>${k}</td><td>${v}</td></tr>`;
    }
    if (Object.keys(payload).length === 0) {
        html += '<tr><td colspan="2">No fields filled in</td></tr>';
    }
    html += '</tbody></table>';
    return html;
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

function lockSampleFields(locked) {
    const ids = ['sample_name', 'sample_type', 'sample_description'];
    for (const id of ids) {
        document.getElementById(id).readOnly = locked;
    }
    document.getElementById('btn-create-sample').disabled = locked;
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
