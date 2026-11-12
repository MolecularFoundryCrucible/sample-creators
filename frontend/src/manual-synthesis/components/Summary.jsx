// Copied from manual-synthesis-ui frontend/src/components/Summary.jsx at c25ae5c.
const Summary = ({ message, summary, onAddMore, onLogout }) => {
  return (
    <div className="summary-container">
      <h2>Upload Summary</h2>

      <div className="success-box">
        <div className="summary-message">{message}</div>
      </div>

      {summary && (
        <div className="summary-details">
          <h3>Details</h3>
          <div className="summary-grid">
            <div className="summary-item">
              <span className="summary-label">Project:</span>
              <span className="summary-value">{summary.Project}</span>
            </div>
            <div className="summary-item">
              <span className="summary-label">Synthesis Type:</span>
              <span className="summary-value">{summary['Synthesis Type']}</span>
            </div>
            <div className="summary-item">
              <span className="summary-label">Samples Uploaded:</span>
              <span className="summary-value">{summary['Samples Uploaded']}</span>
            </div>
            <div className="summary-item">
              <span className="summary-label">Failed:</span>
              <span className="summary-value">{summary.Failed}</span>
            </div>
            <div className="summary-item">
              <span className="summary-label">Total Rows:</span>
              <span className="summary-value">{summary['Total Rows']}</span>
            </div>
          </div>

          {summary['Created Samples'] && summary['Created Samples'].length > 0 && (
            <div className="created-samples-section">
              <h4>Created Samples</h4>
              <ul className="created-samples-list">
                {summary['Created Samples'].map((s) => (
                  <li key={s.unique_id}>
                    {s.sample_name} &mdash;{' '}
                    {s.explorer_url ? (
                      <a href={s.explorer_url} target="_blank" rel="noreferrer">
                        {s.unique_id}
                      </a>
                    ) : (
                      s.unique_id
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {summary.Errors && summary.Errors.length > 0 && (
            <div className="error-section">
              <h4>Errors</h4>
              <ul className="error-list">
                {summary.Errors.map((error, idx) => (
                  <li key={idx}>{error}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      <div className="button-group">
        <button className="btn btn-primary btn-large" onClick={onAddMore}>
          + Add More Data
        </button>
        <button className="btn btn-secondary btn-large" onClick={onLogout}>
          Logout
        </button>
      </div>
    </div>
  );
};

export default Summary;
