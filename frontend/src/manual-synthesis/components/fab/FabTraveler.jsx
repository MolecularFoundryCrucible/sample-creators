// Copied from manual-synthesis-ui frontend/src/components/fab/FabTraveler.jsx at c25ae5c. Changes: starts from the
// login panel's project; each wafer has its own URL (/fabrication/wafer/<id>), opened on load and kept in sync.
import { useState, useEffect, useCallback } from 'react';
import { getFabTemplates, listWafers, createWafer, getTraveler, listMaskDesigns } from '../../services/api';

// eslint-disable-next-line no-undef
const travelerBase = `${typeof BASE_URL === 'string' ? BASE_URL : ''}/fabrication/`;
const waferFromPath = () => (window.location.pathname.match(/\/fabrication\/wafer\/([^/]+)\/?$/) || [])[1] || null;
const maskFromPath = () => (window.location.pathname.match(/\/fabrication\/masks(?:\/([^/]+))?\/?$/) || [])[1] || null;
import TravelerView from './TravelerView';
import MaskDesigns from './MaskDesigns';
import WaferChipletPlanner from './WaferChipletPlanner';

const errorText = (err, fallback) => err.response?.data?.detail || fallback;
const today = () => new Date().toISOString().split('T')[0];
// 'wafer_type' -> 'Wafer type'
const humanize = (key) => key.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

