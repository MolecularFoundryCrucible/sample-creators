// B30 XPS data entry: Kratos Axis Ultra / Vision spectra (.kal). Sample panel, upload and logbook
// come from instrument_page.js; the .kal reader from window.InstrumentParsers.

const INSTRUMENT_PAGE = {
    apiBase: '/b30-xps',
    sampleOptional: true,
    logbookCols: ['Date', 'User', 'Anode', 'Photon (eV)', 'Voltage (V)',
                  'Current (A)', 'Position', 'Spectra', 'Regions', 'Comment'],
    csvFilename: 'b30_xps_recent_datasets.csv',

    selectedFiles() {
        return [...document.getElementById('xps-files').files];
    },

    ingestionFor(file) {
        return /\.kal$/i.test(file.name)
            ? { requested: true, ingestionClass: 'KratosXpsIngestor' }
            : { requested: true };
    },

    filesPreview() {
        const files = document.getElementById('xps-files').files;
        return files.length ? [['Spectra', `${files.length} file(s)`]] : [];
    },

    resetForm() {
        document.getElementById('xps-files').value = '';
        const status = document.getElementById('kal-extract-status');
        status.style.display = 'none';
        status.textContent = '';
        resetFieldsToDefault('#param-grid [data-key]');
        resetFieldsToDefault('#section-comment [data-key]');
    },
};

// Fill the form from the selected spectrum file. Fails soft: unreadable values stay empty and
// KratosXpsIngestor fills them in after upload.
async function onXpsFilesSelected() {
    const file = document.getElementById('xps-files').files?.[0];
    const statusEl = document.getElementById('kal-extract-status');
    statusEl.textContent = '';
    statusEl.style.display = 'none';
    if (!file) return;

    statusEl.style.display = '';
    statusEl.textContent = 'Reading spectrum…';
    try {
        const fields = await window.InstrumentParsers.readKalFields(file);
        if (!fields) {
            statusEl.textContent = 'Not a readable Kratos spectrum — fill in the parameters manually.';
            return;
        }
        const set = (id, value) => {
            if (value === undefined || value === null) return false;
            document.getElementById(id).value = value;
            return true;
        };
        let filled = 0;
        filled += set('field_anode_material', fields.anode_material);
        filled += set('field_photon_energy_eV', fields.photon_energy_eV);
        filled += set('field_anode_voltage_V', fields.anode_voltage_V);
        filled += set('field_emission_current_A', fields.emission_current_A);
        filled += set('field_stage_position_name', fields.stage_position_name);
        filled += set('field_technique', fields.technique);

        const commentEl = document.getElementById('field_comment');
        if (commentEl && !commentEl.value && fields.dataset_comment) {
            commentEl.value = fields.dataset_comment;
            filled++;
        }

        let summary = `✓ Filled ${filled} field(s) from ${file.name}`;
        if (fields.total_spectra !== undefined && fields.regions && fields.regions.length > 0) {
            summary += ` (${fields.total_spectra} spectra: ${fields.regions.join(', ')})`;
        }
        statusEl.textContent = summary;
    } catch (e) {
        statusEl.textContent = '';
        showAlert('error', `Could not read the spectrum: ${e.message}`);
    }
}
