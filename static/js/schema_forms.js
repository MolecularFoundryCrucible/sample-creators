const FIELD_TYPES = ['text', 'number', 'integer', 'boolean', 'date', 'group', 'list'];
const NESTED_TYPES = ['group', 'list'];
const NESTED_STYLE = 'border-left:3px solid #ddd; padding-left:12px; margin:8px 0;';

let schemas = [];
let currentSchema = null;
let collectFormValues = null;
let linkedSample = null;

document.addEventListener('DOMContentLoaded', async () => {
    resetSampleTimestamp();
    await loadUserState();
    await loadSchemas();
});

function el(tag, props = {}, children = []) {
    const node = Object.assign(document.createElement(tag), props);
    node.append(...children);
    return node;
}

// Local time as "YYYY-MM-DDTHH:MM" for the datetime-local input.
function resetSampleTimestamp() {
    const now = new Date();
    const offset = now.getTimezoneOffset() * 60000;
    document.getElementById('new-sample-timestamp').value =
        new Date(now.getTime() - offset).toISOString().slice(0, 16);
}

// ========== Login / Project ==========

async function loginSchemaUser(event) {
    await loginUser(event);
    await loadSchemas();
}

async function setSchemaProject() {
    clearLinkedSample();
    await setProject();
    await loadSchemas();
}

// ========== Schema List ==========

async function loadSchemas(selectId = '') {
    const select = document.getElementById('schema-select');
    const status = document.getElementById('schema-status');
    select.innerHTML = '';
    hideSchemaForm();
    try {
        schemas = await api('/schema-forms/api/schemas');
    } catch (error) {
        schemas = [];
        status.textContent = error.status === 401
            ? "Log in to load this project's schemas."
            : `Could not load schemas: ${error.message}`;
        return;
    }

    select.appendChild(el('option', { value: '', textContent: 'Select a data type…' }));
    for (const schema of schemas) {
        select.appendChild(el('option', { value: schema.id, textContent: schema.name }));
    }
    status.textContent = schemas.length
        ? `${schemas.length} schema(s) in this project.`
        : 'No schemas in this project yet. Add one to get started.';

    if (selectId) {
        select.value = selectId;
        selectSchema();
    }
}

function selectSchema() {
    const id = document.getElementById('schema-select').value;
    currentSchema = schemas.find(schema => schema.id === id) || null;
    if (!currentSchema) {
        hideSchemaForm();
        return;
    }
    closeSchemaBuilder();
    renderSchemaForm();
    document.getElementById('section-sample').classList.remove('hidden');
    document.getElementById('section-form').classList.remove('hidden');
}

function hideSchemaForm() {
    currentSchema = null;
    collectFormValues = null;
    document.getElementById('section-sample').classList.add('hidden');
    document.getElementById('section-form').classList.add('hidden');
    document.getElementById('created-dataset').classList.add('hidden');
}

// ========== Schema Builder ==========

function openSchemaBuilder() {
    document.getElementById('schema-select').value = '';
    hideSchemaForm();
    document.getElementById('builder-name').value = '';
    const container = document.getElementById('builder-fields');
    container.innerHTML = '';
    renderBuilderList(container);
    document.getElementById('section-builder').classList.remove('hidden');
}

function closeSchemaBuilder() {
    document.getElementById('section-builder').classList.add('hidden');
}

// A field list with an "Add Field" button. Rows go in `rows`; nested lists are built
// the same way inside each group/list row.
function renderBuilderList(container) {
    const rows = el('div', { className: 'builder-rows' });
    const addButton = el('button', {
        type: 'button',
        className: 'btn btn-secondary',
        textContent: 'Add Field',
    });
    addButton.addEventListener('click', () => rows.appendChild(builderRow()));
    container.append(rows, el('div', { className: 'button-row' }, [addButton]));
    rows.appendChild(builderRow());
}

