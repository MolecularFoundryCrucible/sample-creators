// Copied from manual-synthesis-ui frontend/src/components/ValidationReview.jsx at c25ae5c.
const selectionKey = (row, field) => `${row}::${field}`;

const CandidateOption = ({ name, candidate, checked, onChange, disabled }) => (
  <label className="candidate-option">
    <input
      type="radio"
      name={name}
      value={candidate.unique_id}
      checked={checked}
      onChange={() => onChange(candidate.unique_id)}
      disabled={disabled}
    />
    <span className="candidate-body">
      <span className="candidate-name">{candidate.sample_name}</span>
      {candidate.sample_type && <span className="candidate-meta">{candidate.sample_type}</span>}
      {candidate.date_created && <span className="candidate-meta">{candidate.date_created}</span>}
      <span className="candidate-id">{candidate.unique_id}</span>
      {candidate.description && <span className="candidate-desc">{candidate.description}</span>}
    </span>
  </label>
);

const ValidationReview = ({
  message,
  needsSelection,
  unresolvedParents,
  duplicateNames,
  selections,
  onSelect,
  confirmDuplicates,
  onConfirmDuplicatesChange,
  onSubmit,
  onCancel,
  loading,
}) => {
  const unpicked = needsSelection.filter((a) => !selections[selectionKey(a.row, a.field)]);
  const blockedByDuplicates = needsSelection.length === 0 && duplicateNames.length > 0 && !confirmDuplicates;
  const canSubmit = !loading && unpicked.length === 0 && !blockedByDuplicates;

  return (
    <div className="validation-review">
      <div className="warning-message">{message}</div>

      {needsSelection.length > 0 && (
        <div className="validation-section">
          <h3>Choose a parent sample</h3>
          {needsSelection.map((item) => {
            const key = selectionKey(item.row, item.field);
            return (
              <div className="validation-item" key={key}>
                <div className="validation-item-header">
                  Row {item.row + 1}
                  {item.sample_name ? ` — ${item.sample_name}` : ''} · {item.field_label}:{' '}
                  <code>{item.reference}</code> matches {item.candidates.length} samples
                </div>
                <div className="candidate-list">
                  {item.candidates.map((candidate) => (
                    <CandidateOption
                      key={candidate.unique_id}
                      name={key}
                      candidate={candidate}
                      checked={selections[key] === candidate.unique_id}
                      onChange={(uniqueId) => onSelect(item.row, item.field, uniqueId)}
                      disabled={loading}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {unresolvedParents.length > 0 && (
        <div className="validation-section">
          <h3>Parent references that match nothing</h3>
          <p className="validation-note">
            These rows will be skipped — nothing is written for them. Fix the reference and upload again,
            or continue to upload the remaining rows.
          </p>
          <ul className="error-list">
            {unresolvedParents.map((item) => (
              <li key={`${item.row}::${item.field}`}>
                Row {item.row + 1}
                {item.sample_name ? ` — ${item.sample_name}` : ''} · {item.field_label}:{' '}
                <code>{item.reference}</code> matched no {item.expected_type}
              </li>
            ))}
          </ul>
        </div>
      )}

      {duplicateNames.length > 0 && (
        <div className="validation-section">
          <h3>Sample names that already exist</h3>
          <ul className="error-list">
            {duplicateNames.map((item) => (
              <li key={item.row}>
                Row {item.row + 1} — <code>{item.sample_name}</code> already exists{' '}
                {item.existing_count === 1 ? 'once' : `${item.existing_count} times`} in this project (
                {item.existing_ids.join(', ')})
              </li>
            ))}
          </ul>
          {needsSelection.length === 0 && (
            <label className="confirm-checkbox">
              <input
                type="checkbox"
                checked={confirmDuplicates}
                onChange={(e) => onConfirmDuplicatesChange(e.target.checked)}
                disabled={loading}
              />
              Create new samples with these names anyway
            </label>
          )}
        </div>
      )}

      <div className="button-group">
        <button className="btn btn-primary btn-large" onClick={onSubmit} disabled={!canSubmit}>
          {loading ? 'Uploading...' : 'Continue upload'}
        </button>
        <button className="btn btn-secondary btn-large" onClick={onCancel} disabled={loading}>
          Back to data
        </button>
      </div>

      {unpicked.length > 0 && (
        <p className="validation-note">
          {unpicked.length} reference{unpicked.length === 1 ? '' : 's'} still need a selection.
        </p>
      )}
    </div>
  );
};

export default ValidationReview;
