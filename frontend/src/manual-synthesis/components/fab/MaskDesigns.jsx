import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createMaskDesign, listMaskDesigns } from '../../services/api';
import { uploadFiles } from '../../../upload';
import MaskReviewEditor from './MaskReviewEditor';

const errorText = (err, fallback) => {
  const detail = err?.response?.data?.detail;
  return typeof detail === 'string' ? detail : fallback;
};

const MaskDesigns = ({ project, selectedMaskId, onSelectMask, onMasksChanged, onReviewedMap, embedded = false }) => {
  const uploadForm = useRef(null);
  const [masks, setMasks] = useState([]);
  const [file, setFile] = useState(null);
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [progress, setProgress] = useState('');
  const [uploading, setUploading] = useState(false);

  const refresh = useCallback(async () => {
    if (!project) return setMasks([]);
    try {
      setMasks((await listMaskDesigns(project)).masks);
    } catch (err) {
      setError(errorText(err, 'Failed to list mask designs'));
    }
  }, [project]);
  useEffect(() => { refresh(); }, [refresh]);

  const upload = async (event) => {
    event.preventDefault();
    if (!file || !project) return;
    setUploading(true);
    setError('');
    setProgress('Creating mask-design dataset…');
    try {
      const { mask } = await createMaskDesign({ project, dataset_name: name.trim() || file.name.replace(/\.gds$/i, '') });
      const results = await uploadFiles({
        datasetMfid: mask.dataset_id,
        files: [file],
        ingestion: () => ({ requested: true, ingestionClass: 'GdsChipMapIngestor' }),
        onProgress: (_file, p) => setProgress(`Uploading ${file.name}: ${Math.floor(100 * p.uploadedBytes / file.size)}%`),
      });
      if (!results[0].ok) throw new Error(results[0].error);
      if (results[0].ingestionError) throw new Error(`GDS uploaded, but ingestion could not be requested: ${results[0].ingestionError}`);
      setProgress('GDS uploaded. Geometry extraction is running; the review will appear when it completes.');
      setFile(null);
      setName('');
      const fileInput = uploadForm.current?.querySelector('input[type="file"]');
      if (fileInput) fileInput.value = '';
      onSelectMask(mask.dataset_id);
      await refresh();
      await onMasksChanged?.();
    } catch (err) {
      setError(err?.message && !err.response ? err.message : errorText(err, 'Mask upload failed'));
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="mask-designs">
      {error && <div className="error-message">{error}</div>}
      {selectedMaskId ? (
        <>
          <button type="button" className="btn btn-secondary" onClick={() => onSelectMask(null)}>&larr; Mask designs</button>
          <MaskReviewEditor key={selectedMaskId} maskId={selectedMaskId} onSaved={async (map) => {
          await refresh(); await onMasksChanged?.(); onReviewedMap?.(map);
        }} />
        </>
      ) : (
        <>
          <p>Upload a GDS mask layout, then review its suggested chip outlines, labels and blocks before using it in a traveler.</p>
          {React.createElement(embedded ? 'div' : 'form', { className: 'mask-upload', ref: uploadForm, onSubmit: embedded ? undefined : upload }, <>
            <div className="form-row">
              <div className="form-group">
                <label htmlFor="mask-name">Mask design name</label>
                <input id="mask-name" value={name} onChange={(e) => setName(e.target.value)}
                       placeholder={file?.name?.replace(/\.gds$/i, '') || 'e.g. QCMF_WFR_05'} />
              </div>
              <div className="form-group">
                <label htmlFor="mask-gds">GDS file *</label>
                <input id="mask-gds" className="file-input" type="file" accept=".gds" required={!embedded}
                       onChange={(e) => setFile(e.target.files?.[0] || null)} />
              </div>
            </div>
            <button className="btn btn-primary" type={embedded ? 'button' : 'submit'} onClick={embedded ? upload : undefined} disabled={!file || !project || uploading}>
              {uploading ? 'Uploading…' : 'Upload GDS'}
            </button>
            {progress && <p className="muted" role="status">{progress}</p>}</>
          )}

          <h3>Mask designs in {project}</h3>
          {!masks.length ? <p className="muted">No mask designs in this project yet.</p> : (
            <table className="mask-list">
              <thead><tr><th>Mask</th><th>Extraction</th><th>Reviewed map</th></tr></thead>
              <tbody>{masks.map((mask) => (
                <tr key={mask.dataset_id}>
                  <td><button type="button" className="link-button" onClick={() => onSelectMask(mask.dataset_id)}>{mask.dataset_name}</button></td>
                  <td>{mask.geometry_ready ? 'Geometry ready' : 'Uploading / extracting'}</td>
                  <td>{mask.reviewed_map
                    ? `v${mask.reviewed_map.version}: ${mask.reviewed_map.chip_count} chips, ${mask.reviewed_map.block_count} blocks${mask.reviewed_map.locked ? ' · in use' : ''}`
                    : 'Not reviewed'}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
};

export default MaskDesigns;
