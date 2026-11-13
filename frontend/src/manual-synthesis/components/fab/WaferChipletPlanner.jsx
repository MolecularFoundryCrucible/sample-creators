import React, { useEffect, useRef, useState } from 'react';
import { chipletSampleName } from '../../../chip-map/chip-map.ts';
import { getChipMap } from '../../services/api';
import ChipMapSvg from './ChipMapSvg';

/** Planned chiplets only: no Crucible samples are created until Step 14 is recorded. */
const WaferChipletPlanner = ({ mapId, waferName, plan, onChange }) => {
  const [map, setMap] = useState(null);
  const [error, setError] = useState('');
  const editedNames = useRef(new Set());
  const selected = new Set(plan.map((p) => p.block));

  useEffect(() => {
    let cancelled = false;
    editedNames.current.clear();
    setMap(null);
    setError('');
    getChipMap(mapId).then((result) => {
      if (!cancelled) setMap(result.map.chip_map);
    }).catch((err) => {
      if (!cancelled) setError(err.response?.data?.detail || 'Failed to load the reviewed chip map');
    });
    return () => { cancelled = true; };
  }, [mapId]);

  useEffect(() => {
    if (!map) return;
    // Rename only untouched defaults after the wafer name changes; preserve deliberate edits.
    onChange(plan.map((entry) => ({
      ...entry,
      name: editedNames.current.has(entry.block)
        ? entry.name
        : chipletSampleName(waferName, map.blocks.find((b) => b.id === entry.block)?.name || entry.block),
    })));
  }, [waferName, mapId, map]);

  if (error) return <div className="error-message">{error}</div>;
  if (!map) return <p className="muted">Loading reviewed chip map…</p>;

  const toggle = (blockId) => {
    const nextSelected = new Set(selected);
    if (nextSelected.has(blockId)) {
      nextSelected.delete(blockId);
      editedNames.current.delete(blockId);
    } else nextSelected.add(blockId);
    const previous = new Map(plan.map((p) => [p.block, p.name]));
    onChange(map.blocks.filter((b) => nextSelected.has(b.id)).map((block) => ({
      block: block.id,
      name: previous.get(block.id) ?? chipletSampleName(waferName, block.name),
    })));
  };
  const duplicateNames = new Set(plan.filter((p, i) => plan.findIndex((q) => q.name.trim() === p.name.trim()) !== i).map((p) => p.name));

  return (
    <div className="map-children-editor wafer-chiplet-planner">
      <h4>Planned chiplets</h4>
      <p>Select the blocks this wafer will be cut into. Names are editable; these future samples are
        {' '}created only when Step 14 is recorded.</p>
      <ChipMapSvg map={map} selectedBlocks={selected} onChip={(chip) => toggle(chip.block)}
                  onBlock={(block) => toggle(block.id)} />
      <div className="button-group">
        <button type="button" className="btn btn-secondary btn-small"
                onClick={() => onChange(map.blocks.map((block) => {
                  const previous = plan.find((p) => p.block === block.id);
                  return previous || { block: block.id, name: chipletSampleName(waferName, block.name) };
                }))}>All blocks</button>
        <button type="button" className="btn btn-secondary btn-small"
                onClick={() => { editedNames.current.clear(); onChange([]); }}>None</button>
      </div>
      <div className="target-list">
        {map.blocks.map((block) => (
          <label key={block.id} className="confirm-checkbox">
            <input type="checkbox" checked={selected.has(block.id)} onChange={() => toggle(block.id)} />
            {block.name} ({map.chips.filter((c) => c.block === block.id).length} chips)
          </label>
        ))}
      </div>
      <div className="children-names">
        {plan.map((entry) => (
          <label key={entry.block}>
            {map.blocks.find((b) => b.id === entry.block)?.name || entry.block}
            <input aria-label={`Planned name for ${entry.block}`} value={entry.name}
                   onChange={(e) => { editedNames.current.add(entry.block); onChange(plan.map((p) => p.block === entry.block ? { ...p, name: e.target.value } : p)); }} />
          </label>
        ))}
      </div>
      {(plan.some((p) => !p.name.trim()) || duplicateNames.size > 0) &&
        <p className="warning-message">Planned chiplet names must be non-empty and unique.</p>}
    </div>
  );
};

export default WaferChipletPlanner;
