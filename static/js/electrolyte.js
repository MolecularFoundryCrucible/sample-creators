let createdElectrolyte = null;
let duplicateChoice = null;
let nameCheckToken = 0;
let checkedName = '';
let checkingName = '';

document.addEventListener('DOMContentLoaded', async () => {
    document.getElementById('preparation-date').value = localDateString();
    addIngredientRow();
    const nameInput = document.getElementById('electrolyte-name');
    nameInput.addEventListener('input', onElectrolyteNameInput);
    nameInput.addEventListener('blur', checkElectrolyteName);
    nameInput.addEventListener('keydown', event => {
        if (event.key !== 'Enter') return;
        event.preventDefault();
        checkElectrolyteName();
    });
    await loadUserState();
});

function localDateString() {
    const now = new Date();
    const offset = now.getTimezoneOffset() * 60000;
    return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

function addIngredientRow(type = '', amount = '') {
    const row = document.createElement('tr');

    const typeCell = document.createElement('td');
    const typeInput = document.createElement('input');
    typeInput.type = 'text';
    typeInput.className = 'ingredient-type';
    typeInput.placeholder = 'e.g. KOH';
    typeInput.required = true;
    typeInput.value = type;
    typeCell.appendChild(typeInput);

    const amountCell = document.createElement('td');
    const amountInput = document.createElement('input');
    amountInput.type = 'text';
    amountInput.className = 'ingredient-amount';
    amountInput.placeholder = 'e.g. 5.6 g';
    amountInput.required = true;
    amountInput.value = amount;
    amountCell.appendChild(amountInput);

    const actionCell = document.createElement('td');
    const removeButton = document.createElement('button');
    removeButton.type = 'button';
    removeButton.className = 'btn btn-secondary';
    removeButton.textContent = 'Remove';
    removeButton.addEventListener('click', () => {
        const rows = document.querySelectorAll('#ingredient-rows tr');
        if (rows.length === 1) {
            typeInput.value = '';
            amountInput.value = '';
        } else {
            row.remove();
        }
    });
    actionCell.appendChild(removeButton);

    row.append(typeCell, amountCell, actionCell);
    document.getElementById('ingredient-rows').appendChild(row);
}

function collectIngredients() {
    return Array.from(document.querySelectorAll('#ingredient-rows tr')).map(row => ({
        type: row.querySelector('.ingredient-type').value.trim(),
        amount: row.querySelector('.ingredient-amount').value.trim(),
    }));
}

function resetElectrolyteFields(useDefaultDate = false) {
    nameCheckToken++;
    checkedName = '';
    checkingName = '';
    duplicateChoice = null;
    document.getElementById('electrolyte-form').reset();
    document.getElementById('ingredient-rows').innerHTML = '';
    addIngredientRow();
    document.getElementById('electrolyte-name-status').textContent = '';
    document.getElementById('create-electrolyte').textContent = 'Create Electrolyte Sample';
    if (useDefaultDate) {
        document.getElementById('preparation-date').value = localDateString();
    }
}

function renderCreatedSummary(result, payload) {
    const action = result.existing_sample_reused
        ? 'Updated existing sample'
        : 'Created new sample';
    const ingredients = payload.ingredients
        .map(ingredient => `${ingredient.type}: ${ingredient.amount}`)
        .join(', ');
    const rows = [
        ['Action', action],
        ['Sample', `${result.sample_name} (${result.unique_id})`],
        ['Preparation dataset', `${result.dataset_name} (${result.dataset_id})`],
        ['Preparation date', payload.preparation_date],
        ['Concentration', payload.concentration],
        ['pH', payload.ph],
        ['Ingredients', ingredients],
    ];

    const summary = document.getElementById('created-electrolyte-summary');
    summary.innerHTML = '';
    for (const [label, value] of rows) {
        const row = document.createElement('tr');
        const labelCell = document.createElement('th');
        const valueCell = document.createElement('td');
        labelCell.textContent = label;
        valueCell.textContent = value;
        row.append(labelCell, valueCell);
        summary.appendChild(row);
    }
}

function onElectrolyteNameInput() {
    nameCheckToken++;
    checkedName = '';
    checkingName = '';
    duplicateChoice = null;
    createdElectrolyte = null;
    document.getElementById('print-electrolyte').disabled = true;
    document.getElementById('create-electrolyte').textContent = 'Create Electrolyte Sample';

    const name = document.getElementById('electrolyte-name').value.trim();
    const status = document.getElementById('electrolyte-name-status');
    status.textContent = name ? 'Press Enter or leave this field to check the name.' : '';
}

async function checkElectrolyteName() {
    const name = document.getElementById('electrolyte-name').value.trim();
    if (!name || checkedName === name || checkingName === name) return;

    const token = ++nameCheckToken;
    checkingName = name;
    const status = document.getElementById('electrolyte-name-status');
    status.textContent = 'Checking name…';
    try {
        const result = await api('/electrolyte/api/check-name', 'POST', { name });
        if (token !== nameCheckToken || name !== document.getElementById('electrolyte-name').value.trim()) return;
        checkedName = name;

        if (result.exists) {
            status.textContent = 'This name already exists in the selected project.';
            showDuplicateWarning(result);
        } else {
            status.textContent = 'Name is available in the selected project.';
        }
    } catch (error) {
        if (token !== nameCheckToken) return;
        status.textContent = error.status === 401
            ? 'Log in and select a project to check this name.'
            : `Could not check name: ${error.message}`;
    } finally {
        if (checkingName === name) checkingName = '';
    }
}

async function setElectrolyteProject() {
    nameCheckToken++;
    checkedName = '';
    checkingName = '';
    duplicateChoice = null;
    createdElectrolyte = null;
    document.getElementById('print-electrolyte').disabled = true;
    await setProject();
    await checkElectrolyteName();
}

async function createElectrolyte(event) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity()) return;

    const name = document.getElementById('electrolyte-name').value.trim();
    const choice = duplicateChoice?.name === name ? duplicateChoice.payload : {};
    await submitElectrolyte({
        name: document.getElementById('electrolyte-name').value.trim(),
        preparation_date: document.getElementById('preparation-date').value,
        concentration: document.getElementById('electrolyte-concentration').value.trim(),
        ph: document.getElementById('electrolyte-ph').value,
        ingredients: collectIngredients(),
        ...choice,
    });
}

