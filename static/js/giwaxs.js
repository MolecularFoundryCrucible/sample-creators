// GIWAXS Bar Creator - Page Logic

document.addEventListener('DOMContentLoaded', async () => {
    await loadUserState();
    await loadGiwaxsState();
    recalcPositions();
});

// ========== State ==========

async function loadGiwaxsState() {
    try {
        const state = await api('/giwaxs/api/state');
        // Restore bar info (populate both tabs)
        document.getElementById('bar_name').value = state.bar_name || '';
        document.getElementById('bar_mf_uuid').value = state.bar_mf_uuid || '';
        document.getElementById('bar_als_uuid').value = state.bar_als_uuid || '';
        document.getElementById('bar_name_search').value = state.bar_name || '';
        document.getElementById('bar_mf_uuid_search').value = state.bar_mf_uuid || '';
        document.getElementById('bar_als_uuid_search').value = state.bar_als_uuid || '';

        // Restore tray info
        document.getElementById('tray_name').textContent = state.tray_name || 'No Tray Scanned';
        if (state.tray_uuid) {
            document.getElementById('tray_uuid').value = state.tray_uuid;
        }

        // Restore thin film dropdown
        if (state.thin_films && state.thin_films.length > 0) {
            populateThinFilmDropdown(state.thin_films);
        }

        // Restore parameters
        document.getElementById('offset_mm').value = state.offset_mm;
        document.getElementById('wafer_width').value = state.wafer_width;
        document.getElementById('incidence_angle').value = state.incidence_angle;

        // Restore layout
        for (let i = 1; i <= 14; i++) {
            const tf = state.positions[String(i)] || '';
            document.getElementById(`pos_${i}_tf`).value = tf;
        }
    } catch {
        // No state yet
    }
}

// ========== Tab Switching ==========

function showBarTab(tab) {
    document.getElementById('bar-tab-new').classList.toggle('hidden', tab !== 'new');
    document.getElementById('bar-tab-existing').classList.toggle('hidden', tab !== 'existing');
    for (const btn of document.querySelectorAll('#section-bar .tab-btn')) {
        btn.classList.remove('active');
    }
    event.target.classList.add('active');
}

// ========== Bar Registration ==========

async function getNextBarName() {
    try {
        const data = await api('/giwaxs/api/next-bar-name', 'POST');
        document.getElementById('bar_name').value = data.bar_name;
        document.getElementById('bar_mf_uuid').value = '';
        document.getElementById('bar_als_uuid').value = '';
        showAlert('success', `Next bar name: ${data.bar_name}`);
    } catch (e) {
        showAlert('error', e.message);
    }
}

async function lookupBar() {
    const barName = document.getElementById('bar_name_search').value.trim();
    if (!barName) return;
    try {
        const data = await api('/giwaxs/api/lookup-bar', 'POST', { bar_name: barName });
        document.getElementById('bar_mf_uuid_search').value = data.mf_uuid;
        document.getElementById('bar_als_uuid_search').value = data.als_uuid;
        if (data.mf_uuid) {
            showAlert('success', `Found bar '${barName}'`);
        } else {
            showAlert('error', `Bar '${barName}' not found in Crucible`);
        }
    } catch (e) {
        showAlert('error', e.message);
    }
}

async function registerCrucible() {
    try {
        const data = await api('/giwaxs/api/register-crucible', 'POST');
        document.getElementById('bar_mf_uuid').value = data.mf_uuid;
        showAlert('success', `Bar '${data.bar_name}' created in Crucible. UUID: ${data.mf_uuid}`);
    } catch (e) {
        showAlert('error', e.message);
    }
}

async function registerALS() {
    try {
        const data = await api('/giwaxs/api/register-als', 'POST');
        document.getElementById('bar_als_uuid').value = data.als_uuid;
        showAlert('success', `Bar '${data.bar_name}' added to ALS SciCat. Set ID: ${data.als_uuid}`);
    } catch (e) {
        showAlert('error', e.message);
    }
}

// ========== Tray Scan ==========

async function scanTray() {
    const uuid = document.getElementById('tray_uuid').value.trim();
    if (!uuid) {
        showAlert('error', 'Please enter a tray UUID');
        return;
    }
    try {
        const data = await api('/giwaxs/api/scan-tray', 'POST', { tray_uuid: uuid });
        document.getElementById('tray_name').textContent = data.tray_name;
        populateThinFilmDropdown(data.thin_films);
        showAlert('success', `Tray: ${data.tray_name} (${data.thin_films.length} samples)`);
    } catch (e) {
        showAlert('error', e.message);
    }
}

