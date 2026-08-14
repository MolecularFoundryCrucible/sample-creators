// B30 E-beam Data Entry - Page Logic
//
// Sample lookup/creation/run handling lives in deposition_common.js, which this page loads
// first. There is one e-beam tool and no calibration sample, so unlike the sputter page
// there is no tool selector, no rate autofill, and no run timer.

const EBEAM_LOGBOOK_COLS = [
    "Date", "User", "Target", "Power (W)", "Rate (Å/s)",
    "Base press. (mTorr)", "Dep. press. (mTorr)", "Comment",
];

document.addEventListener('DOMContentLoaded', async () => {
    await loadUserState();
    await loadDepositionState();

    // Show create fields by default if no sample already loaded
    if (!document.getElementById('sample_barcode').value.trim()) {
        showSamplePanel('create');
    }

    initDatasetGridResponsive();

    document.getElementById('sample_barcode').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') lookupSample();
    });
});

// ========== Dataset Upload ==========

async function uploadDataset() {
    const runSampleNames = getRunSampleNames();
    if (!runSampleNames.length) {
        showAlert('error', 'No samples in this run. Look up or create a sample first.');
        return;
    }

    const payload = collectDatasetFields();

    showModal(
        'Confirm Upload',
        buildUploadPreview(runSampleNames, payload),
        async () => {
            try {
                const result = await depApi('/api/upload-dataset', 'POST', payload);
                showAlert('success', `Dataset uploaded: ${result.dataset_name} (${result.dataset_id})`);
                if (result.failed_samples && result.failed_samples.length) {
                    const names = result.failed_samples.map(s => s.sample_name || s.unique_id).join(', ');
                    showAlert('error', `Dataset created but could not be linked to: ${names}`);
                }
            } catch (e) {
                showAlert('error', `Upload failed: ${e.message}`);
            }
        }
    );
}

function buildUploadPreview(sampleNames, payload) {
    let html = `<p><strong>Samples (${sampleNames.length}):</strong> ${sampleNames.map(escapeHtml).join(', ')}</p>`;
    html += '<table class="preview-table"><thead><tr><th>Field</th><th>Value</th></tr></thead><tbody>';

    const entries = Object.entries(payload);
    if (!entries.length) {
        html += '<tr><td colspan="2">No fields filled in</td></tr>';
    } else {
        for (const [k, v] of entries) {
            html += `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(v)}</td></tr>`;
        }
    }

    html += '</tbody></table>';
    return html;
}

// ========== Logbook ==========

function logbookParams() {
    return {
        target: document.getElementById('recent-target')?.value || 'All',
        limit: document.getElementById('recent-limit')?.value || '100',
    };
}

async function fetchRecentDatasets() {
    const params = logbookParams();

    setRecentLoading(true);
    try {
        const qs = new URLSearchParams(params).toString();
        const res = await depApi(`/api/recent-datasets?${qs}`);
        renderLogbookRows(EBEAM_LOGBOOK_COLS, res.rows || []);
        if (params.target === 'All') {
            updateTargetOptionsFromRows(res.rows || [], true);
        }
    } catch (e) {
        showAlert('error', `Failed to load recent datasets: ${e.message}`);
    } finally {
        setRecentLoading(false);
    }
}

function exportRecentDatasets() {
    return downloadLogbookCsv(
        '/api/recent-datasets/b30_ebeam_recent_datasets.csv',
        logbookParams(),
        'b30_ebeam_recent_datasets.csv'
    );
}
