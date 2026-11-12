// B30 Raman data entry: Horiba LabRAM spectra (LabSpec 6 .ngs). Sample panel, upload and logbook
// come from instrument_page.js; the .ngs reader from window.InstrumentParsers.

const INSTRUMENT_PAGE = {
    apiBase: '/b30-raman',
    logbookCols: ['Date', 'User', 'Laser (nm)', 'Exposure (s)', 'Accumulation', 'Grating',
                  'Objective', 'Range (1/cm)', 'Spectra', 'Comment'],
    csvFilename: 'b30_raman_recent_datasets.csv',

    selectedFiles() {
        return [...document.getElementById('raman-files').files];
    },

    ingestionFor(file) {
        return /\.ngs$/i.test(file.name)
            ? { requested: true, ingestionClass: 'HoribaNgsIngestor' }
            : { requested: true };
    },

    filesPreview() {
        const files = document.getElementById('raman-files').files;
        return files.length ? [['Spectra', `${files.length} file(s)`]] : [];
    },

    resetForm() {
        document.getElementById('raman-files').value = '';
        const status = document.getElementById('ngs-extract-status');
        status.style.display = 'none';
        status.textContent = '';
        resetFieldsToDefault('#param-grid [data-key]');
        resetFieldsToDefault('#section-comment [data-key]');
    },
};

// Fill the form from the first selected spectrum. Fails soft: unreadable values stay empty and
// HoribaNgsIngestor fills them in after upload.
async function onRamanFilesSelected() {
    const file = document.getElementById('raman-files').files?.[0];
    const statusEl = document.getElementById('ngs-extract-status');
    statusEl.textContent = '';
    statusEl.style.display = 'none';
    if (!file) return;

    statusEl.style.display = '';
    statusEl.textContent = 'Reading spectrum…';
    try {
        const fields = await window.InstrumentParsers.readNgsFields(file);
        if (!fields) {
            statusEl.textContent = 'Not a readable LabSpec spectrum — fill in the parameters manually.';
            return;
        }
        const set = (id, value) => {
            if (value === undefined) return false;
            document.getElementById(id).value = value;
            return true;
        };
        let filled = 0;
        filled += set('field_laser_wavelength_nm', fields.laser_wavelength_nm);
        filled += set('field_exposure_time_s', fields.exposure_time_s);
        filled += set('field_accumulation', fields.accumulation);
        filled += set('field_grating', fields.grating);
        filled += set('field_objective', fields.objective);
        if (fields.raman_shift_range) {
            set('field_raman_shift_start', fields.raman_shift_range[0]);
            set('field_raman_shift_end', fields.raman_shift_range[1]);
            filled++;
        }
        statusEl.textContent = `✓ Filled ${filled} field(s) from ${file.name}`;
    } catch (e) {
        statusEl.textContent = '';
        showAlert('error', `Could not read the spectrum: ${e.message}`);
    }
}