function builderRow() {
    const nameInput = el('input', { type: 'text', className: 'builder-name', placeholder: 'field name' });
    const typeSelect = el('select', { className: 'builder-type' },
        FIELD_TYPES.map(type => el('option', { value: type, textContent: type })));
    const requiredBox = el('input', { type: 'checkbox', className: 'builder-required' });
    const removeButton = el('button', { type: 'button', className: 'btn btn-secondary', textContent: 'Remove' });
    const childHint = el('p', { className: 'help-text' });
    const children = el('div', { className: 'builder-children hidden', style: NESTED_STYLE }, [childHint]);

    const row = el('div', { className: 'builder-row' }, [
        el('div', { className: 'input-row' }, [
            nameInput,
            typeSelect,
            el('label', {}, [requiredBox, ' required']),
            removeButton,
        ]),
        children,
    ]);

    // A list's child fields describe one entry; every entry in the form gets the same fields.
    typeSelect.addEventListener('change', () => {
        const kind = typeSelect.value;
        const nested = NESTED_TYPES.includes(kind);
        children.classList.toggle('hidden', !nested);
        childHint.textContent = kind === 'list'
            ? 'Fields for each entry in the list:'
            : 'Fields in this group:';
        if (nested && !children.querySelector(':scope > .builder-rows')) renderBuilderList(children);
    });
    removeButton.addEventListener('click', () => row.remove());
    return row;
}

function collectBuilderFields(container) {
    const rows = container.querySelector(':scope > .builder-rows').children;
    return Array.from(rows).map(row => {
        const type = row.querySelector('.builder-type').value;
        const field = {
            name: row.querySelector('.builder-name').value.trim(),
            type,
            required: row.querySelector('.builder-required').checked,
        };
        if (NESTED_TYPES.includes(type)) {
            field.fields = collectBuilderFields(row.querySelector(':scope > .builder-children'));
        }
        return field;
    });
}

async function saveSchema() {
    const name = document.getElementById('builder-name').value.trim();
    if (!name) {
        showAlert('error', 'Enter a schema name');
        return;
    }
    const button = document.getElementById('save-schema');
    button.disabled = true;
    try {
        const schema = await api('/schema-forms/api/schemas', 'POST', {
            name,
            fields: collectBuilderFields(document.getElementById('builder-fields')),
        });
        closeSchemaBuilder();
        showAlert('success', `Saved schema: ${schema.name}`);
        await loadSchemas(schema.id);
    } catch (error) {
        showAlert('error', error.message);
    } finally {
        button.disabled = false;
    }
}

// ========== Generated Form ==========

function renderSchemaForm() {
    document.getElementById('form-title').textContent = currentSchema.name;
    document.getElementById('dataset-name').value = '';
    const container = document.getElementById('schema-form-fields');
    container.innerHTML = '';
    collectFormValues = renderFields(currentSchema.fields, container, true);
}

// Renders a field list into `container` and returns a function that reads its values
// back as a nested object. The browser only enforces `required` when every enclosing
// group/list is required too; the server does the full check.
function renderFields(fields, container, enforce) {
    const getters = fields.map(field => [field.name, renderField(field, container, enforce)]);
    return () => Object.fromEntries(getters.map(([name, get]) => [name, get()]));
}

function renderField(field, container, enforce) {
    const required = enforce && field.required;
    const labelText = field.name + (field.required ? ' *' : '');

    if (field.type === 'group') {
        const box = el('div', { style: NESTED_STYLE });
        container.append(el('div', { className: 'subsection-header', textContent: labelText }), box);
        return renderFields(field.fields, box, required);
    }

    if (field.type === 'list') {
        const entries = el('div');
        const getters = [];
        const addEntry = () => {
            const box = el('div', { style: NESTED_STYLE });
            const get = renderFields(field.fields, box, required);
            const removeButton = el('button', { type: 'button', className: 'btn btn-secondary', textContent: 'Remove' });
            removeButton.addEventListener('click', () => {
                getters.splice(getters.indexOf(get), 1);
                box.remove();
            });
            box.appendChild(el('div', { className: 'button-row' }, [removeButton]));
            getters.push(get);
            entries.appendChild(box);
        };
        const addButton = el('button', { type: 'button', className: 'btn btn-secondary', textContent: `Add ${field.name}` });
        addButton.addEventListener('click', addEntry);
        container.append(
            el('div', { className: 'subsection-header', textContent: labelText }),
            entries,
            el('div', { className: 'button-row' }, [addButton]),
        );
        addEntry();
        return () => getters.map(get => get());
    }

    if (field.type === 'boolean') {
        const box = el('input', { type: 'checkbox' });
        container.appendChild(el('div', { className: 'form-group' }, [el('label', {}, [box, ` ${field.name}`])]));
        return () => box.checked;
    }

    const input = el('input', { required });
    if (field.type === 'number') Object.assign(input, { type: 'number', step: 'any' });
    else if (field.type === 'integer') Object.assign(input, { type: 'number', step: '1' });
    else if (field.type === 'date') input.type = 'date';
    else input.type = 'text';
    container.appendChild(el('div', { className: 'form-group' }, [el('label', { textContent: labelText }), input]));
    return () => input.value.trim();
}

