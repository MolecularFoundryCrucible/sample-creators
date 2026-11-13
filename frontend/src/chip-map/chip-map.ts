/** Generic GDS geometry -> reviewed chip-map suggestions. No mask-specific layer or size rules. */
export type GdsShape = {
  layer: string
  x0: number
  y0: number
  x1: number
  y1: number
  n_points?: number
  fill?: number
}

export type GdsLabel = { text: string; x: number; y: number; source?: string }
export type UnresolvedLabel = { cell: string; x: number; y: number }
export type GdsGeometry = {
  units: "mm"
  source: Record<string, unknown>
  min_size_mm: number
  shapes: GdsShape[]
  labels: GdsLabel[]
  unresolved_labels: UnresolvedLabel[]
}

export type ChipBlock = { id: string; name: string }
export type ReviewedChip = {
  id: string
  block: string
  label: string
  outline: number[]
  layer?: string
}
export type ReviewedChipMap = {
  units: "mm"
  blocks: ChipBlock[]
  chips: ReviewedChip[]
  version?: number
  locked?: boolean
  used_by?: string[]
  reviewed_by?: string
  reviewed_at?: string
}
export type VersionedChipMap = { dataset_id: string; dataset_name?: string; chip_map: ReviewedChipMap }

export type OutlineGroup = {
  key: string
  layer: string
  width: number
  height: number
  count: number
  suggestedCount: number
  nestedCount: number
  duplicateCount: number
  defaultSelected: boolean
}
export type DraftChip = ReviewedChip & { groupKey: string; needsReview: boolean }
export type ChipMapDraft = { chips: DraftChip[]; blocks: ChipBlock[]; groups: OutlineGroup[] }

const width = (s: GdsShape) => s.x1 - s.x0
const height = (s: GdsShape) => s.y1 - s.y0
const area = (s: GdsShape) => width(s) * height(s)
const shapeId = (s: GdsShape) => `shape:${s.layer}:${s.x0}:${s.y0}:${s.x1}:${s.y1}`
const contains = (outer: GdsShape, point: { x: number; y: number }, margin = 0.05) =>
  outer.x0 - margin <= point.x && point.x <= outer.x1 + margin
  && outer.y0 - margin <= point.y && point.y <= outer.y1 + margin
const containsShape = (outer: GdsShape, inner: GdsShape) =>
  outer.x0 <= inner.x0 && outer.y0 <= inner.y0 && outer.x1 >= inner.x1 && outer.y1 >= inner.y1
const sameBox = (a: GdsShape, b: GdsShape) =>
  Math.abs(a.x0 - b.x0) <= 0.06 && Math.abs(a.y0 - b.y0) <= 0.06
  && Math.abs(a.x1 - b.x1) <= 0.06 && Math.abs(a.y1 - b.y1) <= 0.06

function groupShapes(shapes: GdsShape[]) {
  const groups = new Map<string, GdsShape[]>()
  for (const shape of shapes) {
    // Repeated dimensions are candidates; unique alignment marks and one-off structures are not.
    const key = `${shape.layer}|${width(shape).toFixed(3)}|${height(shape).toFixed(3)}`
    const group = groups.get(key) || []
    group.push(shape)
    groups.set(key, group)
  }
  return groups
}

