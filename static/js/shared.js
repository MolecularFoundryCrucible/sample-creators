// ========== API Helpers ==========

async function api(url, method = 'GET', body = null) {
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (body) opts.body = JSON.stringify(body);
    const fullUrl = (typeof BASE_URL !== 'undefined' ? BASE_URL : '') + url;
    const res = await fetch(fullUrl, opts);
    const data = await res.json();
    if (!res.ok) {
        const err = new Error(data.error || `Request failed (${res.status})`);
        err.status = res.status;
        err.data = data;
        throw err;
    }
    return data;
}

// ========== Printer selection ==========

// Populates a <select> with the printers crucible-api has ever seen a status heartbeat
// from (routes/shared.py::list_printers()), labeled with live online/offline state.
// Shared by every page with a barcode-printer picker, instead of a hardcoded list.
async function populatePrinterSelect(selectId) {
    const select = document.getElementById(selectId);
    if (!select) return;
    const previous = select.value;
    select.innerHTML = '<option value="">Loading printers…</option>';
    try {
        const data = await api('/print/api/printers');
        const printers = [...data.printers].sort((a, b) => a.printer_id.localeCompare(b.printer_id));

        if (!printers.length) {
            select.innerHTML = '<option value="">No printers found</option>';
            return;
        }

        select.innerHTML = '';
        for (const p of printers) {
            const opt = document.createElement('option');
            opt.value = p.printer_id;
            opt.textContent = `${p.printer_id} — ${p.online ? 'online' : 'offline'}`;
            select.appendChild(opt);
        }
        if (printers.some(p => p.printer_id === previous)) select.value = previous;
    } catch (e) {
        select.innerHTML = '<option value="">Failed to load printers</option>';
        showAlert('error', `Could not load printers: ${e.message}`);
    }
}

// ========== Alert System ==========

function hubBaseUrl() {
    const raw = (typeof CRUCIBLE_HUB_URL !== 'undefined' && CRUCIBLE_HUB_URL)
        ? CRUCIBLE_HUB_URL
        : 'https://crucible.lbl.gov/hub';
    return String(raw).replace(/\/+$/, '');
}

function hubDatasetUrl(datasetId) {
    return datasetId ? `${hubBaseUrl()}/datasets/${encodeURIComponent(datasetId)}` : '';
}

function hubProjectUrl(projectId) {
    return projectId ? `${hubBaseUrl()}/projects/${encodeURIComponent(projectId)}` : '';
}

function showAlert(type, message, options = {}) {
    const container = document.getElementById('alert-container');
    if (!container) return;
    const alert = document.createElement('div');
    alert.className = `alert alert-${type}`;

    const linkUrl = typeof options?.linkUrl === 'string' && /^(https?:\/\/|\/)/i.test(options.linkUrl) ? options.linkUrl : '';

    if (!linkUrl) {
        alert.textContent = message;
        container.appendChild(alert);
        const durationMs = options?.durationMs ?? 5000;
        setTimeout(() => alert.remove(), durationMs);
        return;
    }

    alert.classList.add('alert-has-link');

    const body = document.createElement('div');
    body.className = 'alert-body';

    const msgEl = document.createElement('div');
    msgEl.className = 'alert-message';
    msgEl.textContent = message;
    body.appendChild(msgEl);

    const link = document.createElement('a');
    link.className = 'alert-link';
    link.href = linkUrl;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = options.linkText || 'Open in Crucible Hub \u2197';
    body.appendChild(link);

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'alert-close';
    closeBtn.setAttribute('aria-label', 'Dismiss');
    closeBtn.innerHTML = '&times;';
    closeBtn.onclick = () => alert.remove();

    alert.appendChild(body);
    alert.appendChild(closeBtn);
    container.appendChild(alert);

    const durationMs = options?.durationMs ?? 15000;
    let timeoutId = setTimeout(() => alert.remove(), durationMs);

    alert.addEventListener('mouseenter', () => {
        if (timeoutId) {
            clearTimeout(timeoutId);
            timeoutId = null;
        }
    });

    alert.addEventListener('mouseleave', () => {
        if (!timeoutId) {
            timeoutId = setTimeout(() => alert.remove(), durationMs);
        }
    });
}