async function submitElectrolyte(payload) {
    const button = document.getElementById('create-electrolyte');
    button.disabled = true;

    try {
        const result = await api('/electrolyte/api/create', 'POST', payload);

        document.getElementById('created-electrolyte-name').textContent = result.sample_name;
        document.getElementById('created-electrolyte-id').textContent =
            `Sample: ${result.unique_id} · Preparation dataset: ${result.dataset_id}`;
        renderCreatedSummary(result, payload);
        document.getElementById('created-electrolyte').classList.remove('hidden');
        createdElectrolyte = { mfid: result.unique_id, name: result.sample_name };
        document.getElementById('print-electrolyte').disabled = false;
        const action = result.existing_sample_reused ? 'Updated' : 'Created';
        resetElectrolyteFields();
        showAlert('success', `${action} electrolyte sample: ${result.sample_name}`);
    } catch (error) {
        if (error.status === 409 && error.data?.exists) {
            showDuplicateWarning(error.data, payload);
        } else {
            showAlert('error', error.message);
        }
    } finally {
        button.disabled = false;
    }
}

function showDuplicateWarning(data, payload) {
    const options = data.existing_samples.map(sample => {
        const type = sample.sample_type ? ` (${sample.sample_type})` : '';
        return `<option value="${escapeHtml(sample.unique_id)}">${escapeHtml(sample.unique_id + type)}</option>`;
    }).join('');

    const continueWith = choice => {
        duplicateChoice = { name: data.sample_name, payload: choice };
        if (choice.existing_sample_id) {
            const sample = data.existing_samples.find(item => item.unique_id === choice.existing_sample_id);
            createdElectrolyte = { mfid: sample.unique_id, name: sample.sample_name };
            document.getElementById('print-electrolyte').disabled = false;
            document.getElementById('electrolyte-name-status').textContent =
                `Loading existing preparation for ${sample.unique_id}…`;
            document.getElementById('create-electrolyte').textContent = 'Update Electrolyte Sample';
            loadExistingPreparation(sample);
        } else {
            document.getElementById('electrolyte-name-status').textContent =
                'A new sample with this duplicate name will be created.';
            if (payload) submitElectrolyte({ ...payload, ...choice });
        }
    };

    showModal(
        'Electrolyte Name Already Exists',
        `<p>A sample named <strong>${escapeHtml(data.sample_name)}</strong> already exists in the selected project.</p>
         <div class="form-group" style="margin-top:12px;">
             <label for="existing-electrolyte-sample">Existing sample to update</label>
             <select id="existing-electrolyte-sample">${options}</select>
         </div>
         <p class="help-text">Cancel to return to the form and enter a different name.</p>`,
        () => continueWith({ allow_duplicate: true }),
        'Create Duplicate',
        {
            label: 'Update Existing',
            onClick: () => {
                const existingSampleId = document.getElementById('existing-electrolyte-sample').value;
                continueWith({ existing_sample_id: existingSampleId });
            },
        }
    );
}