/** Classify repeated shapes by size. Larger outlines win over nested device geometry by default. */
export function suggestChipMap(geometry: GdsGeometry): ChipMapDraft {
  const grouped = [...groupShapes(geometry.shapes).entries()]
    .filter(([, shapes]) => shapes.length >= 2)
    .map(([key, shapes]) => ({ key, shapes }))
    .sort((a, b) => area(b.shapes[0]) - area(a.shapes[0]) || b.shapes.length - a.shapes.length
      || a.key.localeCompare(b.key))

  // First collapse the same outline repeated on different GDS layers. Prefer the layer with
  // more occurrences of this shape (larger shapes win a size tie), independent of layer names.
  const duplicateIds = new Set<string>()
  const unique: { key: string; shape: GdsShape }[] = []
  const summaries = new Map<string, OutlineGroup>()
  for (const { key, shapes } of grouped) {
    summaries.set(key, {
      key, layer: shapes[0].layer,
      width: Number(width(shapes[0]).toFixed(3)), height: Number(height(shapes[0]).toFixed(3)),
      count: shapes.length, suggestedCount: 0, nestedCount: 0, duplicateCount: 0, defaultSelected: false,
    })
    for (const shape of shapes) {
      if (unique.some((other) => other.shape.layer !== shape.layer && sameBox(shape, other.shape))) {
        duplicateIds.add(shapeId(shape))
        summaries.get(key)!.duplicateCount++
      } else unique.push({ key, shape })
    }
  }

  // A single nested outline per host is often a deliberately nested chip. Many nested outlines
  // in one host are usually device geometry (WFR_04 has both), so suppress those by default.
  // Both kinds stay available as explicit outline-group toggles in the review editor.
  const hosts = new Map<string, { host: GdsShape; nested: typeof unique }>()
  const topLevel: typeof unique = []
  for (const candidate of unique) {
    const containing = unique.filter((other) => other.shape.layer !== candidate.shape.layer
      && containsShape(other.shape, candidate.shape) && area(other.shape) > area(candidate.shape) * 1.1)
    if (!containing.length) {
      topLevel.push(candidate)
      continue
    }
    const host = containing.sort((a, b) => area(a.shape) - area(b.shape))[0].shape
    const id = shapeId(host)
    const entry = hosts.get(id) || { host, nested: [] }
    entry.nested.push(candidate)
    hosts.set(id, entry)
  }
  const accepted = [...topLevel]
  for (const { nested } of hosts.values()) {
    if (nested.length === 1) accepted.push(nested[0])
    else for (const candidate of nested) summaries.get(candidate.key)!.nestedCount++
  }
  for (const { key } of accepted) summaries.get(key)!.suggestedCount++
  for (const summary of summaries.values()) summary.defaultSelected = summary.suggestedCount > 0

  const selected = [...summaries.values()].filter((g) => g.defaultSelected).map((g) => g.key)
  // Exclude duplicates even when another copy of the same group was selected by the reviewer.
  const draft = chipsForGroups(geometry, selected)
  const acceptedIds = new Set(accepted.map((c) => shapeId(c.shape)))
  draft.chips = draft.chips.filter((chip) => acceptedIds.has(chip.id) && !duplicateIds.has(chip.id))
  draft.blocks = [...new Set(draft.chips.map((c) => c.block))]
    .map((id) => ({ id, name: id }))
  return { ...draft, groups: [...summaries.values()] }
}

