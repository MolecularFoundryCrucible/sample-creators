import React, { useEffect, useState } from 'react';
import { blockOutline, chipletSampleName, chipSampleNames } from '../../../chip-map/chip-map.ts';
import ChipMapSvg from './ChipMapSvg';

export const retainChipletNames = (blocks, previousBlockIds, previousNames, nextBlockIds, waferName) => {
  const oldNames = new Map(blocks.filter((block) => previousBlockIds.includes(block.id))
    .map((block, index) => [block.id, previousNames[index]]));
  return blocks.filter((block) => nextBlockIds.includes(block.id))
    .map((block) => oldNames.get(block.id) ?? chipletSampleName(waferName, block.name));
};

/** Map-driven Step 14 / 19 child picker. Names and metadata stay aligned by parent/index. */
const MapChildrenEditor = ({ action, mapRecord, plannedChiplets, wafer, units, targets, children, setChildren, setChildDetails }) => {
  const map = mapRecord.chip_map;
  const [selectedBlocks, setSelectedBlocks] = useState({});
  const [selectedChips, setSelectedChips] = useState({});
  const cutChipIds = new Set(units.filter((u) => u.sample_type === 'chip' && u.chip_details?.chip_id)
    .map((u) => u.chip_details.chip_id));
  const chipsForParent = (parentId) => {
    const parent = units.find((u) => u.unique_id === parentId);
    const block = parent?.chip_details?.block;
    if (!block) return map.chips;
    const blockDef = map.blocks.find((b) => b.id === block || b.name === block);
    return blockDef ? map.chips.filter((c) => c.block === blockDef.id) : [];
  };
  const blocksForParent = (parentId) => {
    const ids = new Set(chipsForParent(parentId).map((c) => c.block));
    return map.blocks.filter((b) => ids.has(b.id));
  };
  const visibleChips = [...new Map(targets.flatMap(chipsForParent).map((c) => [c.id, c])).values()];
  const visibleMap = { ...map, chips: visibleChips };

  useEffect(() => {
    // Map-driven cutting starts empty: users explicitly select what was physically cut.
    const planned = action === 'create_chiplets' && plannedChiplets?.mask_design === mapRecord.dataset_id
      ? plannedChiplets.chiplets : [];
    const plannedNames = new Map(planned.map((p) => [p.block, p.name]));
    const initialBlocks = Object.fromEntries(targets.map((id) => [id, planned.map((p) => p.block)]));
    const initialChildren = {};
    const initialDetails = {};
    for (const parentId of targets) {
      const blocks = map.blocks.filter((b) => plannedNames.has(b.id));
      initialChildren[parentId] = blocks.map((b) => plannedNames.get(b.id) || chipletSampleName(wafer.sample_name, b.name));
      initialDetails[parentId] = blocks.map((block) => ({
        block: block.id, outline_mm: blockOutline(map.chips.filter((c) => c.block === block.id)),
        mask_design: mapRecord.dataset_id,
      }));
    }
    setSelectedBlocks(initialBlocks);
    setChildren((old) => ({ ...old, ...initialChildren }));
    setChildDetails(initialDetails);
  }, []);

  useEffect(() => {
    // Deselected parents must not leave children or metadata in the request.
    const activeOnly = (old) => Object.fromEntries(Object.entries(old).filter(([id]) => targets.includes(id)));
    setChildren(activeOnly);
    setChildDetails(activeOnly);
    setSelectedBlocks(activeOnly);
    setSelectedChips(activeOnly);
  }, [targets, setChildren, setChildDetails]);

  if (action === 'create_chiplets') {
    const apply = (nextBlocks) => {
      const nextChildren = {};
      const details = {};
      for (const parentId of targets) {
        const ids = nextBlocks[parentId] || [];
        const blocks = map.blocks.filter((b) => ids.includes(b.id));
        nextChildren[parentId] = blocks.map((b) => chipletSampleName(wafer.sample_name, b.name));
        details[parentId] = blocks.map((block) => ({
          block: block.id,
          outline_mm: blockOutline(map.chips.filter((c) => c.block === block.id)),
          mask_design: mapRecord.dataset_id,
        }));
      }
      setSelectedBlocks(nextBlocks);
      setChildren((old) => {
        for (const parentId of targets) {
          nextChildren[parentId] = retainChipletNames(
            map.blocks, selectedBlocks[parentId] || [], old[parentId] || [],
            nextBlocks[parentId] || [], wafer.sample_name,
          );
        }
        return { ...old, ...nextChildren };
      });
      setChildDetails(details);
    };
    const toggle = (parentId, blockId) => {
      if (!parentId) return;
      apply({
        ...selectedBlocks,
        [parentId]: (selectedBlocks[parentId] || []).includes(blockId)
          ? selectedBlocks[parentId].filter((id) => id !== blockId)
          : [...(selectedBlocks[parentId] || []), blockId],
      });
    };
    return (
      <div className="map-children-editor">
        <p>Select the blocks that were cut into chiplets. Each block creates one chiplet named
          {' '}<code>{wafer.sample_name}_&lt;block&gt;</code>; names can be edited below.</p>
        <ChipMapSvg map={map} selectedBlocks={new Set(targets.flatMap((id) => selectedBlocks[id] || []))}
                    onChip={(chip) => toggle(targets[0], chip.block)}
                    onBlock={(block) => toggle(targets[0], block.id)} />
        {targets.map((parentId) => (
          <div key={parentId} className="map-selection-controls">
            <div className="button-group">
              <button className="btn btn-secondary btn-small" onClick={() => apply({ ...selectedBlocks, [parentId]: map.blocks.map((b) => b.id) })}>All blocks</button>
              <button className="btn btn-secondary btn-small" onClick={() => apply({ ...selectedBlocks, [parentId]: [] })}>None</button>
            </div>
            <div className="target-list">
              {map.blocks.map((block) => (
                <label key={block.id} className="confirm-checkbox">
                  <input type="checkbox" checked={(selectedBlocks[parentId] || []).includes(block.id)}
                         onChange={() => toggle(parentId, block.id)} />
                  {block.name} ({map.chips.filter((c) => c.block === block.id).length} chips)
                </label>
              ))}
            </div>
          </div>
        ))}
        <SelectedNameInputs units={units} targets={targets} children={children}
                            setChildren={setChildren} noun="Chiplets" />
      </div>
    );
  }

  const apply = (nextChips) => {
    // Number duplicates across all parents together so this request never generates duplicate names.
    const chosen = targets.flatMap((parentId) => {
      const ids = new Set(nextChips[parentId] || []);
      return chipsForParent(parentId).filter((c) => ids.has(c.id) && !cutChipIds.has(c.id));
    });
    const names = chipSampleNames(wafer.sample_name, chosen.map((chip) => ({
      ...chip, block: map.blocks.find((b) => b.id === chip.block)?.name || chip.block,
    })));
    const byParent = Object.fromEntries(targets.map((id) => [id, []]));
    const details = Object.fromEntries(targets.map((id) => [id, []]));
    chosen.forEach((chip, index) => {
      // A chip belongs to exactly one selected block parent; uncut wafers may cover several blocks.
      const parentId = targets.find((id) => chipsForParent(id).some((c) => c.id === chip.id));
      if (!parentId) return;
      byParent[parentId].push(names[index]);
      details[parentId].push({
        chip_id: chip.id, block: chip.block, label: chip.label,
        outline_mm: chip.outline, mask_design: mapRecord.dataset_id,
      });
    });
    setSelectedChips(nextChips);
    setChildren((old) => ({ ...old, ...byParent }));
    setChildDetails(details);
  };
  const toggleChip = (chip) => {
    const parentId = targets.find((id) => chipsForParent(id).some((c) => c.id === chip.id));
    if (!parentId) return;
    const current = selectedChips[parentId] || [];
    apply({ ...selectedChips, [parentId]: current.includes(chip.id) ? current.filter((id) => id !== chip.id) : [...current, chip.id] });
  };
  const toggleBlock = (block) => {
    const parentId = targets.find((id) => blocksForParent(id).some((b) => b.id === block.id));
    if (!parentId) return;
    const ids = map.chips.filter((c) => c.block === block.id && !cutChipIds.has(c.id)).map((c) => c.id);
    const current = selectedChips[parentId] || [];
    const all = ids.every((id) => current.includes(id));
    apply({ ...selectedChips, [parentId]: all ? current.filter((id) => !ids.includes(id)) : [...new Set([...current, ...ids])] });
  };

  return (
    <div className="map-children-editor">
      <p>Click chips or whole blocks. Chip names default to <code>{wafer.sample_name}_&lt;block&gt;_&lt;label&gt;</code>
        {' '}(duplicates get <code>-2</code>, <code>-3</code>, …) and remain editable.</p>
      <ChipMapSvg map={visibleMap} selectedChips={new Set(targets.flatMap((id) => selectedChips[id] || []))}
                  disabledChips={cutChipIds} onChip={toggleChip} onBlock={toggleBlock} />
      <div className="button-group">
        <button className="btn btn-secondary btn-small"
                onClick={() => apply(Object.fromEntries(targets.map((id) => [id, chipsForParent(id).filter((c) => !cutChipIds.has(c.id)).map((c) => c.id)])))}>All available chips</button>
        <button className="btn btn-secondary btn-small" onClick={() => apply({})}>None</button>
      </div>
      {targets.map((parentId) => (
        <div key={parentId}>
          <strong>{units.find((u) => u.unique_id === parentId)?.sample_name}</strong>
          <div className="target-list">
            {blocksForParent(parentId).map((block) => (
              <button key={block.id} className="btn btn-secondary btn-small" onClick={() => toggleBlock(block)}>
                Toggle {block.name}
              </button>
            ))}
          </div>
          {!units.find((u) => u.unique_id === parentId)?.chip_details?.block && units.find((u) => u.unique_id === parentId)?.sample_type === 'chiplet' &&
            <p className="warning-message">This chiplet has no mask block metadata, so all map chips are offered. Check its parent assignment before recording.</p>}
        </div>
      ))}
      {cutChipIds.size > 0 && <p className="muted">{cutChipIds.size} map-derived chips were already cut and are disabled.</p>}
      <SelectedNameInputs units={units} targets={targets} children={children}
                          setChildren={setChildren} noun="Chips" />
    </div>
  );
};

const SelectedNameInputs = ({ units, targets, children, setChildren, noun }) => {
  const rename = (parentId, index, name) => {
    setChildren((old) => ({ ...old, [parentId]: (old[parentId] || []).map((n, i) => i === index ? name : n) }));
  };
  return targets.map((parentId) => (
    <div key={parentId} className="children-editor">
      <strong>{noun} from {units.find((u) => u.unique_id === parentId)?.sample_name} ({children[parentId]?.length || 0})</strong>
      <div className="children-names">
        {(children[parentId] || []).map((name, i) => (
          <input key={`${parentId}-${i}`} aria-label={`${noun} name ${i + 1}`} value={name}
                 onChange={(e) => rename(parentId, i, e.target.value)} />
        ))}
      </div>
    </div>
  ));
};

export default MapChildrenEditor;
