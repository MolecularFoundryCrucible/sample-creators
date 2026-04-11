// RGA Carrier Creator - Page Logic

document.addEventListener('DOMContentLoaded', async () => {
    await loadUserState();
    await loadRGAState();
});

// ========== State ==========

async function loadRGAState() {
    try {
        const state = await api('/rga/api/state');
        document.getElementById('rga_name').value = state.rga_name || '';
        document.getElementById('rga_mf_uuid').value = state.rga_mf_uuid || '';
        document.getElementById('rga_als_uuid').value = state.rga_als_uuid || '';

        // Restore source carrier info
        document.getElementById('carrier_name').textContent = state.carrier_name || 'No Tray Scanned';
        if (state.carrier_uuid) {
            document.getElementById('carrier_uuid').value = state.carrier_uuid;
        }

        // Restore thin film dropdown
        if (state.thin_films && state.thin_films.length > 0) {
            populateThinFilmDropdown(state.thin_films);
        }

        // Restore parameters
        if (state.esaf) document.getElementById('esaf').value = state.esaf;
        document.getElementById('shutter_open_s').value = state.shutter_open_s;
        document.getElementById('mass_range_amu').value = state.mass_range_amu;

        // Restore grid positions
        for (const [pos, tf] of Object.entries(state.positions)) {
            const el = document.getElementById(`pos_${pos}`);
            if (el) el.value = tf || '';
        }

        updateCarrierButtons();
    } catch {
        // No state yet
    }
}

// ========== Carrier Registration ==========

function updateCarrierButtons() {
    const mfUuid = document.getElementById('rga_mf_uuid').value;
    const alsUuid = document.getElementById('rga_als_uuid').value;
    const btnCrucible = document.getElementById('btn-reg-crucible');
    const btnAls = document.getElementById('btn-reg-als');

    if (mfUuid) {
        btnCrucible.disabled = true;
        btnCrucible.textContent = 'In Crucible ✓';
    } else {
        btnCrucible.disabled = false;
        btnCrucible.textContent = 'Add to Crucible';
    }

    if (alsUuid) {
        btnAls.disabled = true;
        btnAls.textContent = 'In ALS DB ✓';
    } else {
        btnAls.disabled = false;
        btnAls.textContent = 'Add to ALS DB';
    }
}

function onCarrierNameChanged() {
    document.getElementById('rga_mf_uuid').value = '';
    document.getElementById('rga_als_uuid').value = '';
    updateCarrierButtons();
}

async function getNextCarrierName() {
    try {
        const data = await api('/rga/api/next-carrier-name', 'POST');
        document.getElementById('rga_name').value = data.rga_name;
        document.getElementById('rga_mf_uuid').value = '';
        document.getElementById('rga_als_uuid').value = '';
        updateCarrierButtons();
        showAlert('success', `Next RGA name: ${data.rga_name}`);
    } catch (e) {
        showAlert('error', e.message);
    }
}

async function lookupCarrier() {
    const rgaName = document.getElementById('rga_name').value.trim();
    if (!rgaName) {
        showAlert('error', 'Enter a carrier name first');
        return;
    }
    try {
        const data = await api('/rga/api/lookup-carrier', 'POST', { rga_name: rgaName });
        document.getElementById('rga_mf_uuid').value = data.mf_uuid;
        document.getElementById('rga_als_uuid').value = data.als_uuid;
        updateCarrierButtons();
        if (data.mf_uuid) {
            showAlert('success', `Found carrier '${rgaName}'`);
        } else {
            showAlert('info', `Carrier '${rgaName}' not found in Crucible — ready to create`);
        }
    } catch (e) {
        showAlert('error', e.message);
    }
}

async function registerCrucible() {
    const rgaName = document.getElementById('rga_name').value.trim();
    if (!rgaName) {
        showAlert('error', 'Enter a carrier name first');
        return;
    }
    try {
        const data = await api('/rga/api/register-crucible', 'POST', { rga_name: rgaName });
        document.getElementById('rga_mf_uuid').value = data.mf_uuid;
        updateCarrierButtons();
        showAlert('success', `RGA '${data.rga_name}' created in Crucible. UUID: ${data.mf_uuid}`);
    } catch (e) {
        showAlert('error', e.message);
    }
}

async function registerALS() {
    const rgaName = document.getElementById('rga_name').value.trim();
    if (!rgaName) {
        showAlert('error', 'Enter a carrier name first');
        return;
    }
    try {
        const data = await api('/rga/api/register-als', 'POST', { rga_name: rgaName });
        document.getElementById('rga_als_uuid').value = data.als_uuid;
        updateCarrierButtons();
        showAlert('success', `RGA '${data.rga_name}' added to ALS SciCat. Set ID: ${data.als_uuid}`);
    } catch (e) {
        showAlert('error', e.message);
    }
}

// ========== Carrier Scan ==========

async function scanCarrier() {
    const uuid = document.getElementById('carrier_uuid').value.trim();
    if (!uuid) {
        showAlert('error', 'Please enter a carrier UUID');
        return;
    }
    try {
        const data = await api('/rga/api/scan-carrier', 'POST', { carrier_uuid: uuid });
        document.getElementById('carrier_name').textContent = data.carrier_name;
        populateThinFilmDropdown(data.thin_films);
        showAlert('success', `Carrier: ${data.carrier_name} (${data.thin_films.length} samples)`);
    } catch (e) {
        showAlert('error', e.message);
    }
}

// ========== Layout Management ==========

