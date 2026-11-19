// Inorganic XRD Uploader Frontend Script
(function () {
    let _mode = "single";
    let _selectedFiles = [];
    let _assignments = []; // Array of { position, name, uuid, file, sha256 }

    function getSelectedMode() {
        const el = document.querySelector('input[name="xrd-mode"]:checked');
        return el ? el.value : "single";
    }

    window.switchTab = function (tabId) {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tabId));
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('hidden', p.id !== tabId));
        if (tabId === 'tab-recent') {
            loadRecentDatasets();
        }
    };

    window.xrdOnModeChange = function () {
        _mode = getSelectedMode();
        _selectedFiles = [];
        _assignments = [];
        const fileInput = document.getElementById('xrd-file-input');
        if (fileInput) fileInput.value = '';

        const parentSec = document.getElementById('xrd-parent-section');
        const fileHelp = document.getElementById('xrd-file-help');
        const fileLabel = document.getElementById('xrd-file-label');

        if (_mode === 'single') {
            parentSec.classList.add('hidden');
            fileInput.multiple = true;
            fileLabel.textContent = 'Select XRD File(s) (.txt)';
            fileHelp.textContent = 'Select 1 or more XRD data files (one sample per file).';
        } else if (_mode === 'file') {
            parentSec.classList.add('hidden');
            fileInput.multiple = false;
            fileLabel.textContent = 'Select Combined XRD File (.txt)';
            fileHelp.textContent = 'Select 1 combined XRD file with tab-separated sample names on line 1.';
        } else if (_mode === 'parent') {
            parentSec.classList.remove('hidden');
            fileInput.multiple = false;
            fileLabel.textContent = 'Select Combined XRD File (.txt)';
            fileHelp.textContent = 'Select the combined XRD file after resolving child samples.';
        }
        renderTable();
    };

    window.xrdResolveParent = async function () {
        const parentUuid = (document.getElementById('xrd-parent-uuid').value || '').trim();
        if (!parentUuid) {
            showAlert('error', 'Please enter a parent sample UUID first.');
            return;
        }

        try {
            const res = await api('/inorganic-xrd/api/resolve-children', 'POST', { sample_uuid: parentUuid });
            const children = res.children || [];
            if (!children.length) {
                showAlert('warning', 'No child samples found for this parent.');
                return;
            }

            _assignments = children.map((c, i) => ({
                position: `S${String(i + 1).padStart(2, '0')}`,
                name: c.sample_name || '—',
                uuid: c.unique_id || '',
            }));
            renderTable();
            showAlert('success', `Resolved ${children.length} child samples.`);
        } catch (e) {
            showAlert('error', 'Resolve failed: ' + e.message);
        }
    };

    window.xrdRemoveChild = function (index) {
        _assignments.splice(index, 1);
        renderTable();
    };

    window.xrdOnFileSelected = async function () {
        const input = document.getElementById('xrd-file-input');
        _selectedFiles = Array.from(input.files || []);
        if (!_selectedFiles.length) {
            if (_mode !== 'parent') _assignments = [];
            renderTable();
            return;
        }

        if (_mode === 'single') {
            _assignments = [];
            for (let i = 0; i < _selectedFiles.length; i++) {
                const f = _selectedFiles[i];
                let sha256 = '';
                if (window.InstrumentParsers?.computeBlobSha256) {
                    try {
                        sha256 = await window.InstrumentParsers.computeBlobSha256(f);
                    } catch (e) {
                        console.warn('SHA256 error:', e);
                    }
                }
                _assignments.push({
                    position: `F${String(i + 1).padStart(2, '0')}`,
                    name: f.name,
                    uuid: '',
                    file: f,
                    sha256,
                });
            }
            renderTable();
        } else if (_mode === 'file') {
            const file = _selectedFiles[0];
            try {
                if (window.InstrumentParsers?.readXrdFile) {
                    const parsed = await window.InstrumentParsers.readXrdFile(file);
                    _assignments = parsed.map(p => ({
                        position: p.position,
                        name: p.name || '—',
                        uuid: p.uuid || '',
                        file,
                    }));
                } else {
                    _assignments = [{ position: 'S01', name: file.name, uuid: '', file }];
                }
            } catch (e) {
                showAlert('error', 'Failed to parse XRD file header: ' + e.message);
            }
            renderTable();
        } else if (_mode === 'parent') {
            // In parent mode, assignment rows come from resolveParent, file is just attached
            showAlert('info', `File ${_selectedFiles[0]?.name || ''} selected.`);
        }
    };

    function renderTable() {
        const tbody = document.getElementById('xrd-table-body');
        const emptyMsg = document.getElementById('xrd-empty-msg');
        const area = document.getElementById('xrd-assignment-area');
        tbody.innerHTML = '';

        if (!_assignments.length) {
            emptyMsg.classList.remove('hidden');
            area.classList.add('hidden');
            return;
        }

        emptyMsg.classList.add('hidden');
        area.classList.remove('hidden');

        _assignments.forEach((item, idx) => {
            const tr = document.createElement('tr');
            const isParent = _mode === 'parent';

            tr.innerHTML = `
                <td style="font-family: monospace;">${escapeHtml(item.position)}</td>
                <td><span title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</span></td>
                <td>
                    <input type="text" class="xrd-uuid-input" data-index="${idx}"
                           style="width: 100%; font-family: monospace; font-size: 0.9em;"
                           value="${escapeHtml(item.uuid || '')}" ${isParent ? 'readonly style="background:#eee;"' : ''}>
                </td>
                <td style="text-align: center;">
                    ${isParent ? `<button type="button" class="btn btn-secondary btn-sm" onclick="xrdRemoveChild(${idx})">&times;</button>` : '—'}
                </td>
            `;
            tbody.appendChild(tr);
        });

        // Add change listeners for UUID inputs
        tbody.querySelectorAll('.xrd-uuid-input').forEach(inp => {
            inp.addEventListener('input', (e) => {
                const idx = parseInt(e.target.dataset.index, 10);
                if (_assignments[idx]) {
                    _assignments[idx].uuid = e.target.value.trim();
                }
            });
        });
    }

    window.xrdUpload = async function () {
        const statusEl = document.getElementById('xrd-upload-status');
        const uploadBtn = document.getElementById('btn-xrd-upload');
        statusEl.textContent = '';

        if (!_selectedFiles.length) {
            showAlert('error', 'Please select file(s) to upload.');
            return;
        }

        const keywords = (document.getElementById('xrd-keywords').value || '')
            .split(',')
            .map(k => k.trim())
            .filter(Boolean);
        const comments = (document.getElementById('xrd-comments').value || '').trim() || null;

        uploadBtn.disabled = true;
        statusEl.textContent = 'Preparing upload...';

        try {
            if (_mode === 'single') {
                const filesPayload = _assignments.map(a => ({
                    filename: a.name,
                    sha256: a.sha256 || '',
                    sample_uuid: a.uuid || '',
                }));

                const prep = await api('/inorganic-xrd/api/create-uploads', 'POST', {
                    mode: 'single',
                    files: filesPayload,
                    keywords,
                    comments,
                });

                const uploads = prep.uploads || [];
                statusEl.textContent = `Uploading ${uploads.length} dataset file(s)...`;

                for (let i = 0; i < uploads.length; i++) {
                    const u = uploads[i];
                    const fileObj = _assignments[i]?.file || _selectedFiles[i];
                    statusEl.textContent = `Uploading file ${i + 1}/${uploads.length}: ${u.filename}...`;

                    if (window.CrucibleUpload?.uploadFiles) {
                        const res = await window.CrucibleUpload.uploadFiles({
                            datasetMfid: u.dataset_mfid,
                            files: [fileObj],
                            ingestion: () => ({ requested: true, ingestionClass: 'InorganicXRDIngestor' }),
                        });
                        const failed = res.filter(r => !r.ok);
                        if (failed.length) throw new Error(failed.map(f => `${f.file.name}: ${f.error}`).join('; '));
                    }
                }
                showAlert('success', `Successfully created and uploaded ${uploads.length} dataset(s)!`, uploads.length === 1 ? { linkUrl: uploads[0].hub_url } : { linkUrl: hubProjectUrl(currentUserState?.selected_project), linkText: 'Open Project in Crucible Hub \u2197' });
                statusEl.innerHTML = uploads.map(u => `<a href="${escapeHtml(u.hub_url)}" target="_blank">${escapeHtml(u.filename)}</a>`).join(', ');

            } else if (_mode === 'file') {
                const combinedFile = _selectedFiles[0];
                const samplesPayload = _assignments
                    .filter(a => a.uuid)
                    .map(a => ({
                        position: a.position,
                        sample_name: a.name,
                        sample_uuid: a.uuid,
                    }));

                if (!samplesPayload.length) {
                    throw new Error('Please enter at least one Sample UUID.');
                }

                const prep = await api('/inorganic-xrd/api/create-uploads', 'POST', {
                    mode: 'flat_multi',
                    filename: combinedFile.name,
                    samples: samplesPayload,
                    keywords,
                    comments,
                });

                const uploads = prep.uploads || [];
                statusEl.textContent = `Uploading file to ${uploads.length} dataset(s)...`;

                for (let i = 0; i < uploads.length; i++) {
                    const u = uploads[i];
                    statusEl.textContent = `Uploading to dataset ${i + 1}/${uploads.length} (${u.sample_name})...`;
                    if (window.CrucibleUpload?.uploadFiles) {
                        const res = await window.CrucibleUpload.uploadFiles({
                            datasetMfid: u.dataset_mfid,
                            files: [combinedFile],
                            ingestion: () => ({ requested: true, ingestionClass: 'InorganicXRDIngestor' }),
                        });
                        const failed = res.filter(r => !r.ok);
                        if (failed.length) throw new Error(failed.map(f => `${f.file.name}: ${f.error}`).join('; '));
                    }
                }
                showAlert('success', `Successfully uploaded to ${uploads.length} sample dataset(s)!`, uploads.length === 1 ? { linkUrl: uploads[0].hub_url } : { linkUrl: hubProjectUrl(currentUserState?.selected_project), linkText: 'Open Project in Crucible Hub \u2197' });
                statusEl.innerHTML = uploads.map(u => `<a href="${escapeHtml(u.hub_url)}" target="_blank">${escapeHtml(u.sample_name)}</a>`).join(', ');

            } else if (_mode === 'parent') {
                const combinedFile = _selectedFiles[0];
                const parentUuid = (document.getElementById('xrd-parent-uuid').value || '').trim();
                const children = _assignments.filter(a => a.uuid).map(a => ({ uuid: a.uuid, position: a.position, name: a.name }));
                const childUuids = children.map(c => c.uuid);

                if (!parentUuid) throw new Error('Parent Sample UUID is required.');
                if (!childUuids.length) throw new Error('At least one child sample is required.');

                const prep = await api('/inorganic-xrd/api/create-uploads', 'POST', {
                    mode: 'parent_child',
                    filename: combinedFile.name,
                    parent_uuid: parentUuid,
                    children: children,
                    child_uuids: childUuids,
                    keywords,
                    comments,
                });

                const targets = prep.upload_targets || [];
                statusEl.textContent = `Uploading file to parent and ${targets.length - 1} child dataset(s)...`;

                for (let i = 0; i < targets.length; i++) {
                    const dsid = targets[i];
                    statusEl.textContent = `Uploading to dataset ${i + 1}/${targets.length}...`;
                    if (window.CrucibleUpload?.uploadFiles) {
                        const res = await window.CrucibleUpload.uploadFiles({
                            datasetMfid: dsid,
                            files: [combinedFile],
                            ingestion: () => ({ requested: true, ingestionClass: 'InorganicXRDIngestor' }),
                        });
                        const failed = res.filter(r => !r.ok);
                        if (failed.length) throw new Error(failed.map(f => `${f.file.name}: ${f.error}`).join('; '));
                    }
                }
                showAlert('success', `Uploaded to parent and ${targets.length - 1} child datasets!`, { linkUrl: prep.parent_hub_url, linkText: 'Open Parent Dataset in Crucible Hub \u2197' });
                statusEl.innerHTML = `<a href="${escapeHtml(prep.parent_hub_url)}" target="_blank">View Parent Dataset</a>`;
            }
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
            const res = await api('/inorganic-xrd/api/recent-datasets');
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
