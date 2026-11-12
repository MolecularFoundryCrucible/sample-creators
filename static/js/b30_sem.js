// B30 SEM data entry: SEM images (FEI TIFF) and EDX (Bruker .spx/.rtx). Sample panel, upload
// and logbook come from instrument_page.js; the file parsers from window.InstrumentParsers.

const INSTRUMENT_PAGE = {
    apiBase: '/b30-sem',
    logbookCols: ['Date', 'User', 'Vacuum', 'Spot', 'HV (V)', 'Current (A)',
                  'Pressure (Torr)', 'EDX', 'Energy (keV)', 'Comment'],
    csvFilename: 'b30_sem_recent_datasets.csv',

    selectedFiles() {
        const files = [];
        if (document.getElementById('images-yes').checked) {
            files.push(...document.getElementById('sem-image-files').files);
        }
        if (document.getElementById('field_edx_used').checked) {
            files.push(...document.getElementById('edx-image-files').files);
            files.push(...document.getElementById('edx-spectrum-file').files);
        }
        return files;
    },

    ingestionFor(file) {
        const name = file.name.toLowerCase();
        if (name.endsWith('.tif') || name.endsWith('.tiff')) {
            // Falls back to the generic TIFF ingestor if the file has no FEI metadata.
            return { requested: true, ingestionClass: 'FeiSemTifIngestor' };
        }
        if (name.endsWith('.spx') || name.endsWith('.rtx')) {
            return { requested: true, ingestionClass: 'BrukerEdxIngestor' };
        }
        return { requested: true };
    },

    filesPreview() {
        const rows = [];
        const sem = document.getElementById('sem-image-files').files;
        const edxImages = document.getElementById('edx-image-files').files;
        const spectrum = document.getElementById('edx-spectrum-file').files;
        if (sem.length) rows.push(['SEM images', `${sem.length} file(s)`]);
        if (edxImages.length) rows.push(['EDX images', `${edxImages.length} file(s)`]);
        if (spectrum.length) rows.push(['EDX spectrum', spectrum[0].name]);
        return rows;
    },

    resetForm() {
        document.getElementById('images-yes').checked = false;
        document.getElementById('images-no').checked = false;
        document.getElementById('section-image-upload').classList.add('hidden');
        document.getElementById('sem-image-files').value = '';
        const tiffStatus = document.getElementById('tiff-extract-status');
        tiffStatus.style.display = 'none';
        tiffStatus.textContent = '';
        document.getElementById('non-tiff-hint').style.display = 'none';

        resetFieldsToDefault('#param-grid [data-key]');
        resetFieldsToDefault('#section-edx [data-key]');
        document.getElementById('edx-details').classList.add('hidden');
        document.getElementById('edx-image-files').value = '';
        document.getElementById('edx-spectrum-file').value = '';
        document.getElementById('edx-spectrum-status').textContent = '';
        resetFieldsToDefault('#section-comment [data-key]');
    },
};

// ========== SEM images ==========

function onImagesSavedChange() {
    const yes = document.getElementById('images-yes').checked;
    document.getElementById('section-image-upload').classList.toggle('hidden', !yes);
    if (!yes) {
        document.getElementById('sem-image-files').value = '';
        document.getElementById('non-tiff-hint').style.display = 'none';
        const statusEl = document.getElementById('tiff-extract-status');
        statusEl.style.display = 'none';
        statusEl.textContent = '';
    }
}

async function onSemFilesSelected() {
    const input = document.getElementById('sem-image-files');
    const nonTiffHint = document.getElementById('non-tiff-hint');
    const statusEl = document.getElementById('tiff-extract-status');
    statusEl.style.display = 'none';
    statusEl.textContent = '';

    if (!input.files || input.files.length === 0) {
        nonTiffHint.style.display = 'none';
        return;
    }
    // Auto-extract from the first TIFF in the selection, if any
    const tiffFile = Array.from(input.files).find(f => /\.tiff?$/i.test(f.name));
    if (tiffFile) {
        nonTiffHint.style.display = 'none';
        await extractTiffMetadata(tiffFile);
    } else {
        nonTiffHint.style.display = '';
    }
}

async function extractTiffMetadata(tiffFile) {
    const statusEl = document.getElementById('tiff-extract-status');
    statusEl.style.display = '';
    statusEl.textContent = 'Extracting metadata…';
    try {
        const { readFeiTiffMetadata, feiFormFields } = window.InstrumentParsers;
        const metadata = await readFeiTiffMetadata(tiffFile);
        const fields = metadata ? feiFormFields(metadata) : {};
        if (Object.keys(fields).length === 0) {
            statusEl.textContent = 'No metadata found';
            showAlert('info', 'No FEI metadata found in this TIFF. Please fill in parameters manually.');
            return;
        }
        let filled = 0;
        for (const [key, value] of Object.entries(fields)) {
            const el = document.getElementById(`field_${key}`);
            if (el) {
                el.value = value;
                filled++;
            }
        }
        statusEl.textContent = `✓ Filled ${filled} field(s)`;
        showAlert('success', `Metadata extracted: ${filled} field(s) auto-filled`);
    } catch (e) {
        statusEl.textContent = '';
        showAlert('error', `Extraction error: ${e.message}`);
    }
}

// ========== EDX ==========

function onEdxToggle() {
    const checked = document.getElementById('field_edx_used').checked;
    document.getElementById('edx-details').classList.toggle('hidden', !checked);
    if (!checked) {
        document.getElementById('edx-image-files').value = '';
        document.getElementById('edx-spectrum-file').value = '';
        document.getElementById('field_primary_energy_keV').value = '';
        document.getElementById('edx-spectrum-status').textContent = '';
    }
}

async function onEdxSpectrumSelected() {
    const file = document.getElementById('edx-spectrum-file').files?.[0];
    const statusEl = document.getElementById('edx-spectrum-status');
    if (!file) {
        statusEl.textContent = '';
        return;
    }
    statusEl.textContent = 'Reading spectrum…';
    try {
        const keV = await window.InstrumentParsers.readBrukerPrimaryEnergy(file);
        if (keV === null) {
            statusEl.textContent = 'No primary energy found in this file. Please enter it manually.';
            return;
        }
        document.getElementById('field_primary_energy_keV').value = keV;
        statusEl.textContent = `✓ Primary energy ${keV} keV filled from the spectrum`;
    } catch (e) {
        statusEl.textContent = '';
        showAlert('error', `Could not read the spectrum: ${e.message}`);
    }
}