// ========== Modal ==========

// `altAction` ({label, onClick}) adds a second, non-primary choice next to Confirm, for
// questions that are a fork rather than a yes/no.
function showModal(title, bodyHTML, onConfirm, confirmLabel = 'Confirm', altAction = null) {
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body').innerHTML = bodyHTML;
    document.getElementById('modal-overlay').classList.remove('hidden');

    const confirmBtn = document.getElementById('modal-confirm');
    // Remove old listeners by cloning
    const newBtn = confirmBtn.cloneNode(true);
    newBtn.textContent = confirmLabel;
    confirmBtn.parentNode.replaceChild(newBtn, confirmBtn);
    newBtn.addEventListener('click', () => {
        closeModal();
        onConfirm();
    });

    const altBtn = document.getElementById('modal-alt');
    const newAltBtn = altBtn.cloneNode(true);
    altBtn.parentNode.replaceChild(newAltBtn, altBtn);
    newAltBtn.classList.toggle('hidden', !altAction);
    if (altAction) {
        newAltBtn.textContent = altAction.label;
        newAltBtn.addEventListener('click', () => {
            closeModal();
            altAction.onClick();
        });
    }
}

// Positions whose thin film name matched zero or several samples. These are
// dropped from the upload, so the preview has to call them out explicitly.
function renderSkippedWarning(skipped) {
    if (!skipped || !skipped.length) return '';
    const rows = skipped.map(s =>
        `<li>Position ${escapeHtml(s.position)}: <strong>${escapeHtml(s.tf_name)}</strong> — ${escapeHtml(s.reason)}</li>`
    ).join('');
    return `<div class="preview-skipped">
        <strong>${skipped.length} position(s) will NOT be uploaded:</strong>
        <ul>${rows}</ul>
    </div>`;
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
}

function closeModal() {
    document.getElementById('modal-overlay').classList.add('hidden');
}

// ========== User Login/Logout ==========

let currentUserState = null;
let userStateEpoch = 0;

// ========== Login/Logout Reset Hooks ==========

// Pages register callbacks here to reset their own form state. Several layers can be
// registered on one page (shared deposition UI plus the per-tool form), so all of them run.
const logoutResetFns = [];

function registerLogoutReset(fn) {
    logoutResetFns.push(fn);
}

async function loginUser(event) {
    event?.preventDefault();
    const userReference = document.getElementById('email').value.trim();
    if (!userReference) {
        showAlert('error', 'Please enter an email or username');
        return;
    }
    try {
        const user = await api('/api/user/login', 'POST', { user_ref: userReference });
        userStateEpoch++;
        populateUserInfo(user);
        showAlert('success', `Logged in as ${user.user_name}`);
    } catch (e) {
        showAlert('error', e.message);
    }
}

async function logoutUser() {
    try {
        await api('/api/user/logout', 'POST');
        userStateEpoch++;
        clearUserInfo();
        showAlert('success', 'Logged out');
    } catch (e) {
        showAlert('error', e.message);
    } finally {
        for (const fn of logoutResetFns) await fn();
    }
}

function loadUserState() {
    const epoch = userStateEpoch;
    const p = (async () => {
        try {
            const user = await api('/api/user');
            if (epoch === userStateEpoch) populateUserInfo(user);
            return currentUserState;
        } catch {
            // Not logged in, that's fine
            if (epoch === userStateEpoch) {
                currentUserState = null;
                window.__crucibleUser = null;
            }
            return currentUserState;
        }
    })();
    window.__crucibleUserPromise = p;
    return p;
}

function populateUserInfo(user) {
    currentUserState = user;
    window.__crucibleUser = user;
    // React islands (synthesis, traveler) follow the login through this event.
    window.dispatchEvent(new CustomEvent('crucible:user', { detail: user }));
    document.getElementById('email').value = user.login_reference || user.email || user.username || '';
    document.getElementById('username').value = user.user_name;

    const projectSelect = document.getElementById('project');
    projectSelect.innerHTML = '';
    for (const p of user.projects) {
        const opt = document.createElement('option');
        opt.value = p;
        opt.textContent = p;
        if (p === user.selected_project) opt.selected = true;
        projectSelect.appendChild(opt);
    }

    // Update nav
    document.getElementById('nav-user-info').textContent = user.user_name;

    loadSampleTypes();
}

