// Shared client-side utilities for migrated uploaders.

function switchTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabId);
    });
    document.querySelectorAll('.tab-panel').forEach(panel => {
        const isMatch = (panel.id === tabId);
        panel.classList.toggle('hidden', !isMatch);
        panel.style.display = isMatch ? '' : 'none';
    });
    if (tabId === 'tab-recent' && typeof loadRecentDatasets === 'function') {
        loadRecentDatasets();
    }
}

// Sample disambiguation modal when multiple samples match a sample name (HTTP 409)
function showAmbiguousSampleModal(candidates, onSelect) {
    let html = '<p class="help-text">Multiple samples found in this project. Please select one:</p>';
    html += '<div style="max-height:260px; overflow-y:auto; margin:10px 0;">';
    html += '<table class="preview-table" style="width:100%;">';
    html += '<thead><tr><th>Sample Name</th><th>MFID</th><th>Action</th></tr></thead><tbody>';
    candidates.forEach((c, idx) => {
        html += `<tr>
            <td><strong>${escapeHtml(c.sample_name || '')}</strong></td>
            <td><code>${escapeHtml(c.unique_id || '')}</code></td>
            <td><button class="btn btn-sm btn-primary" onclick="window._selectSampleCandidate(${idx})">Select</button></td>
        </tr>`;
    });
    html += '</tbody></table></div>';

    window._selectSampleCandidate = (idx) => {
        closeModal();
        onSelect(candidates[idx]);
    };

    showModal('Disambiguate Sample', html, () => {}, 'Close');
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

async function fetchLogbookRows(apiBase, limit = 100) {
    const res = await api(`${apiBase}/api/recent-datasets?limit=${limit}`);
    return res.rows || [];
}

function renderLogbookTable(rows, tableBodyId, columns) {
    const tbody = document.getElementById(tableBodyId);
    if (!tbody) return;
    if (!rows.length) {
        tbody.innerHTML = `<tr><td colspan="${columns.length}">No datasets found in selected project.</td></tr>`;
        return;
    }
    let html = '';
    for (const row of rows) {
        html += '<tr>';
        for (const col of columns) {
            const val = row[col] || '';
            if (col === 'Dataset ID' && val) {
                html += `<td><code>${escapeHtml(val)}</code></td>`;
            } else {
                html += `<td>${escapeHtml(val)}</td>`;
            }
        }
        html += '</tr>';
    }
    tbody.innerHTML = html;
}

function downloadLogbookCsv(apiBase, filename) {
    const base = typeof BASE_URL !== 'undefined' ? BASE_URL : '';
    window.location.href = `${base}${apiBase}/api/recent-datasets/${filename}`;
}