/** Rebuild after outline-group toggles. Explicitly selected nested groups are included. */
export function chipsForGroups(geometry: GdsGeometry, selectedGroups: string[]): Omit<ChipMapDraft, "groups"> {
  const selected = new Set(selectedGroups)
  const grouped = groupShapes(geometry.shapes)
  const candidates = [...grouped.entries()]
    .filter(([key, shapes]) => selected.has(key) && shapes.length >= 2)
    .sort((a, b) => a[0].localeCompare(b[0]))
  const chips: (DraftChip & { shape: GdsShape })[] = []
  for (const [groupKey, shapes] of candidates) {
    for (const shape of shapes) {
      const containedLabels = geometry.labels.filter((label) => contains(shape, label))
      const unresolved = geometry.unresolved_labels.filter((label) => contains(shape, label))
      const label = containedLabels.length
        ? containedLabels.map((l) => l.text).join(" / ")
        : unresolved.length ? "?" : ""
      chips.push({
        id: shapeId(shape),
        block: "",
        label,
        outline: [shape.x0, shape.y0, shape.x1, shape.y1],
        layer: shape.layer,
        groupKey,
        needsReview: containedLabels.length !== 1,
        shape,
      })
    }
  }

  // Blocks are connected components of same-sized outlines on the same layer. Scale the
  // adjacency distance with the chip size so this also works on masks with other dimensions.
  const parent = chips.map((_, i) => i)
  const find = (i: number): number => parent[i] === i ? i : (parent[i] = find(parent[i]))
  for (let i = 0; i < chips.length; i++) {
    for (let j = i + 1; j < chips.length; j++) {
      const a = chips[i].shape
      const b = chips[j].shape
      if (chips[i].layer !== chips[j].layer || Math.abs(width(a) - width(b)) > 0.1
          || Math.abs(height(a) - height(b)) > 0.1) continue
      const gap = Math.min(1.2, Math.max(width(a), height(a)) * 0.2)
      const disjoint = a.x1 + gap < b.x0 || b.x1 + gap < a.x0 || a.y1 + gap < b.y0 || b.y1 + gap < a.y0
      if (!disjoint) parent[find(i)] = find(j)
    }
  }
  const components = new Map<number, typeof chips>()
  chips.forEach((chip, i) => {
    const root = find(i)
    components.set(root, [...(components.get(root) || []), chip])
  })
  const ordered = [...components.values()].sort((a, b) =>
    Math.max(...b.map((c) => c.shape.y1)) - Math.max(...a.map((c) => c.shape.y1))
    || Math.min(...a.map((c) => c.shape.x0)) - Math.min(...b.map((c) => c.shape.x0)))
  const blocks: ChipBlock[] = []
  ordered.forEach((component, index) => {
    const id = `B${index + 1}`
    blocks.push({ id, name: id })
    component.forEach((chip) => { chip.block = id })
  })
  chips.sort((a, b) => Number(a.block.slice(1)) - Number(b.block.slice(1))
    || b.shape.y0 - a.shape.y0 || a.shape.x0 - b.shape.x0)
  return { chips: chips.map(({ shape: _, ...chip }) => chip), blocks }
}

export function duplicateLabels(chips: Pick<ReviewedChip, "block" | "label">[]): Set<string> {
  const seen = new Set<string>()
  const duplicates = new Set<string>()
  for (const chip of chips) {
    if (!chip.label) continue
    const key = `${chip.block}\0${chip.label}`
    if (seen.has(key)) duplicates.add(key)
    seen.add(key)
  }
  return duplicates
}

export function duplicateLabel(chips: Pick<ReviewedChip, "block" | "label">[], chip: ReviewedChip): boolean {
  return duplicateLabels(chips).has(`${chip.block}\0${chip.label}`)
}

/** Attach duplicate suffixes across the entire cutting step, not just within one chiplet. */
export function chipSampleNames(waferName: string, chips: Pick<ReviewedChip, "block" | "label">[]): string[] {
  const counts = new Map<string, number>()
  return chips.map((chip) => {
    const block = chip.block.trim().replace(/\s+/g, "_") || "block"
    const label = chip.label.trim().replace(/\s+/g, "_") || "unlabelled"
    const base = `${waferName}_${block}_${label}`
    const count = (counts.get(base) || 0) + 1
    counts.set(base, count)
    return count === 1 ? base : `${base}-${count}`
  })
}

export function chipletSampleName(waferName: string, blockName: string): string {
  return `${waferName.trim() || "wafer"}_${blockName.trim().replace(/\s+/g, "_") || "block"}`
}

/** Build name-keyed request metadata only after name edits, never key draft state by names. */
export function childDetailsPayload(
  children: Record<string, string[]>,
  details: Record<string, Record<string, unknown>[]>
): Record<string, Record<string, unknown>> {
  return Object.fromEntries(Object.entries(children).flatMap(([parentId, names]) =>
    names.map((name, index) => [name, details[parentId]?.[index] || {}])
  ))
}

export function blockOutline(chips: Pick<ReviewedChip, "outline">[]): number[] {
  if (!chips.length) throw new Error("A block needs at least one chip")
  return [
    Math.min(...chips.map((c) => c.outline[0])),
    Math.min(...chips.map((c) => c.outline[1])),
    Math.max(...chips.map((c) => c.outline[2])),
    Math.max(...chips.map((c) => c.outline[3])),
  ]
}
