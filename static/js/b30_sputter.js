// B30 Sputter Data Entry - Page Logic

document.addEventListener('DOMContentLoaded', async () => {
    await loadUserState();
    await loadB30State();

    // Show create fields by default if no sample already loaded
    const hasLoadedSample = !!document.getElementById('sample_barcode').value.trim();
    if (!hasLoadedSample) {
        showSamplePanel('create');
    }

    initDatasetGridResponsive();
    initRunTimer();
    initDepositionRateAutofill();
    initDepositionTimeAutocalc();

    // Allow barcode field to trigger lookup on Enter
    document.getElementById('sample_barcode').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') lookupSample();
    });
});

function refreshTimerFromDepositionTimeIfIdle() {
    // only reset timer when not actively counting down
    if (runTimerInterval) return;
    syncTimerFromDepositionTime();
    updateTimerUI(runRemainingSeconds);
}

// ========== State ==========

async function loadB30State() {
    try {
        const state = await api('/b30-sputter/api/state');
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
        const data = await api('/b30-sputter/api/lookup-sample', 'POST', { unique_id: barcode });
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
        const data = await api('/b30-sputter/api/create-sample', 'POST', {
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
    showSamplePanel('create'); // changed from 'hidden'
    setSampleStatus('', '');
}

function printSampleBarcode() {
    const barcode = document.getElementById('sample_barcode').value.trim();
    const name = document.getElementById('sample_name').value.trim();
    printBarcode(barcode, name);
}

// ========== Look up deposition rates ==========

function initDepositionRateAutofill() {
    // Keys used to lookup rate from reference datasets
    const triggerKeys = ['target_material', 'gas1', 'gas1_pc', 'power_w', 'pressure_mtorr', 'power_source'];

    // Deposition rate field key
    const rateKey = 'rate_A_s';

    const keyToEl = {};
    document.querySelectorAll('[data-key]').forEach(el => {
        keyToEl[el.getAttribute('data-key')] = el;
    });

    const rateEl = keyToEl[rateKey];
    if (!rateEl) {
        console.warn(`Deposition rate field not found for data-key="${rateKey}"`);
        return;
    }

    const clearRate = () => {
        rateEl.value = '';
        rateEl.dispatchEvent(new Event('input', { bubbles: true }));
        rateEl.dispatchEvent(new Event('change', { bubbles: true }));
    };

    const lookup = debounce(async () => {
        const payload = {};

        for (const key of triggerKeys) {
            const el = keyToEl[key];
            if (!el) {
                clearRate();
                return;
            }
            const val = String(el.value ?? '').trim();
            if (!val) {
                clearRate();
                return;
            }
            payload[key] = val;
        }

        try {
            const res = await api('/b30-sputter/api/lookup-rate', 'POST', payload);
            if (res && res.found) {
                rateEl.value = res.rate_A_s ?? '';
                rateEl.dispatchEvent(new Event('input', { bubbles: true }));
                rateEl.dispatchEvent(new Event('change', { bubbles: true }));

                const ts = parseCalibrationTimestamp(res.timestamp);
                if (ts && isOlderThanThreeMonths(ts)) {
                    const calDate = formatDateMMDDYYYY(res.timestamp);
                    showAlert('error', `Warning: Deposition rate was calibrated more than 3 months ago (on: ${calDate || 'unknown'}).`);
                }
            } else {
                clearRate();
            }
        } catch (e) {
            console.error('Rate lookup failed:', e);
            clearRate();
        }
    }, 250);

    // Trigger lookup whenever source fields change
    triggerKeys.forEach(key => {
        keyToEl[key]?.addEventListener('change', lookup);
        keyToEl[key]?.addEventListener('blur', lookup);
        keyToEl[key]?.addEventListener('input', lookup);
    });

    // Optional initial lookup if fields already pre-populated
    lookup();
}

function debounce(fn, ms) {
    let t = null;
    return (...args) => {
        clearTimeout(t);
        t = setTimeout(() => fn(...args), ms);
    };
}

// ========== Warn if rate is outdated ==========

function parseCalibrationTimestamp(s) {
    if (!s) return null;
    const dt = new Date(s); // handles ISO with timezone offset
    return Number.isNaN(dt.getTime()) ? null : dt;
}

function isOlderThanThreeMonths(dt) {
    if (!dt) return false;
    const cutoff = new Date();
    cutoff.setMonth(cutoff.getMonth() - 3);
    return dt < cutoff;
}

// ========== Auto-calculate deposition time based on rate and thickness ==========

function initDepositionTimeAutocalc() {
    const keyToEl = {};
    document.querySelectorAll('[data-key]').forEach(el => {
        keyToEl[el.getAttribute('data-key')] = el;
    });

    const rateEl = keyToEl['rate_A_s'];
    const thicknessEl = keyToEl['layer_thickness_nm'];
    const timeEl = keyToEl['deposition_time_s'];

    if (!rateEl || !thicknessEl || !timeEl) return;

    function recalc() {
        const rate = parseFloat(rateEl.value);
        const thicknessNm = parseFloat(thicknessEl.value);

        if (!Number.isFinite(rate) || rate <= 0 || !Number.isFinite(thicknessNm) || thicknessNm < 0) {
            timeEl.value = '';
            refreshTimerFromDepositionTimeIfIdle();
            return;
        }

        // time [s] = thickness [nm] * 10 [Å/nm] / rate [Å/s]
        const timeSec = (thicknessNm * 10) / rate;
        timeEl.value = String(Math.round(timeSec)); // integer seconds
        refreshTimerFromDepositionTimeIfIdle();
    }

    rateEl.addEventListener('input', recalc);
    rateEl.addEventListener('change', recalc);
    thicknessEl.addEventListener('input', recalc);
    thicknessEl.addEventListener('change', recalc);

    recalc();
}

// ========== Run Timer (countdown from deposition_time_s) ==========

let runTimerInterval = null;
let runRemainingSeconds = 0;

function initRunTimer() {
    const goBtn = document.getElementById('go-btn');
    const stopBtn = document.getElementById('stop-btn');
    const resetBtn = document.getElementById('reset-timer-btn');

    if (goBtn) goBtn.addEventListener('click', startRunTimer);
    if (stopBtn) stopBtn.addEventListener('click', stopRunTimer);
    if (resetBtn) resetBtn.addEventListener('click', resetRunTimer);

    // Initialize from deposition_time_s field
    syncTimerFromDepositionTime();
    updateTimerUI(runRemainingSeconds);
}

function getFieldByDataKey(key) {
    return document.querySelector(`[data-key="${key}"]`);
}

function getDepositionTimeSeconds() {
    const depTimeEl = getFieldByDataKey('deposition_time_s');
    if (!depTimeEl) return 0;
    const v = parseInt(String(depTimeEl.value || '').trim(), 10);
    return Number.isFinite(v) && v > 0 ? v : 0;
}

function syncTimerFromDepositionTime() {
    runRemainingSeconds = getDepositionTimeSeconds();
}

function startRunTimer() {
    if (runTimerInterval) return; // already running

    // If timer is at/below 0, reload from deposition_time_s
    if (runRemainingSeconds <= 0) {
        syncTimerFromDepositionTime();
        updateTimerUI(runRemainingSeconds);
    }

    if (runRemainingSeconds <= 0) {
        showAlert('error', 'Deposition time is 0 or missing.');
        return;
    }

    runTimerInterval = setInterval(() => {
        runRemainingSeconds -= 1;

        if (runRemainingSeconds <= 0) {
            runRemainingSeconds = 0;
            updateTimerUI(runRemainingSeconds);
            stopRunTimer();
            showAlert('success', 'Countdown complete.');
            return;
        }

        updateTimerUI(runRemainingSeconds);
    }, 1000);
}

function stopRunTimer() {
    if (!runTimerInterval) return;
    clearInterval(runTimerInterval);
    runTimerInterval = null;
}

function resetRunTimer() {
    stopRunTimer();
    syncTimerFromDepositionTime();
    updateTimerUI(runRemainingSeconds);
}

function updateTimerUI(totalSeconds) {
    const display = document.getElementById('run-timer-display');
    if (display) display.textContent = formatElapsed(totalSeconds);

    const hidden = document.getElementById('run_elapsed_seconds');
    // Keep existing upload key, but now store remaining countdown seconds
    if (hidden) hidden.value = String(totalSeconds);
}

function formatElapsed(totalSeconds) {
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    const s = totalSeconds % 60;
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

// ========== Column Flexibility ==========

function initDatasetGridResponsive() {
    const grid = document.getElementById('dataset-grid');
    if (!grid) return;

    function updateDatasetGridColumns() {
        grid.style.gridTemplateColumns =
            window.innerWidth <= 700 ? '1fr' : 'repeat(2, minmax(0, 1fr))';
    }

    updateDatasetGridColumns();
    window.addEventListener('resize', updateDatasetGridColumns);
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
    payload.run_elapsed_seconds = String(runRemainingSeconds);

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
    const HIDE_IN_PREVIEW = new Set(['run_elapsed_seconds']);

    let html = `<p><strong>Sample:</strong> ${sampleName}</p>`;
    html += '<table class="preview-table"><thead><tr><th>Field</th><th>Value</th></tr></thead><tbody>';

    let shown = 0;
    for (const [k, v] of Object.entries(payload)) {
        if (HIDE_IN_PREVIEW.has(k)) continue;
        html += `<tr><td>${k}</td><td>${v}</td></tr>`;
        shown++;
    }

    if (shown === 0) {
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

function formatDateMMDDYYYY(isoTs) {
    if (!isoTs) return '';
    const dt = new Date(isoTs);
    if (Number.isNaN(dt.getTime())) return '';
    const mm = String(dt.getMonth() + 1).padStart(2, '0');
    const dd = String(dt.getDate()).padStart(2, '0');
    const yyyy = dt.getFullYear();
    return `${mm}/${dd}/${yyyy}`;
}