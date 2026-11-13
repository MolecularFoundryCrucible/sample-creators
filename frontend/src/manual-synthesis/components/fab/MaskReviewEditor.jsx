import React, { useEffect, useMemo, useState } from 'react';
import { getMaskDesign, saveChipMap } from '../../services/api';
import { chipsForGroups, duplicateLabel, suggestChipMap } from '../../../chip-map/chip-map.ts';
import ChipMapSvg from './ChipMapSvg';

const errorText = (err, fallback) => {
  const detail = err?.response?.data?.detail;
  return typeof detail === 'string' ? detail : fallback;
};
const copyMap = (map) => ({
  units: 'mm',
  blocks: (map?.blocks || []).map((b) => ({ ...b })),
  chips: (map?.chips || []).map((c) => ({ ...c, outline: [...c.outline] })),
});
const terminal = new Set(['complete', 'completed', 'failed', 'error', 'not_supported', 'file_not_found', 'not_requested', 'cancelled', 'canceled']);
export const ingestionIsWaiting = (geometry, ingestion) => !geometry && (
  !ingestion?.length || ingestion.some((r) => !terminal.has(String(r.status || '').trim().toLowerCase().replace(/[\s-]+/g, '_')))
);

const MaskReviewEditor = ({ maskId, onSaved }) => {
  const [data, setData] = useState(null);
  const [map, setMap] = useState({ units: 'mm', blocks: [], chips: [] });
  const [groups, setGroups] = useState([]);
  const [selectedGroups, setSelectedGroups] = useState([]);
  const [selectedVersion, setSelectedVersion] = useState(null);
  const [selectedChip, setSelectedChip] = useState(null);
  const [blockFilter, setBlockFilter] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  const initial = suggestChipMap(data?.geometry || { shapes: [], labels: [], unresolved_labels: [] });
  const load = async (versionId) => {
    const result = await getMaskDesign(maskId);
    setData(result);
    const versions = result.versions || [];
    const version = versions.find((v) => v.dataset_id === versionId) || versions[0] || null;
    const suggestion = suggestChipMap(result.geometry || { shapes: [], labels: [], unresolved_labels: [] });
    setGroups(suggestion.groups);
    setSelectedGroups(suggestion.groups.filter((g) => g.defaultSelected).map((g) => g.key));
    setMap(version ? copyMap(version.chip_map) : copyMap(suggestion));
    setSelectedVersion(version?.dataset_id || null);
    setSelectedChip(null);
    setError('');
  };

  useEffect(() => {
    let cancelled = false;
    let timer;
    const refresh = async () => {
      try {
        const result = await getMaskDesign(maskId);
        if (cancelled) return;
        setData((previous) => {
          // Polling while a review is open must not overwrite edits. Full state is only initialized once.
          if (!previous || (!previous.geometry && result.geometry)) {
            const version = result.versions?.[0] || null;
            const suggestion = suggestChipMap(result.geometry || { shapes: [], labels: [], unresolved_labels: [] });
            setGroups(suggestion.groups);
            setSelectedGroups(suggestion.groups.filter((g) => g.defaultSelected).map((g) => g.key));
            setMap(version ? copyMap(version.chip_map) : copyMap(suggestion));
            setSelectedVersion(version?.dataset_id || null);
          }
          return result;
        });
        const waiting = ingestionIsWaiting(result.geometry, result.ingestion);
        if (waiting) timer = setTimeout(refresh, 2000);
      } catch (err) {
        if (!cancelled) setError(errorText(err, 'Failed to load mask design'));
      }
    };
    refresh();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [maskId]);

  const currentVersion = data?.versions?.find((v) => v.dataset_id === selectedVersion) || null;
  const latestVersion = data?.versions?.[0]?.chip_map?.version || 0;
  const locked = currentVersion?.chip_map?.locked;
  const visibleChips = map.chips.filter((c) => !blockFilter || c.block === blockFilter);
  const duplicateCount = useMemo(() => map.chips.filter((c) => duplicateLabel(map.chips, c)).length, [map]);
  const unresolved = map.chips.filter((c) => !c.label.trim() || c.label.trim() === '?' || c.label.includes(' / ')).length;
  const selected = map.chips.find((c) => c.id === selectedChip);

  const changeVersion = (id) => {
    const version = data.versions.find((v) => v.dataset_id === id);
    if (version) {
      setSelectedVersion(id);
      setMap(copyMap(version.chip_map));
      setSelectedChip(null);
    } else {
      setSelectedVersion(null);
      setMap(copyMap(initial));
    }
  };

  const toggleGroup = (key) => {
    const next = selectedGroups.includes(key) ? selectedGroups.filter((k) => k !== key) : [...selectedGroups, key];
    setSelectedGroups(next);
    setSelectedVersion(null);
    setMap(copyMap(chipsForGroups(data.geometry, next)));
    setSelectedChip(null);
  };

  const renameBlock = (id, name) =>
    setMap((old) => ({ ...old, blocks: old.blocks.map((b) => b.id === id ? { ...b, name } : b) }));
  const moveChip = (chipId, block) =>
    setMap((old) => ({ ...old, chips: old.chips.map((c) => c.id === chipId ? { ...c, block } : c) }));
  const addBlock = () => {
    let n = map.blocks.length + 1;
    while (map.blocks.some((b) => b.id === `B${n}`)) n++;
    setMap((old) => ({ ...old, blocks: [...old.blocks, { id: `B${n}`, name: `B${n}` }] }));
  };
  const mergeBlock = (id, targetId) => {
    if (!targetId || id === targetId) return;
    setMap((old) => ({
      blocks: old.blocks.filter((b) => b.id !== id),
      chips: old.chips.map((c) => c.block === id ? { ...c, block: targetId } : c),
    }));
  };
  const removeChip = (id) => {
    setMap((old) => ({ ...old, chips: old.chips.filter((c) => c.id !== id) }));
    if (selectedChip === id) setSelectedChip(null);
  };

  const save = async () => {
    setSaving(true);
    setError('');
    try {
      const result = await saveChipMap(maskId, { ...map, expected_version: latestVersion });
      await load(result.map.dataset_id); // select the newly created latest version
      await onSaved?.(result.map);
    } catch (err) {
      setError(errorText(err, 'Failed to save reviewed chip map'));
    } finally {
      setSaving(false);
    }
  };

  if (!data) return <p className="muted">{error || 'Loading mask design…'}</p>;
  return (
    <div className="mask-review">
      <h3>{data.mask.dataset_name}</h3>
      {!data.geometry && (
        <div className="warning-message">
          Geometry is not ready yet. Ingestion: {data.ingestion?.map((r) => `${r.ingestion_class || 'ingestor'} — ${r.status}`).join(', ') || 'uploading / waiting for a request'}.
          {ingestionIsWaiting(data.geometry, data.ingestion)
            ? 'This page refreshes automatically.'
            : 'Extraction finished without readable geometry. Check the ingestion status and GDS file; automatic refresh has stopped.'}
        </div>
      )}
      {data.geometry && (
        <>
          <p className="muted">
            {data.geometry.source.file} · top cell {data.geometry.source.top_cell} · {data.geometry.shapes.length} shapes ·{' '}
            {data.geometry.labels.length} recovered labels · {data.geometry.unresolved_labels.length} unresolved labels
          </p>
          <div className="form-row">
            <div className="form-group">
              <label>Review starting point</label>
              <select value={selectedVersion || ''} onChange={(e) => changeVersion(e.target.value)}>
                <option value="">New suggestion from GDS geometry</option>
                {data.versions.map((v) => (
                  <option key={v.dataset_id} value={v.dataset_id}>
                    Version {v.chip_map.version} — {v.chip_map.chips.length} chips{v.chip_map.locked ? ' (in use / locked)' : ''}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {locked && <p className="warning-message">Version {currentVersion.chip_map.version} is used by a wafer and stays immutable. Saving creates a new version.</p>}
          {currentVersion && selectedVersion !== data.versions[0]?.dataset_id &&
            <p className="muted">Editing a copy of an older version. Saving creates version {latestVersion + 1}.</p>}

          <details className="outline-groups">
            <summary>Outline suggestions ({map.chips.length} chips selected)</summary>
            <p className="muted">Repeated sizes are suggested as chip outlines. Nested device geometry and duplicate layers can be enabled if needed; changing these replaces the current edit with a new suggestion.</p>
            {groups.map((group) => (
              <label key={group.key} className="confirm-checkbox">
                <input type="checkbox" checked={selectedGroups.includes(group.key)} onChange={() => toggleGroup(group.key)} />
                Layer {group.layer}, {group.width} × {group.height} mm — {group.count} shapes
                {group.nestedCount > 0 && <span className="muted"> ({group.nestedCount} nested)</span>}
                {group.duplicateCount > 0 && <span className="muted"> ({group.duplicateCount} duplicates)</span>}
              </label>
            ))}
          </details>

          <div className="mask-review-grid">
            <div>
              <ChipMapSvg map={map} selectedChips={new Set(selectedChip ? [selectedChip] : [])}
                          onChip={(chip) => setSelectedChip(chip.id)} />
              <p className="muted">Select a chip to edit its label or block. Coordinates and box sizes are in millimetres.</p>
              {selected && (
                <div className="selected-chip-editor">
                  <strong>{selected.label || 'Unlabelled chip'}</strong> <span className="muted">({selected.layer || 'no layer'})</span>
                  <div className="form-group">
                    <label>Printed label</label>
                    <input value={selected.label} onChange={(e) => setMap((old) => ({
                      ...old, chips: old.chips.map((c) => c.id === selected.id ? { ...c, label: e.target.value } : c),
                    }))} />
                  </div>
                  <div className="form-group">
                    <label>Block</label>
                    <select value={selected.block} onChange={(e) => moveChip(selected.id, e.target.value)}>
                      {map.blocks.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                    </select>
                  </div>
                  <button type="button" className="btn btn-secondary btn-small" onClick={() => removeChip(selected.id)}>Not a chip — remove</button>
                </div>
              )}
            </div>

            <div>
              <h4>Blocks</h4>
              {map.blocks.map((block) => (
                <div key={block.id} className="block-editor">
                  <input aria-label={`Name for ${block.id}`} value={block.name}
                         onChange={(e) => renameBlock(block.id, e.target.value)} />
                  <span className="muted">{map.chips.filter((c) => c.block === block.id).length} chips</span>
                  <select aria-label={`Merge ${block.name} into`} value="" onChange={(e) => mergeBlock(block.id, e.target.value)}>
                    <option value="">Merge into…</option>
                    {map.blocks.filter((b) => b.id !== block.id).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
                  </select>
                </div>
              ))}
              <button type="button" className="btn btn-secondary btn-small" onClick={addBlock}>+ New block / split target</button>
            </div>
          </div>

          <div className="chip-review-table-wrap">
            <div className="form-row">
              <h4>Chip labels ({visibleChips.length})</h4>
              <select value={blockFilter} onChange={(e) => setBlockFilter(e.target.value)}>
                <option value="">All blocks</option>
                {map.blocks.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
            </div>
            {(duplicateCount > 0 || unresolved > 0) &&
              <div className="warning-message">
                {duplicateCount > 0 && `${duplicateCount} chips share a printed label within their block. `}
                {unresolved > 0 && `${unresolved} chips have no printed label or an unresolved/ambiguous one. Blank labels get unique “unlabelled” names.`}
              </div>}
            <table className="chip-review-table">
              <thead><tr><th>Block</th><th>Printed label</th><th>Size (mm)</th><th /></tr></thead>
              <tbody>
                {visibleChips.map((chip) => {
                  const duplicate = duplicateLabel(map.chips, chip);
                  return (
                    <tr key={chip.id} className={duplicate || !chip.label || chip.label === '?' ? 'chip-warning' : ''}>
                      <td>{map.blocks.find((b) => b.id === chip.block)?.name || chip.block}</td>
                      <td>
                        <input aria-label={`Label for ${chip.id}`} value={chip.label} placeholder="?"
                               onFocus={() => setSelectedChip(chip.id)}
                               onChange={(e) => setMap((old) => ({
                                 ...old, chips: old.chips.map((c) => c.id === chip.id ? { ...c, label: e.target.value } : c),
                               }))} />
                        {duplicate && <span title="Duplicate within this block"> duplicate</span>}
                      </td>
                      <td>{(chip.outline[2] - chip.outline[0]).toFixed(3)} × {(chip.outline[3] - chip.outline[1]).toFixed(3)}</td>
                      <td><button type="button" className="btn btn-secondary btn-small" onClick={() => removeChip(chip.id)}>Remove</button></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {error && <div className="error-message">{error}</div>}
          <button type="button" className="btn btn-primary" disabled={saving || !map.chips.length} onClick={save}>
            {saving ? 'Saving…' : `Save reviewed map as version ${latestVersion + 1}`}
          </button>
          <p className="muted">Saving never changes older versions or wafers that already use them.</p>
        </>
      )}
    </div>
  );
};

export default MaskReviewEditor;