async function loadExistingPreparation(sample) {
    const status = document.getElementById('electrolyte-name-status');
    try {
        const result = await api('/electrolyte/api/existing-preparation', 'POST', {
            sample_id: sample.unique_id,
            name: sample.sample_name,
        });
        if (duplicateChoice?.payload.existing_sample_id !== sample.unique_id ||
            document.getElementById('electrolyte-name').value.trim() !== sample.sample_name) {
            return;
        }
        if (!result.found) {
            status.textContent = `Existing sample selected: ${sample.unique_id}. No preparation dataset was found.`;
            showAlert('info', 'No existing electrolyte preparation dataset was found. Enter the preparation details manually.');
            return;
        }

        document.getElementById('preparation-date').value = result.preparation_date || '';
        document.getElementById('electrolyte-concentration').value = result.concentration ?? '';
        document.getElementById('electrolyte-ph').value = result.ph ?? '';

        const ingredientRows = document.getElementById('ingredient-rows');
        ingredientRows.innerHTML = '';
        for (const ingredient of result.ingredients) {
            if (!ingredient || typeof ingredient !== 'object') continue;
            addIngredientRow(ingredient.type || '', ingredient.amount || '');
        }
        if (!ingredientRows.children.length) addIngredientRow();

        status.textContent = `Loaded preparation dataset: ${result.dataset_id}`;
        showAlert('success', 'Loaded the existing electrolyte preparation details.');
    } catch (error) {
        status.textContent = `Could not load the existing preparation: ${error.message}`;
        showAlert('error', error.message);
    }
}

async function printElectrolyte() {
    const printer = document.getElementById('printer-name').value.trim();
    if (!printer) {
        showAlert('error', 'Enter a printer name');
        return;
    }
    if (!createdElectrolyte) {
        showAlert('error', 'Create an electrolyte sample before printing');
        return;
    }

    const button = document.getElementById('print-electrolyte');
    button.disabled = true;
    try {
        const result = await api('/print/api/print-batch', 'POST', {
            printer,
            items: [createdElectrolyte],
        });
        if (result.printed) {
            showAlert('success', `Sent barcode to ${result.printer}`);
        }
        for (const failed of result.results.filter(item => !item.ok)) {
            showAlert('error', failed.error);
        }
    } catch (error) {
        showAlert('error', error.message);
    } finally {
        button.disabled = false;
    }
}

registerLogoutReset(() => {
    resetElectrolyteFields(true);
    document.getElementById('created-electrolyte').classList.add('hidden');
    document.getElementById('created-electrolyte-summary').innerHTML = '';
    createdElectrolyte = null;
    document.getElementById('print-electrolyte').disabled = true;
});