const RGA_POSITIONS = [];
for (const row of 'ABCDEF') {
    for (let col = 1; col <= 6; col++) {
        RGA_POSITIONS.push(`${row}${col}`);
    }
}

function getLayoutPositions() {
    const positions = {};
    for (const pos of RGA_POSITIONS) {
        const el = document.getElementById(`pos_${pos}`);
        positions[pos] = el ? el.value : '';
    }
    return positions;
}

async function persistLayout() {
    const data = {
        positions: getLayoutPositions(),
        shutter_open_s: parseInt(document.getElementById('shutter_open_s').value),
        mass_range_amu: parseInt(document.getElementById('mass_range_amu').value),
        esaf: document.getElementById('esaf').value,
    };
    await api('/rga/api/layout', 'POST', data);
}

async function updateParams() {
    await persistLayout();
}

function assignToCell(pos) {
    const tf = document.getElementById('select_thinfilm').value;
    if (!tf) {
        showAlert('error', 'No thin film selected');
        return;
    }
    document.getElementById(`pos_${pos}`).value = tf;
    persistLayout();
}

async function addOneToRGA() {
    const pos = document.getElementById('select_rga_pos').value;
    const tf = document.getElementById('select_thinfilm').value;
    if (!tf) {
        showAlert('error', 'No thin film selected');
        return;
    }
    document.getElementById(`pos_${pos}`).value = tf;
    await persistLayout();
}

async function addAllToRGA() {
    const select = document.getElementById('select_thinfilm');
    const tfList = Array.from(select.options).map(o => o.value);
    let tfIdx = 0;
    for (const pos of RGA_POSITIONS) {
        if (tfIdx >= tfList.length) break;
        const el = document.getElementById(`pos_${pos}`);
        if (el && !el.value) {
            el.value = tfList[tfIdx];
            tfIdx++;
        }
    }
    await persistLayout();
    showAlert('success', `Assigned ${tfIdx} thin films to RGA carrier`);
}

async function clearLayout() {
    for (const pos of RGA_POSITIONS) {
        const el = document.getElementById(`pos_${pos}`);
        if (el) el.value = '';
    }
    try {
        await api('/rga/api/clear-layout', 'POST');
        showAlert('success', 'Layout cleared');
    } catch (e) {
        showAlert('error', e.message);
    }
}

// ========== CSV Generation ==========

async function generateCSV() {
    // Persist layout first
    await persistLayout();

    try {
        const fullUrl = (typeof BASE_URL !== 'undefined' ? BASE_URL : '') + '/rga/api/generate-csv';
        const res = await fetch(fullUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.error || 'CSV generation failed');
        }
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const disposition = res.headers.get('Content-Disposition');
        const match = disposition && disposition.match(/filename=(.+)/);
        a.download = match ? match[1] : 'rga_output.txt';
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        showAlert('success', 'CSV downloaded');
    } catch (e) {
        showAlert('error', e.message);
    }
}

// ========== Preview & Upload ==========

async function previewAndUpload() {
    try {
        const rgaName = document.getElementById('rga_name').value;
        const mfUuid = document.getElementById('rga_mf_uuid').value;
        const alsUuid = document.getElementById('rga_als_uuid').value;

        if (!rgaName) {
            showAlert('error', 'No carrier specified. Enter a name or use Get Next #.');
            return;
        }
        if (!mfUuid) {
            showAlert('error', 'Carrier has not been registered in Crucible yet.');
            return;
        }
        if (!alsUuid) {
            showAlert('error', 'Carrier has not been registered in ALS SciCat yet.');
            return;
        }

        await persistLayout();

        showAlert('success', 'Collecting sample info from Crucible...');
        const preview = await api('/rga/api/collect-preview', 'POST');

        if (!preview.samples || preview.samples.length === 0) {
            showAlert('error', 'No samples found in RGA carrier layout');
            return;
        }

        let html = `<p><strong>RGA Carrier:</strong> ${preview.rga_name}</p>`;
        html += `<p><strong>Crucible UUID:</strong> ${preview.rga_mf_uuid}</p>`;
        html += `<p><strong>ALS Set ID:</strong> ${preview.rga_als_uuid}</p>`;
        html += `<p><strong>Samples:</strong> ${preview.samples.length}</p>`;
        html += '<table class="preview-table"><thead><tr><th>Pos</th><th>Thin Film</th><th>MFID</th><th>Parameters</th></tr></thead><tbody>';
        for (const s of preview.samples) {
            const scanLines = Object.entries(s.scan_params || {})
                .map(([k, v]) => `<span class="param-key">${k}:</span> ${v}`)
                .join('<br>');
            const mdLines = Object.entries(s.scientific_metadata || {})
                .map(([k, v]) => `<span class="param-key meta-key">${k}:</span> <span class="meta-val">${v}</span>`)
                .join('<br>');
            const divider = scanLines && mdLines ? '<div class="param-divider"></div>' : '';
            html += `<tr><td>${s.rga_position}</td><td>${s.tf_name}</td><td class="mfid-cell">${s.tf_mfid}</td><td class="params-cell">${scanLines}${divider}${mdLines}</td></tr>`;
        }
        html += '</tbody></table>';

        showModal('Upload Preview', html, async () => {
            try {
                const result = await api('/rga/api/upload', 'POST');
                showAlert('success', `Successfully uploaded ${result.uploaded_count} samples to database`);
            } catch (e) {
                showAlert('error', `Upload failed: ${e.message}`);
            }
        });
    } catch (e) {
        showAlert('error', e.message);
    }
}