const FabTraveler = ({ userInfo, initialWaferId, initialMaskId, initialMaskView = false }) => {
  const [templates, setTemplates] = useState({});
  const [project, setProject] = useState(userInfo.selectedProject || '');
  const [wafers, setWafers] = useState([]);
  const [masks, setMasks] = useState([]);
  const [selectedWafer, setSelectedWafer] = useState(null);
  const [showMasks, setShowMasks] = useState(Boolean(initialMaskView));
  const [selectedMask, setSelectedMask] = useState(initialMaskId || null);
  const [showNew, setShowNew] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const templateIds = Object.keys(templates);
  const [form, setForm] = useState(null);
  const [plannedChiplets, setPlannedChiplets] = useState([]);
  const [showInlineMaskDesigner, setShowInlineMaskDesigner] = useState(false);
  const [inlineMaskId, setInlineMaskId] = useState(null);

  useEffect(() => {
    getFabTemplates()
      .then((res) => setTemplates(res.templates))
      .catch((err) => setError(errorText(err, 'Failed to load process templates')));
  }, []);

  const refreshWafers = useCallback(async (proj) => {
    if (!proj) return setWafers([]);
    try {
      setWafers((await listWafers(proj)).wafers);
    } catch (err) {
      setError(errorText(err, 'Failed to load wafers'));
    }
  }, []);

  useEffect(() => {
    refreshWafers(project);
    if (project) {
      listMaskDesigns(project).then((res) => setMasks(res.masks)).catch(() => setMasks([]));
    } else setMasks([]);
  }, [project, refreshWafers]);

  // A wafer URL opens that wafer's traveler in its own project.
  useEffect(() => {
    if (!initialWaferId) return;
    getTraveler(initialWaferId)
      .then((t) => {
        setProject(t.project);
        setSelectedWafer(initialWaferId);
      })
      .catch((err) => setError(errorText(err, 'Failed to open this wafer')));
  }, [initialWaferId]);

  // Keep the address bar on the open wafer, and follow the browser's back/forward buttons.
  useEffect(() => {
    const target = selectedWafer ? `${travelerBase}wafer/${selectedWafer}`
      : showMasks ? `${travelerBase}masks/${selectedMask || ''}` : travelerBase;
    if (window.location.pathname !== target) window.history.pushState(null, '', target);
  }, [selectedWafer, selectedMask, showMasks]);
  useEffect(() => {
    const onPop = () => {
      const maskPath = /\/fabrication\/masks(?:\/|$)/.test(window.location.pathname);
      setShowMasks(maskPath);
      setSelectedMask(maskFromPath());
      setSelectedWafer(waferFromPath());
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const openNewForm = (templateId = templateIds[0]) => {
    const template = templates[templateId];
    const options = Object.fromEntries(
      Object.entries(template.wafer_options).map(([k, values]) => [k, values[0]])
    );
    const spec = Object.fromEntries(template.wafer_spec.parameters.map((p) => [p.key, p.default ?? '']));
    const templateDefault = Object.keys(template.template_defaults)[0];
    setForm({ templateId, templateDefault, name: '', description: '', options, spec, date: today() });
    setPlannedChiplets([]);
    setShowInlineMaskDesigner(false);
    setInlineMaskId(null);
    setShowNew(true);
    setError('');
  };

  const submitNew = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      const res = await createWafer({
        project,
        orcid: userInfo.orcid,
        operator: userInfo.name,
        template_id: form.templateId,
        wafer_name: form.name,
        description: form.description,
        wafer_options: form.options,
        template_default: form.templateDefault,
        spec: form.spec,
        planned_chiplets: plannedChiplets,
        step_date: form.date,
      });
      setShowNew(false);
      await refreshWafers(project);
      setSelectedWafer(res.wafer.unique_id);
    } catch (err) {
      setError(errorText(err, 'Failed to create wafer'));
    } finally {
      setLoading(false);
    }
  };

  const selectWaferMap = (mapId) => {
    setForm((old) => ({ ...old, spec: { ...old.spec, mask_design: mapId } }));
    setPlannedChiplets([]);
  };

  const useReviewedMap = async (map) => {
    setMasks((await listMaskDesigns(project)).masks);
    selectWaferMap(map.dataset_id);
    setShowInlineMaskDesigner(false);
  };

  if (selectedWafer) {
    return (
      <TravelerView
        waferId={selectedWafer}
        project={project}
        userInfo={userInfo}
        onBack={() => {
          setSelectedWafer(null);
          refreshWafers(project);
        }}
      />
    );
  }

  const template = form && templates[form.templateId];

  return (
    <div className="main-form">
      <div className="user-info-box">
        <strong>Current User:</strong> {userInfo.name} | <strong>ORCID:</strong> {userInfo.orcid}
      </div>

      <div className="form-section">
        <div className="form-row">
          <div className="form-group">
            <label htmlFor="fab-project">Project *</label>
            <select id="fab-project" value={project} onChange={(e) => { setSelectedWafer(null); setSelectedMask(null); setProject(e.target.value); }}>
              <option value="">-- Select a project --</option>
              {userInfo.projects.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>
        </div>

        {error && <div className="error-message">{error}</div>}

        {project && (
          <div className="mode-tabs">
            <button className={`mode-tab ${!showMasks ? 'active' : ''}`}
                    onClick={() => { setShowMasks(false); setSelectedMask(null); }}>Wafers</button>
            <button className={`mode-tab ${showMasks ? 'active' : ''}`}
                    onClick={() => { setShowMasks(true); setShowNew(false); }}>Mask designs</button>
          </div>
        )}

        {project && showMasks && (
          <MaskDesigns project={project} selectedMaskId={selectedMask} onSelectMask={setSelectedMask}
                           onMasksChanged={async () => setMasks((await listMaskDesigns(project)).masks)} />
        )}

        {project && !showMasks && !showNew && (
          <>
            <h3>Wafers</h3>
            {wafers.length === 0 ? (
              <p>No wafers in this project yet.</p>
            ) : (
              <ul className="wafer-list">
                {wafers.map((w) => (
                  <li key={w.unique_id}>
                    <button className="link-button" onClick={() => setSelectedWafer(w.unique_id)}>
                      {w.sample_name}
                    </button>
                    {w.description && <span className="muted"> — {w.description}</span>}
                  </li>
                ))}
              </ul>
            )}
            <div className="button-group">
              <button className="btn btn-primary" onClick={() => openNewForm()} disabled={!templateIds.length}>
                + New wafer
              </button>
            </div>
          </>
        )}

        {project && !showMasks && showNew && template && (
          <form onSubmit={submitNew} className="fab-form">
            <h3>New wafer</h3>
            <div className="form-row">
              <div className="form-group">
                <label>Process template</label>
                <select
                  value={form.templateId}
                  onChange={(e) => openNewForm(e.target.value)}
                >
                  {templateIds.map((id) => (
                    <option key={id} value={id}>{templates[id].name} ({id})</option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label>Template default</label>
                <select
                  value={form.templateDefault}
                  onChange={(e) => setForm({ ...form, templateDefault: e.target.value })}
                >
                  {Object.entries(template.template_defaults).map(([id, d]) => (
                    <option key={id} value={id}>{d.name}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label htmlFor="new-wafer-name">Wafer name *</label>
                <input
                  id="new-wafer-name"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="e.g. QCMF_WFR_05"
                  required
                />
              </div>
              <div className="form-group">
                <label>Date</label>
                <input type="date" value={form.date}
                       onChange={(e) => setForm({ ...form, date: e.target.value })} />
              </div>
            </div>
            <div className="form-row">
              {Object.entries(template.wafer_options).map(([key, values]) => (
                <div className="form-group" key={key}>
                  <label>{humanize(key)}</label>
                  <select
                    value={form.options[key]}
                    onChange={(e) => setForm({ ...form, options: { ...form.options, [key]: e.target.value } })}
                  >
                    {values.map((v) => <option key={v} value={v}>{v}</option>)}
                  </select>
                </div>
              ))}
            </div>
            <div className="form-row">
              {template.wafer_spec.parameters.map((p) => (
                <div className="form-group" key={p.key}>
                  <label>{p.label}</label>
                  {p.key === 'mask_design' ? (
                    <>
                      <select value={form.spec[p.key]}
                              onChange={(e) => selectWaferMap(e.target.value)}>
                        <option value="">No chip map — enter cut names manually</option>
                        {masks.flatMap((m) => m.reviewed_map ? [{ mask: m, map: m.reviewed_map }] : []).map(({ mask, map }) => (
                          <option key={map.dataset_id} value={map.dataset_id}>
                            {mask.dataset_name} — v{map.version} ({map.chip_count} chips)
                          </option>
                        ))}
                      </select>
                      <button type="button" className="btn btn-secondary btn-small" onClick={() => setShowInlineMaskDesigner(!showInlineMaskDesigner)}>
                        {showInlineMaskDesigner ? 'Hide GDS upload/review' : 'Upload / review a GDS'}
                      </button>
                      <span className="muted">Choose a reviewed map here, or upload a new GDS above. Planning does not create chiplet samples.</span>
                    </>
                  ) : (
                    <input
                      value={form.spec[p.key]}
                      onChange={(e) => setForm({ ...form, spec: { ...form.spec, [p.key]: e.target.value } })}
                    />
                  )}
                </div>
              ))}
            </div>
            {showInlineMaskDesigner && (
              <section className="embedded-mask-design">
                <MaskDesigns embedded project={project} selectedMaskId={inlineMaskId} onSelectMask={setInlineMaskId}
                  onReviewedMap={useReviewedMap}
                  onMasksChanged={async () => setMasks((await listMaskDesigns(project)).masks)} />
              </section>
            )}
            {form.spec.mask_design && (
              <WaferChipletPlanner mapId={form.spec.mask_design} waferName={form.name}
                                   plan={plannedChiplets} onChange={setPlannedChiplets} />
            )}
            <div className="form-group">
              <input value={form.description}
                     onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </div>
            <div className="button-group">
              <button className="btn btn-primary" type="submit" disabled={loading}>
                {loading ? 'Creating...' : 'Create wafer'}
              </button>
              <button className="btn btn-secondary" type="button" onClick={() => setShowNew(false)}
                      disabled={loading}>
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
};

export default FabTraveler;
