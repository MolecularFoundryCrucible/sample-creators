import React from 'react';
import { blockOutline } from '../../../chip-map/chip-map.ts';

const COLORS = ['#1a73e8', '#e8710a', '#188038', '#d93025', '#9334e6', '#007b83', '#c5221f', '#5f6368', '#b06000', '#3949ab'];

/** Schematic GDS coordinates (mm). Only reviewed outlines are drawn, never device polygons. */
const ChipMapSvg = ({ map, selectedChips = new Set(), disabledChips = new Set(), onChip, onBlock,
                      selectedBlocks = new Set(), className = '' }) => {
  const chips = map?.chips || [];
  if (!chips.length) return <p className="muted">No chip outlines to display.</p>;
  const [minX, minY, maxX, maxY] = blockOutline(chips);
  const pad = Math.max(maxX - minX, maxY - minY) * 0.04 + 0.5;
  const viewBox = `${minX - pad} ${-maxY - pad} ${maxX - minX + 2 * pad} ${maxY - minY + 2 * pad}`;
  const fontSize = Math.max(maxX - minX, maxY - minY) / 75;
  const color = (blockId) => COLORS[Math.max(0, map.blocks.findIndex((b) => b.id === blockId)) % COLORS.length];
  const blockName = (id) => map.blocks.find((b) => b.id === id)?.name || id;
  const activate = (callback, value) => (event) => {
    if (!callback) return;
    if (event.type === 'keydown' && !['Enter', ' '].includes(event.key)) return;
    event.preventDefault();
    callback(value);
  };

  return (
    <svg className={`chip-map-svg ${className}`} viewBox={viewBox} role="img"
         aria-label={`Chip map with ${chips.length} chips in ${map.blocks.length} blocks`}>
      {map.blocks.map((block) => {
        const members = chips.filter((c) => c.block === block.id);
        if (!members.length) return null;
        const [x0, y0, x1, y1] = blockOutline(members);
        const active = selectedBlocks.has(block.name) || selectedBlocks.has(block.id);
        return (
          <g key={block.id} onClick={onBlock ? activate(onBlock, block) : undefined}
             onKeyDown={onBlock ? activate(onBlock, block) : undefined}
             role={onBlock ? 'button' : undefined} tabIndex={onBlock ? 0 : undefined}
             aria-label={`Select block ${block.name}`} className={onBlock ? 'map-clickable' : ''}>
            <rect x={x0} y={-y1} width={x1 - x0} height={y1 - y0} fill={color(block.id)}
                  fillOpacity={active ? 0.14 : 0.025} stroke={color(block.id)} strokeOpacity={active ? 1 : 0.35}
                  strokeWidth={active ? 2 : 1} vectorEffect="non-scaling-stroke" />
            <text x={x0} y={-y1 - fontSize * 0.35} fontSize={fontSize * 1.15} fontWeight="700" fill={color(block.id)}>
              {block.name}
            </text>
          </g>
        );
      })}
      {chips.map((chip) => {
        const [x0, y0, x1, y1] = chip.outline;
        const selected = selectedChips.has(chip.id);
        const disabled = disabledChips.has(chip.id);
        return (
          <g key={chip.id} onClick={!disabled && onChip ? activate(onChip, chip) : undefined}
             onKeyDown={!disabled && onChip ? activate(onChip, chip) : undefined}
             role={onChip && !disabled ? 'button' : undefined} tabIndex={onChip && !disabled ? 0 : undefined}
             aria-label={`${blockName(chip.block)} ${chip.label || 'unlabelled'}${disabled ? ', already cut' : ''}`}
             className={onChip && !disabled ? 'map-clickable' : ''} opacity={disabled ? 0.25 : 1}>
            <rect x={x0} y={-y1} width={x1 - x0} height={y1 - y0}
                  fill={selected ? color(chip.block) : '#fff'} fillOpacity={selected ? 0.55 : 0.65}
                  stroke={color(chip.block)} strokeWidth={selected ? 3 : 1.5} vectorEffect="non-scaling-stroke" />
            <text x={(x0 + x1) / 2} y={-(y0 + y1) / 2} fontSize={fontSize} textAnchor="middle"
                  dominantBaseline="middle" fill="#202124" pointerEvents="none">
              {chip.label || '?'}
            </text>
          </g>
        );
      })}
    </svg>
  );
};

export default ChipMapSvg;