async function submitSchemaForm(event) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity() || !currentSchema) return;

    const button = document.getElementById('create-dataset');
    button.disabled = true;
    try {
        const result = await api('/schema-forms/api/datasets', 'POST', {
            schema_id: currentSchema.id,
            dataset_name: document.getElementById('dataset-name').value.trim(),
            sample_id: linkedSample?.mfid || '',
            values: collectFormValues(),
        });
        document.getElementById('created-dataset-name').textContent = result.dataset_name;
        document.getElementById('created-dataset-id').textContent = linkedSample
            ? `Dataset: ${result.dataset_id} · Linked sample: ${linkedSample.name} (${linkedSample.mfid})`
            : `Dataset: ${result.dataset_id}`;
        document.getElementById('created-dataset').classList.remove('hidden');
        renderSchemaForm();
        showAlert('success', `Created dataset: ${result.dataset_name}`);
    } catch (error) {
        showAlert('error', error.message);
    } finally {
        button.disabled = false;
    }
}

// ========== Sample Panel ==========

function setLinkedSample(sample) {
    linkedSample = sample;
    document.getElementById('linked-sample').value = sample ? `${sample.name} (${sample.mfid})` : '';
    document.getElementById('print-sample').disabled = !sample;
}

function clearLinkedSample() {
    setLinkedSample(null);
}

async function searchSamples(event) {
    event.preventDefault();
    const name = document.getElementById('sample-search').value.trim();
    const status = document.getElementById('sample-search-status');
    const table = document.getElementById('sample-results-table');
    const tbody = document.getElementById('sample-results');
    if (!name) {
        showAlert('error', 'Enter a sample name to search');
        return;
    }

    status.textContent = 'Searching…';
    tbody.innerHTML = '';
    table.classList.add('hidden');
    try {
        const result = await api('/print/api/search', 'POST', {
            sample_name: name,
            exact: document.getElementById('sample-search-exact').checked,
        });
        status.textContent = `${result.count} sample(s) found.`;
        for (const row of result.rows) {
            const linkButton = el('button', { type: 'button', className: 'btn btn-secondary', textContent: 'Link' });
            linkButton.addEventListener('click', () =>
                setLinkedSample({ mfid: row.unique_id, name: row.sample_name }));
            tbody.appendChild(el('tr', {}, [
                el('td', { textContent: row.sample_name }),
                el('td', { textContent: row.sample_type }),
                el('td', { textContent: row.unique_id }),
                el('td', {}, [linkButton]),
            ]));
        }
        table.classList.toggle('hidden', !result.rows.length);
    } catch (error) {
        status.textContent = '';
        showAlert('error', error.message);
    }
}

async function createSample(event) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity()) return;

    const button = document.getElementById('create-sample');
    button.disabled = true;
    try {
        const sample = await api('/schema-forms/api/samples', 'POST', {
            sample_name: document.getElementById('new-sample-name').value.trim(),
            sample_type: document.getElementById('sample_type').value.trim(),
            description: document.getElementById('new-sample-description').value.trim(),
            timestamp: document.getElementById('new-sample-timestamp').value,
        });
        setLinkedSample({ mfid: sample.unique_id, name: sample.sample_name });
        form.reset();
        resetSampleTimestamp();
        loadSampleTypes();
        showAlert('success', `Created and linked sample: ${sample.sample_name}`);
    } catch (error) {
        showAlert('error', error.message);
    } finally {
        button.disabled = false;
    }
}

async function printLinkedSample() {
    const printer = document.getElementById('printer-name').value.trim();
    if (!printer) {
        showAlert('error', 'Enter a printer name');
        return;
    }
    if (!linkedSample) {
        showAlert('error', 'Link or create a sample before printing');
        return;
    }

    const button = document.getElementById('print-sample');
    button.disabled = true;
    try {
        const result = await api('/print/api/print-batch', 'POST', {
            printer,
            items: [linkedSample],
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
    schemas = [];
    clearLinkedSample();
    closeSchemaBuilder();
    hideSchemaForm();
    document.getElementById('schema-select').innerHTML = '';
    document.getElementById('schema-status').textContent = "Log in to load this project's schemas.";
    document.getElementById('sample-results').innerHTML = '';
    document.getElementById('sample-results-table').classList.add('hidden');
    document.getElementById('sample-search-status').textContent = '';
});
