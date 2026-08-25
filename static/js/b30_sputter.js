// B30 Sputter Data Entry - Page Logic
//
// Sample lookup/creation/run handling lives in deposition_common.js, which this page loads
// first. What stays here is sputter-specific: the gas and co-deposition toggles,
// deposition-rate autofill, the run timer, and the sputter logbook.

document.addEventListener('DOMContentLoaded', async () => {
    await loadUserState();

    await loadDepositionState();

    // Show create fields by default if no sample already loaded
    const hasLoadedSample = !!document.getElementById('sample_barcode').value.trim();
    if (!hasLoadedSample) {
        showSamplePanel('create');
    }

    initDatasetGridResponsive();
    captureDatasetFieldDefaults();
    initRunTimer();
    initCoDepositionToggle();
    initGas2Toggle();
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

// ========== Hide second gas fields unless used ==========

function initGas2Toggle() {
    const keyToEl = {};
    document.querySelectorAll('[data-key]').forEach(el => keyToEl[el.dataset.key] = el);

    const enabledEl = keyToEl['02_second_gas_enabled'];
    const gas2Keys = ['05_gas2', '06_gas2_pc'];

    if (!enabledEl) return;

    function setVisible(show) {
        gas2Keys.forEach(k => {
            const el = keyToEl[k];
            if (!el) return;
            const grp = el.closest('.form-group');
            if (grp) grp.classList.toggle('hidden', !show);
            if (!show && el.type !== 'checkbox') el.value = '';
        });
    }

    setVisible(enabledEl.checked);
    enabledEl.addEventListener('change', () => {
        setVisible(enabledEl.checked);

        // fire change/input so dependent logic reacts (if any)
        gas2Keys.forEach(k => {
            const el = keyToEl[k];
            if (!el) return;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        });
    });
}

// ========== Look up deposition rates ==========

let triggerRateLookup = null;

function initDepositionRateAutofill() {
    // CHANGED: split keys into base/primary/secondary instead of one trigger list
    const requiredBaseKeys = ['03_gas1', '04_gas1_pc', '07_pressure_mTorr'];
    const primaryKeys = ['09_target_material', '11_power_W', '10_power_source'];
    const secondaryKeys = ['13_target_material_2', '15_power_W_2', '14_power_source_2'];

    // unchanged total deposition rate key
    const rateKey = '19_rate_A_s';

    const keyToEl = {};
    document.querySelectorAll('[data-key]').forEach(el => {
        keyToEl[el.getAttribute('data-key')] = el;
    });

    const rateEl = keyToEl[rateKey];
    if (!rateEl) {
        console.warn(`Deposition rate field not found for data-key="${rateKey}"`);
        return;
    }

    // CHANGED: co-dep toggle + optional per-target display fields
    const coDepEl = keyToEl['01_co_deposition_enabled'];
    const rate1El = keyToEl['17_rate_A_s_1']; // optional
    const rate2El = keyToEl['18_rate_A_s_2']; // optional

    const isCoDepEnabled = () => !!(coDepEl && coDepEl.checked);

    // CHANGED: clear total + optional per-target fields
    const clearRate = () => {
        if (rate1El) rate1El.value = '';
        if (rate2El) rate2El.value = '';
        rateEl.value = '';
        rateEl.dispatchEvent(new Event('input', { bubbles: true }));
        rateEl.dispatchEvent(new Event('change', { bubbles: true }));
    };

    // CHANGED: helper to set summed total
    const setRates = (r1, r2, useSecond) => {
        // If co-dep is OFF, never keep per-target fields populated
        if (!useSecond) {
            if (rate1El) rate1El.value = '';
            if (rate2El) rate2El.value = '';
        } else {
            if (rate1El) rate1El.value = (r1 != null ? String(r1) : '');
            if (rate2El) rate2El.value = (r2 != null ? String(r2) : '');
        }

        const has1 = r1 != null;
        const has2 = useSecond ? (r2 != null) : false;

        if (!has1 && !has2) {
            rateEl.value = '';
        } else {
            const total = (has1 ? r1 : 0) + (has2 ? r2 : 0);
            rateEl.value = String(total);
        }

        // notify listeners
        if (rate1El) {
            rate1El.dispatchEvent(new Event('input', { bubbles: true }));
            rate1El.dispatchEvent(new Event('change', { bubbles: true }));
        }
        if (rate2El) {
            rate2El.dispatchEvent(new Event('input', { bubbles: true }));
            rate2El.dispatchEvent(new Event('change', { bubbles: true }));
        }
        rateEl.dispatchEvent(new Event('input', { bubbles: true }));
        rateEl.dispatchEvent(new Event('change', { bubbles: true }));
    };

    // CHANGED: build payload by key set (primary or secondary)
    const buildPayload = (materialKey, powerKey, sourceKey) => {
        const gas1 = String(keyToEl['03_gas1']?.value ?? '').trim();
        const gas1_pc = String(keyToEl['04_gas1_pc']?.value ?? '').trim();
        const pressure_mtorr = String(keyToEl['07_pressure_mTorr']?.value ?? '').trim();

        const target_material = String(keyToEl[materialKey]?.value ?? '').trim();
        const power_w = String(keyToEl[powerKey]?.value ?? '').trim();
        const power_source = String(keyToEl[sourceKey]?.value ?? '').trim();

        if (!gas1 || !gas1_pc || !pressure_mtorr || !target_material || !power_w || !power_source) {
            return null;
        }

        // NOTE: keep payload keys expected by backend route
        return {
            "09_target_material": target_material,
            "03_gas1": gas1,
            "04_gas1_pc": gas1_pc,
            "11_power_W": power_w,
            "07_pressure_mTorr": pressure_mtorr,
            "10_power_source": power_source
        };
    };

    const lookupOne = async (payload) => {
        const res = await depApi('/api/lookup-rate', 'POST', payload);
        if (res && res.found) {
            const n = Number(res["19_rate_A_s"]);
            return { rate: Number.isFinite(n) ? n : null, res };
        }
        return { rate: null, res: null };
    };

    const lookup = debounce(async () => {
        const primaryPayload = buildPayload('09_target_material', '11_power_W', '10_power_source');
        if (!primaryPayload) {
            clearRate();
            return;
        }

        const useSecond = isCoDepEnabled();
        const secondaryPayload = useSecond
            ? buildPayload('13_target_material_2', '15_power_W_2', '14_power_source_2')
            : null;

        try {
            // 1) Always look up primary first and update UI immediately
            const r1Obj = await lookupOne(primaryPayload);
            setRates(r1Obj.rate, null, false); // total = primary (or blank if not found)

            const ts1 = parseCalibrationTimestamp(r1Obj.res?.timestamp);
            if (ts1 && isOlderThanThreeMonths(ts1)) {
                const calDate = formatDateMMDDYYYY(r1Obj.res.timestamp);
                showAlert('error', `Warning: Primary deposition rate was calibrated more than 3 months ago (on: ${calDate || 'unknown'}).`);
            }

            // 2) If co-dep is enabled and secondary fields are complete, add secondary
            if (useSecond && secondaryPayload) {
                const r2Obj = await lookupOne(secondaryPayload);

                // total now becomes primary + secondary (secondary contributes only if found)
                setRates(r1Obj.rate, r2Obj.rate, true);

                const ts2 = parseCalibrationTimestamp(r2Obj.res?.timestamp);
                if (ts2 && isOlderThanThreeMonths(ts2)) {
                    const calDate = formatDateMMDDYYYY(r2Obj.res.timestamp);
                    showAlert('error', `Warning: Secondary deposition rate was calibrated more than 3 months ago (on: ${calDate || 'unknown'}).`);
                }
            } else if (useSecond && !secondaryPayload) {
                // co-dep enabled but secondary incomplete:
                // keep showing primary-only total; clear optional secondary rate field if present
                if (rate2El) rate2El.value = '';
                // no clearRate() here on purpose
            }
        } catch (e) {
            console.error('Rate lookup failed:', e);
            clearRate();
        }
    }, 250);

    triggerRateLookup = lookup;

    // CHANGED: expanded trigger list includes secondary + co-dep toggle
    const triggerKeys = [
        ...requiredBaseKeys,
        ...primaryKeys,
        ...secondaryKeys,
        '01_co_deposition_enabled'
    ];

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

    const rateEl = keyToEl['19_rate_A_s'];
    const thicknessEl = keyToEl['20_layer_thickness_nm'];
    const timeEl = keyToEl['21_deposition_time_s'];

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
    setTimerStatus(false);
}

function getFieldByDataKey(key) {
    return document.querySelector(`[data-key="${key}"]`);
}

function getDepositionTimeSeconds() {
    const depTimeEl = getFieldByDataKey('21_deposition_time_s');
    if (!depTimeEl) return 0;
    const v = parseInt(String(depTimeEl.value || '').trim(), 10);
    return Number.isFinite(v) && v > 0 ? v : 0;
}

function syncTimerFromDepositionTime() {
    runRemainingSeconds = getDepositionTimeSeconds();
}

function startRunTimer() {
    if (runTimerInterval) {
        showModal(
            'Timer Already Running',
            `<p>A run is already in progress with <strong>${formatElapsed(runRemainingSeconds)}</strong> remaining.</p>
             <p>Stopping it discards the current countdown and restarts from the deposition time now in the form.</p>`,
            () => {
                resetRunTimer();
                startRunTimer();
            },
            'Stop and Restart'
        );
        return;
    }

    // If timer is at/below 0, reload from deposition_time_s
    if (runRemainingSeconds <= 0) {
        syncTimerFromDepositionTime();
        updateTimerUI(runRemainingSeconds);
    }

    if (runRemainingSeconds <= 0) {
        showAlert('error', 'Deposition time is 0 or missing.');
        return;
    }

    setTimerStatus(true);

    runTimerInterval = setInterval(() => {
        runRemainingSeconds -= 1;

        if (runRemainingSeconds <= 0) {
            runRemainingSeconds = 0;
            updateTimerUI(runRemainingSeconds);
            stopRunTimer();
            showTimerFinishedOverlay();
            playTimerFinishedBeep();
            return;
        }

        updateTimerUI(runRemainingSeconds);
    }, 1000);
}

function stopRunTimer() {
    if (!runTimerInterval) return;
    clearInterval(runTimerInterval);
    runTimerInterval = null;
    setTimerStatus(false);
}

function resetRunTimer() {
    stopRunTimer();
    syncTimerFromDepositionTime();
    updateTimerUI(runRemainingSeconds);
    setTimerStatus(false);
}

function updateTimerUI(totalSeconds) {
    const display = document.getElementById('run-timer-display');
    if (display) display.textContent = formatElapsed(totalSeconds);
}

function formatElapsed(totalSeconds) {
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    const s = totalSeconds % 60;
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function showTimerFinishedOverlay() {
    const el = document.getElementById('timer-finished-overlay');
    if (el) el.classList.remove('hidden');
}

function dismissTimerFinishedOverlay() {
    const el = document.getElementById('timer-finished-overlay');
    if (el) el.classList.add('hidden');
}

function playTimerFinishedBeep() {
    try {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (!AudioCtx) return;

        const ctx = new AudioCtx();
        const now = ctx.currentTime;

        // 8 urgent pulses, alternating frequencies
        const pulses = 8;
        const step = 0.16;      // time between pulse starts
        const dur = 0.13;       // pulse duration

        for (let i = 0; i < pulses; i++) {
            const t = now + i * step;
            const freq = (i % 2 === 0) ? 780 : 520; // alternating high/low

            const osc = ctx.createOscillator();
            const gain = ctx.createGain();

            osc.type = 'square'; // harsher, more alarming than sine
            osc.frequency.setValueAtTime(freq, t);

            // Fast attack, strong level, sharp decay
            gain.gain.setValueAtTime(0.0001, t);
            gain.gain.exponentialRampToValueAtTime(0.45, t + 0.01);
            gain.gain.exponentialRampToValueAtTime(0.0001, t + dur);

            osc.connect(gain);
            gain.connect(ctx.destination);

            osc.start(t);
            osc.stop(t + dur + 0.01);
        }

        setTimeout(() => ctx.close(), Math.ceil((pulses * step + 0.4) * 1000));
    } catch (e) {
        console.warn('Beep failed:', e);
    }
}

// ========== Enable co-deposition ==========

function initCoDepositionToggle() {
    const keyToEl = {};
    document.querySelectorAll('[data-key]').forEach(el => keyToEl[el.dataset.key] = el);

    const enabledEl = keyToEl['01_co_deposition_enabled'];
    const secondKeys = ['17_rate_A_s_1', '13_target_material_2', '14_power_source_2', '15_power_W_2', '16_DC_voltage_V_2', '18_rate_A_s_2'];

    if (!enabledEl) return;

    function setVisible(show) {
        secondKeys.forEach(k => {
            const el = keyToEl[k];
            if (!el) return;
            const grp = el.closest('.form-group');
            if (grp) grp.classList.toggle('hidden', !show);

            if (!show && el.type !== 'checkbox') {
                // co-dep OFF: clear per-target secondary/aux fields
                // (this includes rate_A_s_1 and rate_A_s_2)
                el.value = '';

                // notify listeners
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }
        });

        // IMPORTANT: do NOT clear total rate_A_s here
        // It should remain populated for single-target mode.
    }

    setVisible(enabledEl.checked);
    // The rate autofill in initDepositionRateAutofill() also listens on this checkbox, so
    // toggling it re-runs the lookup and the dependent time/timer recalc from there.
    enabledEl.addEventListener('change', () => setVisible(enabledEl.checked));
}

// ========== Dataset create / update ==========

// Set once a dataset has been created from this form. While it holds an ID the page is in
// its saved state and Update Dataset writes back to that record.
let currentDatasetId = null;
let currentDatasetName = null;

// Captured before any autofill runs so New Dataset restores the configured defaults rather
// than emptying every field.
const datasetFieldDefaults = new Map();

function captureDatasetFieldDefaults() {
    document.querySelectorAll('#dataset-grid [data-key]').forEach(el => {
        datasetFieldDefaults.set(el, el.type === 'checkbox' ? el.checked : el.value);
    });
}

function buildDatasetPayload() {
    return collectDatasetFields();
}

async function createDataset() {
    const runSampleNames = getRunSampleNames();
    if (!runSampleNames.length) {
        showAlert('error', 'No samples in this run. Look up or create a sample first.');
        return;
    }

    const payload = buildDatasetPayload();

    showModal(
        'Confirm Create Dataset',
        buildDatasetPreview(runSampleNames, payload),
        async () => {
            try {
                const result = await depApi('/api/create-dataset', 'POST', payload);
                setDatasetSaved(result.dataset_id, result.dataset_name);
                showAlert('success', `Dataset created: ${result.dataset_name} (${result.dataset_id})`);
                reportFailedLinks(result.failed_samples);
            } catch (e) {
                showAlert('error', `Create failed: ${e.message}`);
            }
        },
        'Create Dataset'
    );
}

async function updateDataset() {
    if (!currentDatasetId) return;

    const payload = buildDatasetPayload();
    payload.dataset_id = currentDatasetId;
    payload.dataset_name = currentDatasetName;

    try {
        const result = await depApi('/api/update-dataset', 'POST', payload);
        setDatasetSaved(result.dataset_id, result.dataset_name);
        const linked = result.linked_samples || [];
        showAlert('success', linked.length
            ? `Dataset updated — newly linked: ${linked.join(', ')}`
            : 'Dataset updated');
        reportFailedLinks(result.failed_samples);
    } catch (e) {
        showAlert('error', `Update failed: ${e.message}`);
    }
}

function resetForm() {
    showModal(
        'Reset Form',
        '<p>Do you want to clear sample information in addition to resetting deposition parameters?</p>',
        () => resetDatasetForm(false),
        'Keep Samples',
        { label: 'Clear Samples', onClick: () => resetDatasetForm(true) }
    );
}

function resetDatasetForm(clearSamples, { silent = false } = {}) {
    setDatasetSaved(null, null);

    // Restore every value first, then notify — the co-deposition and rate-lookup handlers
    // read sibling fields, so they need to see the fully reset form.
    datasetFieldDefaults.forEach((value, el) => {
        if (el.type === 'checkbox') el.checked = value;
        else el.value = value;
    });
    datasetFieldDefaults.forEach((_, el) => {
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
    });

    // The countdown is deliberately left alone: a run can still be depositing while the
    // form is being filled in for the next one.
    if (clearSamples) clearRunSamples(true);
    if (!silent) {
        showAlert('info', clearSamples
            ? 'Form reset — deposition parameters and run samples cleared'
            : 'Form reset — run samples kept');
    }
}

function setDatasetSaved(datasetId, datasetName) {
    currentDatasetId = datasetId;
    currentDatasetName = datasetName;

    const saved = !!datasetId;
    document.getElementById('dataset-saved-panel').classList.toggle('hidden', !saved);
    document.getElementById('dataset-grid').classList.toggle('is-saved', saved);

    if (saved) {
        document.getElementById('dataset-saved-name').textContent = datasetName || '';
        document.getElementById('dataset-saved-id').textContent = datasetId;
    }
}

function reportFailedLinks(failed) {
    if (!failed || !failed.length) return;
    const names = failed.map(s => s.sample_name || s.unique_id).join(', ');
    showAlert('error', `Could not link to: ${names}`);
}

function buildDatasetPreview(sampleNames, payload) {
    let html = `<p><strong>Samples (${sampleNames.length}):</strong> ${sampleNames.map(escapeHtml).join(', ')}</p>`;
    html += '<table class="preview-table"><thead><tr><th>Field</th><th>Value</th></tr></thead><tbody>';

    let shown = 0;
    for (const [k, v] of Object.entries(payload)) {
        html += `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(v)}</td></tr>`;
        shown++;
    }

    if (shown === 0) {
        html += '<tr><td colspan="2">No fields filled in</td></tr>';
    }

    html += '</tbody></table>';
    return html;
}

// ========== Logbook ==========

const SPUTTER_LOGBOOK_COLS = [
  "Date", "User", "Gas", "Press. (mTorr)", "Temp. (\u00b0C)", "Target", "Source",
  "Power (W)", "DCV (V)", "Indiv. rates (\u00c5/s)", "Tot. rate (\u00c5/s)", "Time (s)",
  "Thickness (nm)", "Comment"
];

function logbookParams() {
  return {
    view: document.getElementById('recent-view')?.value || 'Deposition only',
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
    renderLogbookRows(SPUTTER_LOGBOOK_COLS, res.rows || []);
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
    '/api/recent-datasets/b30_sputter_recent_datasets.csv',
    logbookParams(),
    'b30_sputter_recent_datasets.csv'
  );
}

// ========== Helpers ==========

function formatDateMMDDYYYY(isoTs) {
    if (!isoTs) return '';
    const dt = new Date(isoTs);
    if (Number.isNaN(dt.getTime())) return '';
    const mm = String(dt.getMonth() + 1).padStart(2, '0');
    const dd = String(dt.getDate()).padStart(2, '0');
    const yyyy = dt.getFullYear();
    return `${mm}/${dd}/${yyyy}`;
}

function setTimerStatus(running) {
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) logoutBtn.disabled = running;
    // The tooltip lives on the wrapper because browsers suppress hover events on
    // disabled elements.
    const logoutWrap = document.getElementById('logout-wrap');
    if (logoutWrap) {
        logoutWrap.title = running ? 'Wait for the timer to complete before logging out' : '';
    }

    const badge = document.getElementById('timer-status-badge');
    if (!badge) return;
    if (running) {
        badge.textContent = 'RUNNING';
        badge.style.background = '#c6f6d5';
        badge.style.color = '#2d3748';
    } else {
        badge.textContent = 'IDLE';
        badge.style.background = '#e2e8f0';
        badge.style.color = '#2d3748';
    }
}

// Unlike the Reset Form button, logging out does clear the countdown — the logout button is
// disabled while a run is timing, so this only ever reseeds an already-finished timer.
registerLogoutReset(() => {
    resetDatasetForm(true, { silent: true });
    resetRunTimer();
});
