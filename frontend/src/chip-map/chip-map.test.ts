import { describe, expect, it } from "vitest"
import { blockOutline, childDetailsPayload, chipletSampleName, chipSampleNames, chipsForGroups, suggestChipMap } from "./chip-map"
import type { GdsGeometry, GdsShape } from "./chip-map"

const shape = (layer: string, x0: number, y0: number, w = 12, h = 7): GdsShape =>
  ({ layer, x0, y0, x1: x0 + w, y1: y0 + h, n_points: 10, fill: 0.01 })

function geometry(): GdsGeometry {
  return {
    units: "mm",
    source: {},
    min_size_mm: 1,
    shapes: [
      shape("2/0", 0, 0), shape("2/0", 12, 0), shape("2/0", 0, 7), shape("2/0", 12, 7),
      shape("1/10", 0, 0), shape("1/10", 12, 0),
      shape("65/0", 1, 1, 2, 2), shape("65/0", 13, 1, 2, 2),
      shape("65/0", 4, 1, 1.5, 2), shape("65/0", 16, 1, 1.5, 2),
      shape("10/0", 40, 0, 5, 7), shape("10/0", 50, 0, 5, 7), shape("10/0", 60, 0, 5, 7),
      shape("9/0", 90, 90, 4, 4), // one-off alignment mark
    ],
    labels: [{ text: "R1D1", x: 5, y: 3 }, { text: "R1D2", x: 17, y: 3 }],
    unresolved_labels: [{ cell: "TEXT$7", x: 5, y: 10 }],
  }
}

describe("GDS chip-map suggestions", () => {
  it("uses repeated outlines, removes cross-layer duplicates and nested devices", () => {
    const draft = suggestChipMap(geometry())
    expect(draft.chips).toHaveLength(7)
    expect(draft.chips.filter((c) => c.layer === "2/0")).toHaveLength(4)
    expect(draft.chips.filter((c) => c.layer === "10/0")).toHaveLength(3)
    expect(draft.chips.some((c) => c.layer === "1/10" || c.layer === "65/0")).toBe(false)
    expect(draft.groups.find((g) => g.layer === "1/10")?.duplicateCount).toBe(2)
    expect(draft.groups.filter((g) => g.layer === "65/0").reduce((n, g) => n + g.nestedCount, 0)).toBe(4)
    expect(draft.groups.some((g) => g.layer === "9/0")).toBe(false)
  })

  it("labels by containment and flags missing, unresolved and ambiguous labels", () => {
    const draft = suggestChipMap(geometry())
    expect(draft.chips.find((c) => c.id.includes(":0:0:12:7"))?.label).toBe("R1D1")
    expect(draft.chips.find((c) => c.id.includes(":0:7:12:14"))).toMatchObject({ label: "?", needsReview: true })
    expect(draft.chips.filter((c) => c.layer === "10/0").every((c) => c.needsReview)).toBe(true)
  })

  it("clusters adjacent outlines into position-ordered blocks", () => {
    const draft = suggestChipMap(geometry())
    expect(draft.chips.filter((c) => c.layer === "2/0").every((c) => c.block === "B1")).toBe(true)
    expect(draft.chips.filter((c) => c.layer === "10/0").map((c) => c.block)).toEqual(["B2", "B3", "B4"])
  })

  it("allows a reviewer to include a nested layer explicitly", () => {
    const suggestion = suggestChipMap(geometry())
    const nested = suggestion.groups.filter((g) => g.layer === "65/0").map((g) => g.key)
    const selected = suggestion.groups.filter((g) => g.defaultSelected).map((g) => g.key)
    const draft = chipsForGroups(geometry(), [...selected, ...nested])
    expect(draft.chips.filter((c) => c.layer === "65/0")).toHaveLength(4)
  })
})

describe("sample naming", () => {
  it("suffixes duplicates within and across parents", () => {
    expect(chipSampleNames("QCMF_WFR_05", [
      { block: "B6", label: "R2D3" }, { block: "B6", label: "R2D3" }, { block: "B7", label: "R2D3" },
    ])).toEqual(["QCMF_WFR_05_B6_R2D3", "QCMF_WFR_05_B6_R2D3-2", "QCMF_WFR_05_B7_R2D3"])
  })

  it("bounds a chiplet by all selected chips in its block", () => {
    expect(blockOutline([{ outline: [1, 2, 3, 4] }, { outline: [-1, 3, 8, 9] }])).toEqual([-1, 2, 8, 9])
  })
})

describe("editable child names", () => {
  it("builds a chiplet name from the wafer and reviewed block", () => {
    expect(chipletSampleName("QCMF_WFR_05", "Top Test")).toBe("QCMF_WFR_05_Top_Test")
  })

  it("keeps metadata by parent/index through temporary name collisions", () => {
    const one = { chip_id: "chip-1", mask_design: "map-1" }
    const two = { chip_id: "chip-2", mask_design: "map-1" }
    expect(childDetailsPayload({ parent: ["B", "A"] }, { parent: [one, two] }))
      .toEqual({ B: one, A: two })
  })
})

describe("nested chips and nearly equal sizes", () => {
  it("keeps an isolated nested outline and clusters nominal-size variants", () => {
    const g = geometry()
    g.shapes = [
      shape("2/0", 0, 0, 20, 20), shape("2/0", 20, 0, 20, 20),
      shape("2/0", 0, 20, 20.04, 20), shape("2/0", 20, 20, 20.04, 20),
      shape("10/0", 2, 2, 5, 7), shape("10/0", 22, 2, 5, 7),
    ]
    const draft = suggestChipMap(g)
    expect(draft.chips.filter((c) => c.layer === "10/0")).toHaveLength(2)
    expect(new Set(draft.chips.filter((c) => c.layer === "2/0").map((c) => c.block)).size).toBe(1)
    expect(new Set(draft.chips.filter((c) => c.layer === "10/0").map((c) => c.block)).size).toBe(2)
  })
})
