// Copied from manual-synthesis-ui frontend/src/components/fab/TravelerView.jsx at c25ae5c.
import { useState, useEffect, useCallback } from 'react';
import { getTraveler } from '../../services/api';
import StepForm from './StepForm';
import ProcessLabel from './ProcessLabel';
import CrucibleLabel from './CrucibleLabel';

const STATUS_LABEL = { done: 'Done', skipped: 'Skipped', pending: 'Pending' };

const TravelerView = ({ waferId, project, userInfo, onBack }) => {
  const [traveler, setTraveler] = useState(null);
  const [error, setError] = useState('');
  const [activeStepId, setActiveStepId] = useState(null);
  const [activeRecord, setActiveRecord] = useState(null);
  const [showProcessLabel, setShowProcessLabel] = useState(false);

  const load = useCallback(async () => {
    try {
      setTraveler(await getTraveler(waferId));
      setError('');
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load traveler');
    }
  }, [waferId]);

  useEffect(() => {
    load();
  }, [load]);

  if (error && !traveler) {
    return (
      <div className="main-form">
        <div className="error-message">{error}</div>
        <button className="btn btn-secondary" onClick={onBack}>Back to wafers</button>
      </div>
    );
  }
  if (!traveler) return <div className="main-form">Loading traveler...</div>;

  const { wafer, wafer_options: options, units, steps } = traveler;
  const unitName = Object.fromEntries(units.map((u) => [u.unique_id, u.sample_name]));
  const nextStep = steps.find((s) => s.status === 'pending');
  const activeStep = steps.find((s) => s.id === activeStepId);
  const labelStep = steps.find((s) => s.id === traveler.label_after_step);
  const labelsReady = !labelStep || labelStep.status === 'done';
  const children = (parentId) => units.filter((u) => u.parent_id === parentId);

  const renderUnit = (unit) => (
    <li key={unit.unique_id}>
      <a href={unit.explorer_url} target="_blank" rel="noreferrer">{unit.sample_name}</a>
      <span className="muted"> ({unit.sample_type})</span>
      {children(unit.unique_id).length > 0 && <ul>{children(unit.unique_id).map(renderUnit)}</ul>}
    </li>
  );

  return (
    <div className="main-form">
      <div className="traveler-header">
        <button className="btn btn-secondary" onClick={onBack}>&larr; Wafers</button>
        <h2>{wafer.sample_name}</h2>
        <span className="muted">
          {traveler.template_name} · {traveler.template_defaults?.[traveler.template_default]?.name || traveler.template_default}
          {' · '}{Object.values(options).join(' · ')}
        </span>
      </div>

      {error && <div className="error-message">{error}</div>}

      <div className="traveler-grid">
        <div>
          <h3>Samples</h3>
          <ul className="unit-tree">{renderUnit(wafer)}</ul>

          <h3>Labels</h3>
          {labelsReady ? (
            <>
              <button className="btn btn-secondary" onClick={() => setShowProcessLabel(true)}>
                Print process label
              </button>
              <CrucibleLabel units={units} />
            </>
          ) : (
            <p className="muted">Available once {labelStep.label} ({labelStep.name}) is recorded.</p>
          )}
        </div>

        <div>
          <h3>Process steps</h3>
          <table className="step-table">
            <thead>
              <tr><th>Step</th><th>Name</th><th>Status</th><th>Date</th><th>Applied to</th><th /></tr>
            </thead>
            <tbody>
              {steps.map((s) => {
                const last = s.records[s.records.length - 1];
                const applied = [...new Set(s.records.flatMap((r) => r.unit_ids))].map((id) => unitName[id]);
                return (
                  <tr key={s.id} className={`step-${s.status} ${s === nextStep ? 'step-next' : ''}`}>
                    <td>{s.label}</td>
                    <td>{s.name}{s.optional && <span className="muted"> (optional)</span>}</td>
                    <td>{STATUS_LABEL[s.status]}</td>
                    <td>{last?.step_date || ''}</td>
                    <td className="applied-to">{applied.join(', ')}</td>
                    <td className="step-actions">
                      {s.records.map((r) => (
                        <button key={r.dataset_id} className="btn btn-secondary btn-small"
                                onClick={() => { setActiveRecord(r); setActiveStepId(s.id); }}>
                          View / edit{s.records.length > 1 ? ` (${r.step_date || '?'})` : ''}
                        </button>
                      ))}
                      <button className="btn btn-secondary btn-small"
                              onClick={() => { setActiveRecord(null); setActiveStepId(s.id); }}>
                        {s.status === 'pending' ? 'Record' : 'Record again'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {activeStep && (
        <StepForm
          key={activeRecord?.dataset_id || `new-${activeStep.id}`}
          step={activeStep}
          record={activeRecord}
          traveler={traveler}
          project={project}
          userInfo={userInfo}
          earlierPending={steps
            .slice(0, steps.indexOf(activeStep))
            .filter((s) => s.status === 'pending' && !s.optional)}
          onClose={() => { setActiveStepId(null); setActiveRecord(null); }}
          onRecorded={async () => {
            await load();
            setActiveStepId(null);
            setActiveRecord(null);
          }}
        />
      )}

      {showProcessLabel && (
        <ProcessLabel traveler={traveler} onClose={() => setShowProcessLabel(false)} />
      )}
    </div>
  );
};

export default TravelerView;