function clearUserInfo() {
    currentUserState = null;
    window.__crucibleUser = null;
    window.dispatchEvent(new CustomEvent('crucible:user', { detail: null }));
    document.getElementById('email').value = '';
    document.getElementById('username').value = '';
    document.getElementById('project').innerHTML = '';
    document.getElementById('nav-user-info').textContent = '';
    const sessionEl = document.getElementById('session_name');
    if (sessionEl) sessionEl.value = '';
    const tagsEl = document.getElementById('tags');
    if (tagsEl) tagsEl.value = '';
    const commentsEl = document.getElementById('comments');
    if (commentsEl) commentsEl.value = '';
    sampleTypeOptions = [];
}

async function setProject(nextProject) {
    const projectSelect = document.getElementById('project');
    const previous = currentUserState?.selected_project || '';
    const project = typeof nextProject === 'string' ? nextProject : (projectSelect ? projectSelect.value : '');
    const epoch = ++userStateEpoch;
    if (projectSelect && projectSelect.value !== project) {
        projectSelect.value = project;
    }
    try {
        const res = await api('/api/user/project', 'POST', { project });
        if (epoch !== userStateEpoch) return;
        if (projectSelect && Array.from(projectSelect.options).some(o => o.value === project)) {
            projectSelect.value = project;
        }
        const updatedUser = res?.user || (currentUserState ? { ...currentUserState, selected_project: project } : null);
        if (updatedUser) {
            currentUserState = updatedUser;
            window.__crucibleUser = updatedUser;
            window.dispatchEvent(new CustomEvent('crucible:user', { detail: updatedUser }));
        }
        await loadSampleTypes();
    } catch (e) {
        if (projectSelect && Array.from(projectSelect.options).some(o => o.value === previous)) {
            projectSelect.value = previous;
        }
        if (typeof nextProject === 'string') throw e;
        showAlert('error', e.message);
    }
}
window.setProject = setProject;

// ========== Generic Field Reset ==========

// Resets each matched form element back to the state defined by its original
// HTML (the browser's defaultValue/defaultChecked/option.defaultSelected),
// undoing any values the user typed in. File inputs are cleared outright.
function resetFieldsToDefault(selector, root = document) {
    root.querySelectorAll(selector).forEach(el => {
        if (el.tagName === 'SELECT') {
            const defaultOption = Array.from(el.options).find(o => o.defaultSelected);
            el.selectedIndex = defaultOption ? defaultOption.index : 0;
        } else if (el.type === 'checkbox' || el.type === 'radio') {
            el.checked = el.defaultChecked;
        } else if (el.type === 'file') {
            el.value = '';
        } else {
            el.value = el.defaultValue;
        }
    });
}
// ========== Tabs ==========

function switchTab(tabId) {
    document.querySelectorAll('.tab-panel').forEach(el => el.classList.add('hidden'));
    document.getElementById(tabId)?.classList.remove('hidden');

    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelector(`.tab-btn[data-tab="${tabId}"]`)?.classList.add('active');
}

// ========== Barcode Printing ==========

function printBarcode(barcode, label) {
    // TODO: integrate with label printer (e.g. Dymo, Zebra ZPL, or browser print dialog)
    showAlert('info', `Print barcode: ${barcode}${label ? ' — ' + label : ''} (not yet implemented)`);
}

// ========== Thin Film Dropdown ==========

function populateThinFilmDropdown(thinFilms) {
    const select = document.getElementById('select_thinfilm');
    select.innerHTML = '';
    for (const tf of thinFilms) {
        const opt = document.createElement('option');
        opt.value = tf;
        opt.textContent = tf;
        select.appendChild(opt);
    }
}

// ========== Sample Type Typeahead ==========

// Distinct types for the selected project, fetched once per project and filtered in the
// browser. A type someone else creates mid-session won't show up until the page reloads.
let sampleTypeOptions = [];

async function loadSampleTypes() {
    try {
        sampleTypeOptions = await api('/api/sample-types');
    } catch {
        sampleTypeOptions = [];
    }
}

