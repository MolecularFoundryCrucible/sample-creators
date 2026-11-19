// SpinBot SpinRun Uploader Frontend Script
(function () {
    let _h5File = null;
    let _yamlFile = null;
    let _embeddedInfo = { dsid: null, projectId: null, trays: [] };

    window.switchTab = function (tabId) {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tabId));
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('hidden', p.id !== tabId));
        if (tabId === 'tab-recent') {
            loadRecentDatasets();
        }
    };

    window.onH5FileSelected = async function () {
        const input = document.getElementById('spinrun-h5-file');
        _h5File = input.files && input.files[0] ? input.files[0] : null;
        _embeddedInfo = { dsid: null, projectId: null, trays: [] };

        const dsidInp = document.getElementById('spinrun-extracted-dsid');
        const traysSec = document.getElementById('spinrun-trays-section');
        const traysList = document.getElementById('spinrun-trays-list');

        dsidInp.value = '';
        traysList.innerHTML = '';
        traysSec.classList.add('hidden');

        if (!_h5File) return;

        try {
            if (window.InstrumentParsers?.readH5EmbeddedInfo) {
                _embeddedInfo = await window.InstrumentParsers.readH5EmbeddedInfo(_h5File, _h5File.name);
                if (_embeddedInfo.dsid) {
                    dsidInp.value = _embeddedInfo.dsid;
                }
                if (_embeddedInfo.trays && _embeddedInfo.trays.length > 0) {
                    traysList.innerHTML = _embeddedInfo.trays.map(t =>
                        `<li style="padding: 4px 0; border-bottom: 1px solid #ddd;">
                            <strong>${escapeHtml(t.name || 'Unnamed Tray')}</strong> <span style="font-family: monospace; color: #666;">(${escapeHtml(t.mfid)})</span>
                         </li>`
                    ).join('');
                    traysSec.classList.remove('hidden');
                    populatePrinterSelect('spinrun-printer');
                }
            }
        } catch (e) {
            console.warn('Failed to parse H5 embedded info:', e);
        }
    };

    window.spinrunPrintTrays = async function () {
        const trays = _embeddedInfo.trays || [];
        if (!trays.length) {
            showAlert('warning', 'No trays found to print.');
            return;
        }

        const printerSelect = document.getElementById('spinrun-printer');
        const printerId = printerSelect ? printerSelect.value : '';
        const printBtn = document.getElementById('btn-print-trays');
        const statusEl = document.getElementById('spinrun-print-status');

        printBtn.disabled = true;
        statusEl.textContent = 'Sending print jobs...';

        try {
            const res = await api('/spinbot-spinrun/api/print-trays', 'POST', {
                trays,
                printer_id: printerId,
            });
            showAlert('success', `Sent ${res.count} tray label(s) to printer!`);
            statusEl.textContent = `Printed ${res.count} barcode(s).`;
        } catch (e) {
            showAlert('error', 'Print failed: ' + e.message);
            statusEl.textContent = 'Print failed: ' + e.message;
        } finally {
            printBtn.disabled = false;
        }
    };

    window.spinrunUpload = async function () {
        const uploadBtn = document.getElementById('btn-spinrun-upload');
        const statusEl = document.getElementById('spinrun-upload-status');
        statusEl.textContent = '';

        const h5Input = document.getElementById('spinrun-h5-file');
        _h5File = h5Input.files && h5Input.files[0] ? h5Input.files[0] : null;
        if (!_h5File) {
            showAlert('error', 'Please select a SpinRun .h5 file.');
            return;
        }

        const yamlInput = document.getElementById('spinrun-yaml-file');
        _yamlFile = yamlInput.files && yamlInput.files[0] ? yamlInput.files[0] : null;

        const sampleUuid = (document.getElementById('spinrun-sample-uuid').value || '').trim() || null;
        const keywords = (document.getElementById('spinrun-keywords').value || '')
            .split(',')
            .map(k => k.trim())
            .filter(Boolean);
        const comments = (document.getElementById('spinrun-comments').value || '').trim() || null;

        uploadBtn.disabled = true;
        statusEl.textContent = 'Preparing SpinRun dataset...';

        try {
            let sha256 = '';
            if (!_embeddedInfo.dsid && window.InstrumentParsers?.computeBlobSha256) {
                try {
                    sha256 = await window.InstrumentParsers.computeBlobSha256(_h5File);
                } catch (e) {
                    console.warn('Could not compute SHA-256:', e);
                }
            }

            const prep = await api('/spinbot-spinrun/api/create-upload', 'POST', {
                filename: _h5File.name,
                yaml_filename: _yamlFile ? _yamlFile.name : null,
                embedded_dsid: _embeddedInfo.dsid || null,
                sha256: sha256 || null,
                sample_uuid: sampleUuid,
                keywords,
                comments,
            });

            const datasetMfid = prep.dataset_mfid;
            statusEl.textContent = `Uploading files to dataset ${datasetMfid}...`;

            // If .yaml companion is present, upload it first with ingestion requested=false
            if (_yamlFile && window.CrucibleUpload?.uploadFiles) {
                statusEl.textContent = `Uploading companion ${_yamlFile.name}...`;
                const res = await window.CrucibleUpload.uploadFiles({
                    datasetMfid,
                    files: [_yamlFile],
                    ingestion: () => ({ requested: false }),
                });
                const failed = res.filter(r => !r.ok);
                if (failed.length) throw new Error(failed.map(f => `${f.file.name}: ${f.error}`).join('; '));
            }

            // Upload .h5 file and request SpinbotSpinRunIngestor
            statusEl.textContent = `Uploading ${_h5File.name}...`;
            if (window.CrucibleUpload?.uploadFiles) {
                const res = await window.CrucibleUpload.uploadFiles({
                    datasetMfid,
                    files: [_h5File],
                    ingestion: () => ({ requested: true, ingestionClass: 'SpinbotSpinRunIngestor' }),
                });
                const failed = res.filter(r => !r.ok);
                if (failed.length) throw new Error(failed.map(f => `${f.file.name}: ${f.error}`).join('; '));
            }

            showAlert('success', 'SpinBot SpinRun uploaded successfully!', { linkUrl: prep.hub_url || hubDatasetUrl(datasetMfid) });
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
            const res = await api('/spinbot-spinrun/api/recent-datasets');
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
    });
})();