// ========== Layout Management ==========

function recalcPositions() {
    const offset = parseFloat(document.getElementById('offset_mm').value) || 0;
    const width = parseFloat(document.getElementById('wafer_width').value) || 0;
    for (let i = 1; i <= 14; i++) {
        const mm = ((i - 1) * width) + offset;
        document.getElementById(`pos_${i}_mm`).textContent = mm.toFixed(1);
    }
}

function getLayoutPositions() {
    const positions = {};
    for (let i = 1; i <= 14; i++) {
        positions[String(i)] = document.getElementById(`pos_${i}_tf`).value;
    }
    return positions;
}

async function persistLayout() {
    const data = {
        positions: getLayoutPositions(),
        offset_mm: parseFloat(document.getElementById('offset_mm').value),
        wafer_width: parseFloat(document.getElementById('wafer_width').value),
        incidence_angle: document.getElementById('incidence_angle').value,
    };
    await api('/giwaxs/api/layout', 'POST', data);
}

async function updateParams() {
    await persistLayout();
}

async function addOneToBar() {
    const pos = document.getElementById('select_bar_pos').value;
    const tf = document.getElementById('select_thinfilm').value;
    if (!tf) {
        showAlert('error', 'No thin film selected');
        return;
    }
    document.getElementById(`pos_${pos}_tf`).value = tf;
    await persistLayout();
}

async function addAllToBar() {
    const select = document.getElementById('select_thinfilm');
    const tfList = Array.from(select.options).map(o => o.value);
    let tfIdx = 0;
    for (let i = 1; i <= 14; i++) {
        if (tfIdx >= tfList.length) break;
        const input = document.getElementById(`pos_${i}_tf`);
        if (!input.value) {
            input.value = tfList[tfIdx];
            tfIdx++;
        }
    }
    await persistLayout();
    showAlert('success', `Assigned ${tfIdx} thin films to bar`);
}

async function clearLayout() {
    for (let i = 1; i <= 14; i++) {
        document.getElementById(`pos_${i}_tf`).value = '';
    }
    try {
        await api('/giwaxs/api/clear-layout', 'POST');
        showAlert('success', 'Layout cleared');
    } catch (e) {
        showAlert('error', e.message);
    }
}

// ========== Preview & Upload ==========

async function previewAndUpload() {
    try {
        const barName = document.getElementById('bar_name').value || document.getElementById('bar_name_search').value;
        const mfUuid = document.getElementById('bar_mf_uuid').value || document.getElementById('bar_mf_uuid_search').value;
        const alsUuid = document.getElementById('bar_als_uuid').value || document.getElementById('bar_als_uuid_search').value;

        if (!barName) {
            showAlert('error', 'No bar specified. Create a new bar or search for an existing one first.');
            return;
        }
        if (!mfUuid) {
            showAlert('error', 'Bar has not been registered in Crucible yet.');
            return;
        }
        if (!alsUuid) {
            showAlert('error', 'Bar has not been registered in ALS SciCat yet.');
            return;
        }

        // Persist layout first
        await persistLayout();

        showAlert('success', 'Collecting sample info from Crucible...');
        const preview = await api('/giwaxs/api/collect-preview', 'POST');

        if (!preview.samples || preview.samples.length === 0) {
            showAlert('error', 'No samples found in bar layout');
            return;
        }

        let html = `<p><strong>Bar:</strong> ${preview.bar_name}</p>`;
        html += `<p><strong>Crucible UUID:</strong> ${preview.bar_mf_uuid}</p>`;
        html += `<p><strong>ALS Set ID:</strong> ${preview.bar_als_uuid}</p>`;
        html += `<p><strong>Samples:</strong> ${preview.samples.length}</p>`;
        html += '<table class="preview-table"><thead><tr><th>Pos</th><th>Thin Film</th><th>MFID</th></tr></thead><tbody>';
        for (const s of preview.samples) {
            html += `<tr><td>${s.bar_position}</td><td>${s.tf_name}</td><td>${s.tf_mfid}</td></tr>`;
        }
        html += '</tbody></table>';

        showModal('Upload Preview', html, async () => {
            try {
                const result = await api('/giwaxs/api/upload', 'POST');
                showAlert('success', `Successfully uploaded ${result.uploaded_count} samples to database`);
            } catch (e) {
                showAlert('error', `Upload failed: ${e.message}`);
            }
        });
    } catch (e) {
        showAlert('error', e.message);
    }
}
