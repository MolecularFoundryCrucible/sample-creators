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
        throw new Error(data.error || `Request failed (${res.status})`);
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

function showModal(title, bodyHTML, onConfirm) {
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body').innerHTML = bodyHTML;
    document.getElementById('modal-overlay').classList.remove('hidden');

    const confirmBtn = document.getElementById('modal-confirm');
    // Remove old listeners by cloning
    const newBtn = confirmBtn.cloneNode(true);
    confirmBtn.parentNode.replaceChild(newBtn, confirmBtn);
    newBtn.addEventListener('click', () => {
        closeModal();
        onConfirm();
    });
}

function closeModal() {
    document.getElementById('modal-overlay').classList.add('hidden');
}

// ========== User Login/Logout ==========

async function loginUser() {
    const email = document.getElementById('email').value.trim();
    if (!email) {
        showAlert('error', 'Please enter an email address');
        return;
    }
    try {
        const user = await api('/api/user/login', 'POST', { email });
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
    document.getElementById('email').value = user.email;
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
}

async function setProject() {
    const project = document.getElementById('project').value;
    await api('/api/user/project', 'POST', { project });
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
