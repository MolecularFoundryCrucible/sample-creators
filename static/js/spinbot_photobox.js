// SpinBot Photobox Carrier Uploader Frontend Script
(function () {
    const MFID_RE = /^[0-9a-hjkmnp-tv-z]{26}$/i;
    const TRAY1_POSITIONS = ['A1','A2','A3','A4','B1','B2','B3','B4'];
    const TRAY2_POSITIONS = ['C1','C2','C3','C4','D1','D2','D3','D4'];

    let _carrier = { uuid: '', name: '', pendingNew: false };
    let _tray1 = { uuid: '', samples: [] };
    let _tray2 = { uuid: '', samples: [] };

    window.switchTab = function (tabId) {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tabId));
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('hidden', p.id !== tabId));
        if (tabId === 'tab-recent') {
            loadRecentDatasets();
        }
    };

    function updateCarrierDisplay() {
        const display = document.getElementById('pb-carrier-display');
        if (!display) return;
        if (_carrier.pendingNew) {
            display.textContent = `${_carrier.name} (will be created on upload)`;
            display.style.color = '#d97706';
        } else if (_carrier.uuid) {
            display.textContent = `${_carrier.name || 'Carrier'} (${_carrier.uuid})`;
            display.style.color = '#059669';
        } else {
            display.textContent = '—';
            display.style.color = '#333';
        }
    }

    window.pbLookupCarrier = async function () {
        const query = (document.getElementById('pb-carrier-input').value || '').trim();
        if (!query) {
            showAlert('error', 'Enter a carrier UUID or name first.');
            return;
        }

        const body = MFID_RE.test(query) ? { sample_unique_id: query } : { sample_name: query };
        try {
            const data = await api('/spinbot-photobox/api/lookup-carrier', 'POST', body);
            _carrier = {
                uuid: data.unique_id,
                name: data.sample_name || data.unique_id,
                pendingNew: false,
            };
            updateCarrierDisplay();
            showAlert('success', `Found carrier: ${_carrier.name}`);
        } catch (e) {
            showAlert('error', 'Lookup failed: ' + e.message);
        }
    };

    window.pbQueueNewCarrier = async function () {
        try {
            const data = await api('/spinbot-photobox/api/next-carrier-name');
            _carrier = {
                uuid: '',
                name: data.sample_name,
                pendingNew: true,
            };
            updateCarrierDisplay();
            showAlert('info', `Queued new carrier: ${_carrier.name}`);
        } catch (e) {
            showAlert('error', 'Failed to get carrier name: ' + e.message);
        }
    };

    window.pbPrintCarrier = async function () {
        if (!_carrier.uuid) {
            showAlert('error', 'Please look up an existing carrier to print its barcode.');
            return;
        }
        const printer = document.getElementById('pb-printer')?.value || '';
        try {
            await api('/spinbot-photobox/api/print-carrier', 'POST', {
                printer_id: printer,
                carrier_uuid: _carrier.uuid,
                carrier_name: _carrier.name,
            });
            showAlert('success', `Printed barcode for ${_carrier.name}`);
        } catch (e) {
            showAlert('error', 'Print failed: ' + e.message);
        }
    };

    function renderTrayGrid(containerId, samples, positions) {
        const el = document.getElementById(containerId);
        if (!samples || !samples.length) {
            el.innerHTML = '<span class="info-text">No samples in tray.</span>';
            return;
        }

        const rows = positions.map((pos, idx) => {
            const s = samples[idx];
            const name = s ? (s.sample_name || '—') : '—';
            const uuid = s ? (s.unique_id ? s.unique_id.slice(-8) : '') : '';
            return `<div style="display: flex; justify-content: space-between; padding: 3px 0; border-bottom: 1px solid #eee;">
                <span style="font-family: monospace; font-weight: bold; width: 30px;">${escapeHtml(pos)}</span>
                <span style="flex-grow: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHtml(name)}">${escapeHtml(name)}</span>
                <span style="font-family: monospace; color: #888; margin-left: 8px;">${escapeHtml(uuid)}</span>
            </div>`;
        }).join('');

        el.innerHTML = rows;
    }

    window.pbResolveTray = async function (num) {
        const uuidInp = document.getElementById(`pb-tray${num}-uuid`);
        const uuid = (uuidInp ? uuidInp.value : '').trim();
        if (!uuid) {
            showAlert('error', `Enter Tray ${num} UUID first.`);
            return;
        }

        try {
            const data = await api('/spinbot-photobox/api/resolve-children', 'POST', { sample_uuid: uuid });
            const samples = data.children || [];
            if (num === 1) {
                _tray1 = { uuid, samples };
                renderTrayGrid('pb-tray1-grid', samples, TRAY1_POSITIONS);
            } else {
                _tray2 = { uuid, samples };
                renderTrayGrid('pb-tray2-grid', samples, TRAY2_POSITIONS);
            }
            showAlert('success', `Resolved Tray ${num} with ${samples.length} sample(s).`);
        } catch (e) {
            showAlert('error', `Failed to resolve Tray ${num}: ` + e.message);
        }
    };

    window.pbUpload = async function () {
        const uploadBtn = document.getElementById('btn-pb-upload');
        const statusEl = document.getElementById('pb-upload-status');
        statusEl.textContent = '';

        const photoInput = document.getElementById('pb-photo-file');
        const photoFile = photoInput && photoInput.files ? photoInput.files[0] : null;
        if (!photoFile) {
            showAlert('error', 'Please select a carrier photo file.');
            return;
        }

        if (!_carrier.uuid && !_carrier.pendingNew) {
            showAlert('error', 'Please look up or generate a new carrier first.');
            return;
        }

        const samplePositions = {};
        _tray1.samples.forEach((s, idx) => {
            if (idx < TRAY1_POSITIONS.length && s.unique_id) {
                samplePositions[TRAY1_POSITIONS[idx]] = s.unique_id;
            }
        });
        _tray2.samples.forEach((s, idx) => {
            if (idx < TRAY2_POSITIONS.length && s.unique_id) {
                samplePositions[TRAY2_POSITIONS[idx]] = s.unique_id;
            }
        });

        const keywords = (document.getElementById('pb-keywords').value || '')
            .split(',')
            .map(k => k.trim())
            .filter(Boolean);
        const comments = (document.getElementById('pb-comments').value || '').trim() || null;

        uploadBtn.disabled = true;
        statusEl.textContent = 'Preparing carrier photo dataset...';

        try {
            const prep = await api('/spinbot-photobox/api/prepare-upload', 'POST', {
                pending_new_carrier: _carrier.pendingNew,
                carrier_uuid: _carrier.uuid,
                carrier_name: _carrier.name,
                tray1_uuid: _tray1.uuid || null,
                tray2_uuid: _tray2.uuid || null,
                sample_positions: samplePositions,
                filename: photoFile.name,
                keywords,
                comments,
            });

            _carrier.uuid = prep.carrier_uuid;
            _carrier.name = prep.carrier_name;
            _carrier.pendingNew = false;
            updateCarrierDisplay();

            const datasetMfid = prep.dataset_mfid;
            statusEl.textContent = `Uploading photo file to dataset ${datasetMfid}...`;

            if (window.CrucibleUpload?.uploadFiles) {
                const res = await window.CrucibleUpload.uploadFiles({
                    datasetMfid,
                    files: [photoFile],
                    ingestion: () => ({ requested: true }),
                });
                const failed = res.filter(r => !r.ok);
                if (failed.length) throw new Error(failed.map(f => `${f.file.name}: ${f.error}`).join('; '));
            }

            statusEl.textContent = 'Triggering carrier segmentation pipeline...';
            await api('/spinbot-photobox/api/postprocess', 'POST', { dataset_id: datasetMfid });

            showAlert('success', 'Carrier photo uploaded and segmentation requested!');
            statusEl.innerHTML = `<a href="${escapeHtml(prep.hub_url)}" target="_blank">View Dataset in Crucible Hub (${escapeHtml(datasetMfid)})</a>`;
        } catch (e) {
            showAlert('error', 'Upload failed: ' + e.message);
            statusEl.textContent = 'Upload failed: ' + e.message;
        } finally {
            uploadBtn.disabled = false;
        }
    };

    window.loadRecentDatasets = async function () {
        const tbody = document.getElementById('recent-table-body');
        tbody.innerHTML = '<tr><td colspan="5">Loading...</td></tr>';
        try {
            const res = await api('/spinbot-photobox/api/recent-datasets');
            const rows = res.rows || [];
            if (!rows.length) {
                tbody.innerHTML = '<tr><td colspan="5">No recent datasets found.</td></tr>';
                return;
            }
            tbody.innerHTML = rows.map(r => `
                <tr>
                    <td>${escapeHtml(r.Date || '')}</td>
                    <td>${escapeHtml(r.User || '')}</td>
                    <td>${escapeHtml(r['Dataset Name'] || '')}</td>
                    <td>${escapeHtml(r.Measurement || '')}</td>
                    <td>${escapeHtml(r.Comment || '')}</td>
                </tr>
            `).join('');
        } catch (e) {
            tbody.innerHTML = `<tr><td colspan="5">Failed to load datasets: ${escapeHtml(e.message)}</td></tr>`;
        }
    };

    document.addEventListener('DOMContentLoaded', () => {
        loadUserState();
        populatePrinterSelect('pb-printer');
    });
})();
