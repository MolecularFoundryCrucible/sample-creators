// Inorganic Nirvana Uploader Frontend Script
(function () {
    let _source = 'file';
    let _files = [];
    let _activeFileIdx = 0;
    let _fileAssignments = []; // Array of { filename, file, positions: [...], embeddedInfo }
    let _holdersInfo = null;   // { basename, trays, samples }

    window.switchTab = function (tabId) {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tabId));
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('hidden', p.id !== tabId));
        if (tabId === 'tab-recent') {
            loadRecentDatasets();
        }
    };

    window.nirvanaOnSourceChange = function () {
        const el = document.querySelector('input[name="nirvana-source"]:checked');
        _source = el ? el.value : 'file';

        const holdersSec = document.getElementById('nirvana-holders-section');
        const tabsContainer = document.getElementById('nirvana-file-tabs');
        if (_source === 'holders') {
            holdersSec.classList.remove('hidden');
            tabsContainer.innerHTML = '';
        } else {
            holdersSec.classList.add('hidden');
        }
        renderPositionsTable();
    };

    window.nirvanaResolveHolders = async function () {
        const trayA = (document.getElementById('nirvana-tray-a').value || '').trim();
        const trayB = (document.getElementById('nirvana-tray-b').value || '').trim();

        if (!trayA && !trayB) {
            showAlert('error', 'Please enter at least one Tray UUID.');
            return;
        }

        try {
            const data = await api('/nirvana/api/resolve-holders', 'POST', {
                holder_uuids: [trayA, trayB],
                layout_name: 'Tray 2×8',
            });
            _holdersInfo = data;
            renderPositionsTable();
            showAlert('success', `Resolved holders: ${data.basename}`);
        } catch (e) {
            showAlert('error', 'Failed to resolve holders: ' + e.message);
        }
    };

    window.nirvanaOnFilesSelected = async function () {
        const input = document.getElementById('nirvana-file-input');
        _files = Array.from(input.files || []);
        _fileAssignments = [];
        _activeFileIdx = 0;

        if (!_files.length) {
            renderPositionsTable();
            return;
        }

        if (_source === 'file') {
            for (let i = 0; i < _files.length; i++) {
                const f = _files[i];
                let positions = [];
                let embeddedInfo = { dsid: null, projectId: null, trays: [] };
                try {
                    if (window.InstrumentParsers?.readNirvanaH5Positions) {
                        positions = await window.InstrumentParsers.readNirvanaH5Positions(f, f.name);
                    }
                } catch (e) {
                    console.warn(`Could not read positions for ${f.name}:`, e);
                }

                try {
                    if (window.InstrumentParsers?.readH5EmbeddedInfo) {
                        embeddedInfo = await window.InstrumentParsers.readH5EmbeddedInfo(f, f.name);
                    }
                } catch (e) {
                    console.warn(`Could not read embedded info for ${f.name}:`, e);
                }

                _fileAssignments.push({
                    filename: f.name,
                    file: f,
                    positions,
                    embeddedInfo,
                });
            }
        }
        renderFileTabs();
        renderPositionsTable();
    };

    function renderFileTabs() {
        const tabsContainer = document.getElementById('nirvana-file-tabs');
        tabsContainer.innerHTML = '';
        if (_source !== 'file' || _fileAssignments.length <= 1) return;

        _fileAssignments.forEach((fa, idx) => {
            const btn = document.createElement('button');
            btn.className = `btn tab-btn ${idx === _activeFileIdx ? 'active' : ''}`;
            btn.style.fontSize = '0.85em';
            btn.style.padding = '4px 8px';
            btn.textContent = fa.filename;
            btn.onclick = () => {
                _activeFileIdx = idx;
                renderFileTabs();
                renderPositionsTable();
            };
            tabsContainer.appendChild(btn);
        });
    }

    function renderPositionsTable() {
        const tbody = document.getElementById('nirvana-table-body');
        const emptyMsg = document.getElementById('nirvana-empty-msg');
        const container = document.getElementById('nirvana-table-container');
        tbody.innerHTML = '';

        let items = [];
        if (_source === 'file') {
            if (_fileAssignments.length && _fileAssignments[_activeFileIdx]) {
                items = _fileAssignments[_activeFileIdx].positions;
            }
        } else if (_source === 'holders') {
            if (_holdersInfo && _holdersInfo.samples) {
                items = _holdersInfo.samples;
            }
        }

        if (!items || !items.length) {
            emptyMsg.classList.remove('hidden');
            container.classList.add('hidden');
            return;
        }

        emptyMsg.classList.add('hidden');
        container.classList.remove('hidden');

        items.forEach((p, idx) => {
            const tr = document.createElement('tr');
            const isExcluded = Boolean(p.excluded);
            tr.innerHTML = `
                <td style="font-family: monospace;">${escapeHtml(p.position)}</td>
                <td><span title="${escapeHtml(p.name || '')}">${escapeHtml(p.name || '—')}</span></td>
                <td><span style="font-family: monospace; font-size: 0.9em;">${escapeHtml(p.uuid || '—')}</span></td>
                <td style="text-align: center;">
                    <input type="checkbox" class="nirvana-include-chk" data-index="${idx}" ${!isExcluded ? 'checked' : ''}>
                </td>
            `;
            tbody.appendChild(tr);
        });

        tbody.querySelectorAll('.nirvana-include-chk').forEach(chk => {
            chk.addEventListener('change', (e) => {
                const idx = parseInt(e.target.dataset.index, 10);
                if (_source === 'file' && _fileAssignments[_activeFileIdx]?.positions[idx]) {
                    _fileAssignments[_activeFileIdx].positions[idx].excluded = !e.target.checked;
                } else if (_source === 'holders' && _holdersInfo?.samples[idx]) {
                    _holdersInfo.samples[idx].excluded = !e.target.checked;
                }
            });
        });
    }

    window.nirvanaUpload = async function () {
        const uploadBtn = document.getElementById('btn-nirvana-upload');
        const statusEl = document.getElementById('nirvana-upload-status');
        statusEl.textContent = '';

        if (!_files.length) {
            showAlert('error', 'Please select at least one Nirvana .h5 file.');
            return;
        }

        if (_source === 'holders' && (!_holdersInfo || !_holdersInfo.samples.length)) {
            showAlert('error', 'Please resolve holders before uploading.');
            return;
        }

        const ingestorSelect = document.getElementById('nirvana-ingestor-select').value;
        const keywords = (document.getElementById('nirvana-keywords').value || '')
            .split(',')
            .map(k => k.trim())
            .filter(Boolean);
        const comments = (document.getElementById('nirvana-comments').value || '').trim() || null;

        uploadBtn.disabled = true;
        const releaseGuard = beginUploadTabGuard();
        const progressCtrl = renderSingleUploadProgress(statusEl, {
            label: `Preparing ${_files.length} file(s)`,
            detail: 'Starting Nirvana upload...',
        });

        try {
            const uploadedDatasets = [];

            for (let i = 0; i < _files.length; i++) {
                const file = _files[i];
                let ingestionClass = ingestorSelect;
                if (ingestionClass === 'auto') {
                    if (window.InstrumentParsers?.detectNirvanaIngestor) {
                        ingestionClass = window.InstrumentParsers.detectNirvanaIngestor(file.name);
                    } else {
                        ingestionClass = 'NirvanaMultiPosLineScanIngestor';
                    }
                }

                progressCtrl.update({
                    label: `[${i + 1}/${_files.length}] Uploading ${file.name}`,
                    detail: `Preparing ${file.name}...`,
                    percent: Math.round((i / _files.length) * 100),
                });

                let embeddedDsid = null;
                let sha256 = null;

                if (_source === 'file' && _fileAssignments[i]) {
                    embeddedDsid = _fileAssignments[i].embeddedInfo?.dsid || null;
                } else if (window.InstrumentParsers?.readH5EmbeddedInfo) {
                    try {
                        const info = await window.InstrumentParsers.readH5EmbeddedInfo(file, file.name);
                        embeddedDsid = info.dsid;
                    } catch (e) {
                        console.warn('Failed to read embedded info:', e);
                    }
                }

                if (!embeddedDsid && window.InstrumentParsers?.computeBlobSha256) {
                    try {
                        sha256 = await window.InstrumentParsers.computeBlobSha256(file);
                    } catch (e) {
                        console.warn('Failed to compute sha256:', e);
                    }
                }

                let preparePayload = {};
                if (_source === 'file') {
                    const positions = _fileAssignments[i]?.positions || [];
                    const excludedPositions = positions.filter(p => p.excluded).map(p => p.position);
                    const excludedUuids = positions.filter(p => p.excluded && p.uuid).map(p => p.uuid);

                    preparePayload = {
                        source: 'file',
                        filename: file.name,
                        embedded_dsid: embeddedDsid,
                        sha256: sha256,
                        excluded_positions: excludedPositions,
                        excluded_uuids: excludedUuids,
                        keywords,
                        comments,
                    };
                } else if (_source === 'holders') {
                    const samplePositions = {};
                    const excludedPositions = [];
                    const trayUuids = (_holdersInfo.trays || []).map(t => t.unique_id).filter(Boolean);

                    _holdersInfo.samples.forEach(s => {
                        if (s.excluded) {
                            excludedPositions.push(s.position);
                        } else if (s.uuid) {
                            samplePositions[s.position] = {
                                sample_uuid: s.uuid,
                                sample_name: s.name,
                                tray_uuid: s.tray_uuid,
                                tray_name: s.tray_name,
                            };
                        }
                    });

                    preparePayload = {
                        source: 'holders',
                        filename: file.name,
                        embedded_dsid: embeddedDsid,
                        sha256: sha256,
                        sample_positions: samplePositions,
                        tray_uuids: trayUuids,
                        trays: _holdersInfo.trays || [],
                        excluded_positions: excludedPositions,
                        keywords,
                        comments,
                    };
                }

                const prep = await api('/nirvana/api/prepare-upload', 'POST', preparePayload);
                const datasetMfid = prep.dataset_mfid;

                if (window.CrucibleUpload?.uploadFiles) {
                    const res = await window.CrucibleUpload.uploadFiles({
                        datasetMfid,
                        files: [file],
                        ingestion: () => ({ requested: true, ingestionClass }),
                        onProgress: (f, p) => {
                            const filePct = f.size ? Math.min(100, Math.round((p.uploadedBytes / f.size) * 100)) : 100;
                            const overallPct = Math.round(((i + (filePct / 100)) / _files.length) * 100);
                            progressCtrl.update({
                                label: `[${i + 1}/${_files.length}] Uploading ${file.name}`,
                                detail: `Uploading ${file.name} (${filePct}%)...`,
                                percent: overallPct,
                            });
                        },
                    });
                    const failed = res.filter(r => !r.ok);
                    if (failed.length) throw new Error(failed.map(f => `${f.file.name}: ${f.error}`).join('; '));
                }

                uploadedDatasets.push({ filename: file.name, datasetMfid, hubUrl: prep.hub_url });
            }

            progressCtrl.update({
                label: 'Upload Complete',
                detail: `Uploaded ${uploadedDatasets.length} scan(s)`,
                percent: 100,
                isDone: true,
            });
            progressCtrl.hideNotice();

            showAlert('success', `Successfully uploaded ${uploadedDatasets.length} Nirvana scan(s)!`, uploadedDatasets.length === 1 ? { linkUrl: uploadedDatasets[0].hubUrl } : { linkUrl: hubProjectUrl(currentUserState?.selected_project), linkText: 'Open Project in Crucible Hub \u2197' });
            statusEl.innerHTML = uploadedDatasets.map(d => `<a href="${escapeHtml(d.hubUrl)}" target="_blank">${escapeHtml(d.filename)}</a>`).join(', ');
        } catch (e) {
            showAlert('error', 'Upload failed: ' + e.message);
            statusEl.textContent = 'Upload failed: ' + e.message;
        } finally {
            releaseGuard();
            uploadBtn.disabled = false;
        }
    };

    window.loadRecentDatasets = async function () {
        const tbody = document.getElementById('recent-table-body');
        tbody.innerHTML = '<tr><td colspan="5">Loading...</td></tr>';
        try {
            const res = await api('/nirvana/api/recent-datasets');
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
