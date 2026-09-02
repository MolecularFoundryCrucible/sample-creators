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

// ========== Alert System ==========

function showAlert(type, message) {
    const container = document.getElementById('alert-container');
    const alert = document.createElement('div');
    alert.className = `alert alert-${type}`;
    alert.textContent = message;
    container.appendChild(alert);
    setTimeout(() => alert.remove(), 5000);
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
        populateUserInfo(user);
        showAlert('success', `Logged in as ${user.user_name}`);
    } catch (e) {
        showAlert('error', e.message);
    }
}

async function logoutUser() {
    try {
        await api('/api/user/logout', 'POST');
        clearUserInfo();
        showAlert('success', 'Logged out');
    } catch (e) {
        showAlert('error', e.message);
    } finally {
        for (const fn of logoutResetFns) await fn();
    }
}

async function loadUserState() {
    try {
        const user = await api('/api/user');
        populateUserInfo(user);
    } catch {
        // Not logged in, that's fine
    }
}

function populateUserInfo(user) {
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

async function setProject() {
    const project = document.getElementById('project').value;
    await api('/api/user/project', 'POST', { project });
    await loadSampleTypes();
}

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