function initSampleTypeTypeahead() {
    const input = document.getElementById('sample_type');
    const results = document.getElementById('sample_type_results');
    if (!input || !results) return;

    const close = () => results.classList.add('hidden');

    input.addEventListener('input', () => {
        const q = input.value.trim().toLowerCase();
        const matches = q ? sampleTypeOptions.filter(t => t.toLowerCase().includes(q)) : [];
        if (!matches.length) { close(); return; }
        results.innerHTML = matches.map(t =>
            `<button type="button" class="typeahead-item">${escapeHtml(t)}</button>`
        ).join('');
        results.classList.remove('hidden');
        results.querySelectorAll('button').forEach((btn, i) =>
            btn.addEventListener('click', () => { input.value = matches[i]; close(); })
        );
    });

    input.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
    document.addEventListener('mousedown', e => {
        if (!results.contains(e.target) && e.target !== input) close();
    });
}

document.addEventListener('DOMContentLoaded', initSampleTypeTypeahead);

// ========== Upload Tab Guard & Single Progress Helpers ==========

let _activeUploadGuards = 0;

function _onUploadBeforeUnload(event) {
    if (_activeUploadGuards > 0) {
        event.preventDefault();
        event.returnValue = '';
    }
}

if (typeof window !== 'undefined') {
    window.addEventListener('beforeunload', _onUploadBeforeUnload);
}

function beginUploadTabGuard() {
    _activeUploadGuards += 1;
    let released = false;
    return function release() {
        if (!released) {
            released = true;
            _activeUploadGuards = Math.max(0, _activeUploadGuards - 1);
        }
    };
}

function renderSingleUploadProgress(containerEl, opts = {}) {
    if (!containerEl) {
        return {
            update: () => {},
            hideNotice: () => {},
        };
    }
    const initialLabel = opts.label || 'Uploading...';
    const initialDetail = opts.detail || '';

    containerEl.innerHTML = `
        <div class="upload-active-notice">
            Upload in progress -- please do not close or refresh this browser tab until the upload is finished.
        </div>
        <div class="upload-step is-active">
            <div class="upload-step-header">
                <div>
                    <span class="upload-step-label"></span>
                    <div class="upload-step-detail"></div>
                </div>
                <span class="upload-step-pct">0%</span>
            </div>
            <div class="upload-step-bar">
                <div class="upload-step-bar-fill is-active" style="width: 0%;"></div>
            </div>
        </div>
    `;

    const noticeEl = containerEl.querySelector('.upload-active-notice');
    const stepEl = containerEl.querySelector('.upload-step');
    const labelEl = containerEl.querySelector('.upload-step-label');
    const detailEl = containerEl.querySelector('.upload-step-detail');
    const pctEl = containerEl.querySelector('.upload-step-pct');
    const fillEl = containerEl.querySelector('.upload-step-bar-fill');

    if (labelEl) labelEl.textContent = initialLabel;
    if (detailEl) detailEl.textContent = initialDetail;

    try {
        containerEl.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' });
    } catch {
        // Ignore scroll errors in older/test environments
    }

    const hideNotice = () => {
        if (noticeEl) {
            noticeEl.style.display = 'none';
        }
    };

    return {
        hideNotice,
        update({ label, detail, percent, isDone }) {
            const clamped = Math.max(0, Math.min(100, Math.round(percent ?? 0)));
            if (label !== undefined && labelEl) {
                labelEl.textContent = label;
            }
            if (detail !== undefined && detailEl) {
                detailEl.textContent = detail;
            }
            if (pctEl) {
                pctEl.textContent = `${clamped}%`;
            }
            if (fillEl) {
                fillEl.style.width = `${clamped}%`;
                if (isDone) {
                    fillEl.classList.add('is-done');
                    fillEl.classList.remove('is-active');
                } else {
                    fillEl.classList.remove('is-done');
                    fillEl.classList.add('is-active');
                }
            }
            if (stepEl) {
                if (isDone) {
                    stepEl.classList.remove('is-active');
                } else {
                    stepEl.classList.add('is-active');
                }
            }
            if (isDone) {
                hideNotice();
            }
        },
    };
}
