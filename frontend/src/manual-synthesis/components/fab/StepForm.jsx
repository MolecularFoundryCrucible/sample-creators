// Copied from manual-synthesis-ui frontend/src/components/fab/StepForm.jsx at c25ae5c. Change: attachments go
// straight to storage through the shared upload module (no size cap), ingestion recorded as not requested.
import { useState, useEffect } from 'react';
import { recordStep, editStepRecord, getStepRecord } from '../../services/api';
import { uploadFiles as uploadToStorage } from '../../../upload';

const ALLOWED_PARENTS = { create_chiplets: ['wafer'], create_chips: ['wafer', 'chiplet'] };
const CHILD_SUFFIX = { create_chiplets: 'CL', create_chips: 'C' };
const WIDE_FIELDS = new Set(['specs']);
const today = () => new Date().toISOString().split('T')[0];

const childNames = (parentName, suffix, count) =>
  Array.from({ length: count }, (_, i) => `${parentName}_${suffix}${String(i + 1).padStart(2, '0')}`);

const errorText = (err, fallback) => err.response?.data?.detail || fallback;

// `record` set = view/edit an existing entry; otherwise record a new one.
const StepForm = ({ step, record, traveler, project, userInfo, earlierPending = [], onClose, onRecorded }) => {
  const editing = Boolean(record);
  const { units, wafer, template_id: templateId } = traveler;
  const action = editing ? null : step.action;
  const leafUnits = units.filter((u) => u.is_leaf);
  const parentCandidates = action
    ? leafUnits.filter((u) => ALLOWED_PARENTS[action].includes(u.sample_type))
    : [];
  const showRows = !editing || record.status === 'done';

  const templateDefaults = traveler.template_defaults || {};
  const [templateDefault, setTemplateDefault] = useState(
    (editing ? record.template_default : null) || traveler.template_default
  );

  // A template default only lists the values it changes; everything else comes from the template.
  const defaultsFor = (defaultId) => {
    const overrides = templateDefaults[defaultId]?.overrides?.[step.id] || {};
    return Object.fromEntries(step.rows.map((r) => [r.key, Object.fromEntries(r.fields.map((f) => {
      const value = overrides[r.key] && f.key in overrides[r.key] ? overrides[r.key][f.key] : f.default;
      return [f.key, value ?? ''];
    }))]));
  };

  // values[rowKey][fieldKey]; an edit starts from the saved row, falling back to the defaults.
  const [values, setValues] = useState(() => {
    const defaults = defaultsFor(templateDefault);
    if (!editing) return defaults;
    const saved = Object.fromEntries((record.rows || []).map((r) => [r.key, r.values || {}]));
    return Object.fromEntries(step.rows.map((r) => [r.key, r.key in saved
      ? Object.fromEntries(r.fields.map((f) => [f.key, saved[r.key][f.key] ?? '']))
      : defaults[r.key]]));
  });

  const changeTemplateDefault = (defaultId) => {
    setTemplateDefault(defaultId);
    setValues(defaultsFor(defaultId));
  };
  const [date, setDate] = useState(editing ? record.step_date || today() : today());
  const [comments, setComments] = useState(editing ? record.comments || '' : '');
  const [targets, setTargets] = useState(
    action ? parentCandidates.map((u) => u.unique_id) : leafUnits.map((u) => u.unique_id)
  );
  const [children, setChildren] = useState(() =>
    Object.fromEntries(parentCandidates.map((u) => [u.unique_id, childNames(u.sample_name, CHILD_SUFFIX[action], 4)]))
  );
  const [newFiles, setNewFiles] = useState([]);
  const [attached, setAttached] = useState(null);
  const [error, setError] = useState('');
  const [problems, setProblems] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!editing) return;
    getStepRecord(record.dataset_id)
      .then((res) => setAttached(res.files))
      .catch(() => setAttached([]));
  }, [editing, record]);

  const toggleTarget = (id) =>
    setTargets((prev) => (prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id]));

  const setChildCount = (parent, count) =>
    setChildren((prev) => ({
      ...prev,
      [parent.unique_id]: childNames(parent.sample_name, CHILD_SUFFIX[action], Math.max(0, count)),
    }));

  const setChildName = (parentId, idx, name) =>
    setChildren((prev) => ({ ...prev, [parentId]: prev[parentId].map((n, i) => (i === idx ? name : n)) }));

  const [openComments, setOpenComments] = useState(() => new Set());
  const toggleComment = (rowKey) =>
    setOpenComments((prev) => {
      const next = new Set(prev);
      next.has(rowKey) ? next.delete(rowKey) : next.add(rowKey);
      return next;
    });

  const setValue = (rowKey, fieldKey, value) =>
    setValues((prev) => ({ ...prev, [rowKey]: { ...prev[rowKey], [fieldKey]: value } }));

  const uploadFiles = async (datasetId) => {
    if (!newFiles.length) return [];
    try {
      const results = await uploadToStorage({
        datasetMfid: datasetId,
        files: newFiles,
        ingestion: () => ({ requested: false }),
      });
      return results.filter((r) => !r.ok).map((r) => `${r.file.name}: ${r.error}`);
    } catch (err) {
      return [errorText(err, 'File upload failed')];
    }
  };

  const submit = async (status) => {
    setLoading(true);
    setError('');
    try {
      let datasetId;
      let issues = [];
      if (editing) {
        await editStepRecord(record.dataset_id, {
          orcid: userInfo.orcid,
          operator: userInfo.name,
          step_date: date,
          rows: showRows ? values : {},
          comments,
        });
        datasetId = record.dataset_id;
      } else {
        const res = await recordStep({
          template_id: templateId,
          step_id: step.id,
          wafer_id: wafer.unique_id,
          project,
          orcid: userInfo.orcid,
          operator: userInfo.name,
          target_ids: targets,
          status,
          step_date: date,
          rows: status === 'done' ? values : {},
          template_default: templateDefault,
          comments,
          new_children: action && status === 'done'
            ? Object.fromEntries(targets.map((t) => [t, children[t] || []]))
            : {},
        });
        datasetId = res.dataset_id;
        issues = res.errors;
      }
      issues = [...issues, ...(await uploadFiles(datasetId))];
      if (issues.length) {
        setProblems(issues);
      } else {
        await onRecorded();
      }
    } catch (err) {
      setError(errorText(err, editing ? 'Failed to save changes' : 'Failed to record step'));
    } finally {
      setLoading(false);
    }
  };

  const selectable = action ? parentCandidates : units;
  const unitName = Object.fromEntries(units.map((u) => [u.unique_id, u.sample_name]));

  return (
    <div className="modal-backdrop">
      <div className="modal-panel">
        <div className="traveler-header">
          <h3>{step.label} — {step.name}{editing ? ' (view / edit)' : ''}</h3>
          <button className="btn btn-secondary btn-small" onClick={onClose} disabled={loading}>Close</button>
        </div>
        {step.tool && <p className="muted">Tool: {step.tool}</p>}

        {!editing && showRows && (
          <div className="form-row">
            <div className="form-group">
              <label>Template default</label>
              <select value={templateDefault} onChange={(e) => changeTemplateDefault(e.target.value)}>
                {Object.entries(templateDefaults).map(([id, d]) => (
                  <option key={id} value={id}>
                    {d.name}{id === traveler.template_default ? ' (this wafer)' : ''}
                  </option>
                ))}
              </select>
            </div>
          </div>
        )}

        {editing && (
          <p className="muted">
            {record.status === 'skipped' ? 'Skipped' : 'Recorded'} by {record.operator || 'unknown'}
            {' · '}applies to {record.unit_ids.map((id) => unitName[id] || id).join(', ')}
            {record.edited_by && ` · last edited by ${record.edited_by}`}
          </p>
        )}

        {!editing && earlierPending.length > 0 && (
          <div className="warning-message">
            Earlier required steps are still pending: {earlierPending.map((s) => s.label).join(', ')}.
            You can still record this step.
          </div>
        )}

        {showRows && (
          <div className="step-rows">
            {step.rows.map((r) => {
              const fields = r.fields.filter((f) => f.key !== 'comment');
              const hasComment = r.fields.some((f) => f.key === 'comment');
              const commentText = String(values[r.key].comment ?? '');
              const open = openComments.has(r.key);
              return (
              <div key={r.key} className="step-row">
                <div className="step-row-title">{r.process}</div>
                {fields.length > 0 && (
                  <div className="param-grid">
                    {fields.map((f) => (
                      <div className={`form-group ${WIDE_FIELDS.has(f.key) ? 'wide' : ''}`} key={f.key}>
                        <label>{f.label}{f.unit ? ` (${f.unit})` : ''}</label>
                        <input
                          type={f.type === 'number' ? 'number' : 'text'}
                          step="any"
                          value={values[r.key][f.key]}
                          onChange={(e) => setValue(r.key, f.key, e.target.value)}
                        />
                      </div>
                    ))}
                  </div>
                )}
                {hasComment && (
                  <div className="row-comment">
                    <button type="button" className="comment-toggle" aria-expanded={open}
                            onClick={() => toggleComment(r.key)}>
                      {open ? '▾' : '▸'} {commentText.trim()
                        ? (open ? 'Comment' : `Comment: ${commentText.length > 70 ? `${commentText.slice(0, 70)}…` : commentText}`)
                        : 'Add comment'}
                    </button>
                    {open && (
                      <textarea rows="2" value={commentText} autoFocus={!commentText}
                                onChange={(e) => setValue(r.key, 'comment', e.target.value)} />
                    )}
                  </div>
                )}
              </div>
              );
            })}
          </div>
        )}

        <div className="form-row">
          <div className="form-group">
            <label>Date</label>
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </div>
        </div>

        {!editing && (
          <div className="form-group">
            <label>{action ? 'Cut' : 'Applies to'}</label>
            {selectable.length === 0 && <p className="muted">Nothing left to cut at this level.</p>}
            <div className="target-list">
              {selectable.map((u) => (
                <label key={u.unique_id} className="confirm-checkbox">
                  <input type="checkbox" checked={targets.includes(u.unique_id)}
                         onChange={() => toggleTarget(u.unique_id)} />
                  {u.sample_name} <span className="muted">({u.sample_type})</span>
                </label>
              ))}
            </div>
          </div>
        )}

        {action && targets.map((parentId) => {
          const parent = units.find((u) => u.unique_id === parentId);
          const names = children[parentId] || [];
          return (
            <div key={parentId} className="children-editor">
              <label>
                {action === 'create_chiplets' ? 'Chiplets' : 'Chips'} from {parent.sample_name}:{' '}
                <input type="number" min="0" value={names.length}
                       onChange={(e) => setChildCount(parent, parseInt(e.target.value || '0', 10))} />
              </label>
              <div className="children-names">
                {names.map((n, i) => (
                  <input key={i} value={n} onChange={(e) => setChildName(parentId, i, e.target.value)} />
                ))}
              </div>
            </div>
          );
        })}

        {editing && record.created_children?.length > 0 && (
          <p className="muted">
            Created: {record.created_children.map((c) => c.sample_name).join(', ')}
          </p>
        )}

        {step.allow_files && (
          <div className="form-group">
            <label>Files (optional, e.g. recipe file)</label>
            {editing && attached === null && <p className="muted">Loading attached files...</p>}
            {editing && attached?.length > 0 && (
              <ul className="file-list">
                {attached.map((f) => (
                  <li key={f.mfid}>
                    {f.url ? <a href={f.url} target="_blank" rel="noreferrer">{f.filename}</a> : f.filename}
                  </li>
                ))}
              </ul>
            )}
            <input type="file" multiple className="file-input"
                   onChange={(e) => setNewFiles(Array.from(e.target.files))} />
          </div>
        )}

        <div className="form-group">
          <label>Comments / deviations</label>
          <textarea rows="3" value={comments} onChange={(e) => setComments(e.target.value)} />
        </div>

        {error && <div className="error-message">{error}</div>}
        {problems && (
          <div className="warning-message">
            Saved, with problems: {problems.join('; ')}
            <div><button className="btn btn-secondary btn-small" onClick={onRecorded}>OK</button></div>
          </div>
        )}

        <div className="button-group">
          {editing ? (
            <button className="btn btn-primary" onClick={() => submit(record.status)} disabled={loading}>
              {loading ? 'Saving...' : 'Save changes'}
            </button>
          ) : (
            <>
              <button className="btn btn-primary" onClick={() => submit('done')}
                      disabled={loading || !targets.length}>
                {loading ? 'Saving...' : 'Record as done'}
              </button>
              {step.optional && (
                <button className="btn btn-secondary" onClick={() => submit('skipped')}
                        disabled={loading || !targets.length}>
                  Skip step
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default StepForm;
