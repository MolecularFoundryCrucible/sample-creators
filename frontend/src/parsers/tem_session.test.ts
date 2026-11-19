import { describe, expect, it } from "vitest"
import {
  filesToSessionInputs,
  MAX_FILE_BYTES,
  planTemSessionUploads,
  TEM_ACCEPTABLE_EXTENSIONS,
} from "./tem_session"
import type { SessionFileInput } from "./tem_session"

function makeFakeFile(name: string, size: number): File {
  const file = new File(["x"], name, { type: "application/octet-stream" })
  Object.defineProperty(file, "size", { value: size, configurable: true })
  return file
}

function makeInput(relativePath: string, size = 1024): SessionFileInput {
  const normalized = relativePath.replace(/\\/g, "/")
  const baseName = normalized.split("/").filter(Boolean).pop() || relativePath
  return {
    file: makeFakeFile(baseName, size),
    relativePath,
  }
}

describe("filesToSessionInputs", () => {
  it("uses webkitRelativePath when present and falls back to file.name", () => {
    const withRel = makeFakeFile("img.dm4", 100)
    Object.defineProperty(withRel, "webkitRelativePath", {
      value: "run_01/img.dm4",
      configurable: true,
    })
    const bare = makeFakeFile("bare.dm4", 200)

    const inputs = filesToSessionInputs([withRel, bare])
    expect(inputs).toEqual([
      { file: withRel, relativePath: "run_01/img.dm4" },
      { file: bare, relativePath: "bare.dm4" },
    ])
  })
})

describe("planTemSessionUploads", () => {
  it("pairs multi-series .ser files with shared .emi and plain .ser with matching .emi", () => {
    const plan = planTemSessionUploads([
      makeInput("2026-11-18_TEAM05/foo_1.ser", 1000),
      makeInput("2026-11-18_TEAM05/foo_2.ser", 2000),
      makeInput("2026-11-18_TEAM05/foo.emi", 250),
      makeInput("2026-11-18_TEAM05/Acq.SER", 1500),
      makeInput("2026-11-18_TEAM05/acq.EMI", 300),
    ])

    expect(plan.folderName).toBe("2026-11-18_TEAM05")
    expect(plan.items).toHaveLength(3)
    expect(plan.ignoredCount).toBe(0)
    expect(plan.companionCount).toBe(3)
    expect(plan.emptyFiles).toEqual([])
    expect(plan.oversizedFiles).toEqual([])

    const byName = new Map(plan.items.map((item) => [item.datasetName, item]))

    const acq = byName.get("Acq.SER")
    expect(acq).toBeDefined()
    expect(acq?.dataFormat).toBe("ser")
    expect(acq?.companionFiles.map((f) => f.name)).toEqual(["acq.EMI"])
    expect(acq?.totalBytes).toBe(1800)
    expect(acq?.warning).toBeUndefined()

    const foo1 = byName.get("foo_1.ser")
    const foo2 = byName.get("foo_2.ser")
    expect(foo1?.companionFiles.map((f) => f.name)).toEqual(["foo.emi"])
    expect(foo2?.companionFiles.map((f) => f.name)).toEqual(["foo.emi"])
    expect(foo1?.totalBytes).toBe(1250)
    expect(foo2?.totalBytes).toBe(2250)
    expect(plan.totalUploadBytes).toBe(1800 + 1250 + 2250)
  })

  it("records a non-blocking warning when a .ser file has no matching .emi", () => {
    const plan = planTemSessionUploads([
      makeInput("session_a/lonely_1.ser", 512),
      makeInput("session_a/orphan.emi", 128),
    ])

    expect(plan.items).toHaveLength(1)
    expect(plan.items[0].datasetName).toBe("lonely_1.ser")
    expect(plan.items[0].companionFiles).toEqual([])
    expect(plan.items[0].warning).toContain("lonely.emi")
    expect(plan.companionCount).toBe(0)
    // orphan.emi is neither an acceptable primary file nor a paired companion
    expect(plan.ignoredCount).toBe(1)
  })

  it("pairs .mrc with .rawtlt and .txt in order while preserving standalone .txt item (legacy parity)", () => {
    const plan = planTemSessionUploads([
      makeInput("tomo_session/tomo.mrc", 5000),
      makeInput("tomo_session/tomo.txt", 400),
      makeInput("tomo_session/tomo.rawtlt", 300),
      makeInput("tomo_session/partial.mrc", 4000),
      makeInput("tomo_session/partial.rawtlt", 200),
    ])

    expect(plan.items).toHaveLength(3)
    expect(plan.ignoredCount).toBe(0)

    const byName = new Map(plan.items.map((item) => [item.datasetName, item]))

    const tomoMrc = byName.get("tomo.mrc")
    expect(tomoMrc?.dataFormat).toBe("mrc")
    expect(tomoMrc?.companionFiles.map((f) => f.name)).toEqual([
      "tomo.rawtlt",
      "tomo.txt",
    ])
    expect(tomoMrc?.totalBytes).toBe(5700)

    const tomoTxt = byName.get("tomo.txt")
    expect(tomoTxt).toBeDefined()
    expect(tomoTxt?.dataFormat).toBe("txt")
    expect(tomoTxt?.companionFiles).toEqual([])
    expect(tomoTxt?.totalBytes).toBe(400)

    const partialMrc = byName.get("partial.mrc")
    expect(partialMrc?.companionFiles.map((f) => f.name)).toEqual(["partial.rawtlt"])
    expect(partialMrc?.totalBytes).toBe(4200)

    expect(plan.companionCount).toBe(3)
    expect(plan.totalUploadBytes).toBe(5700 + 400 + 4200)
  })

  it("does not cross-pair same-named sidecars across nested subdirectories", () => {
    const plan = planTemSessionUploads([
      makeInput("run_nested/subA/Acq_1.ser", 1000),
      makeInput("run_nested/subA/Acq.emi", 200),
      makeInput("run_nested/subB/Acq_1.ser", 1100),
      makeInput("run_nested/subA/tilt.mrc", 2000),
      makeInput("run_nested/subB/tilt.rawtlt", 150),
    ])

    expect(plan.items).toHaveLength(3)

    const byPath = new Map(plan.items.map((item) => [item.relativePath, item]))

    const serA = byPath.get("run_nested/subA/Acq_1.ser")
    expect(serA?.directoryPath).toBe("run_nested/subA")
    expect(serA?.companionFiles.map((f) => f.name)).toEqual(["Acq.emi"])
    expect(serA?.warning).toBeUndefined()

    const serB = byPath.get("run_nested/subB/Acq_1.ser")
    expect(serB?.directoryPath).toBe("run_nested/subB")
    expect(serB?.companionFiles).toEqual([])
    expect(serB?.warning).toContain("Acq.emi")

    const mrcA = byPath.get("run_nested/subA/tilt.mrc")
    expect(mrcA?.companionFiles).toEqual([])
    // tilt.rawtlt in subB is unpaired so counted as ignored
    expect(plan.ignoredCount).toBe(1)
  })

  it("ignores OS junk files and unsupported non-TEM files", () => {
    const plan = planTemSessionUploads([
      makeInput("session_junk/.DS_Store", 6148),
      makeInput("session_junk/Thumbs.db", 2048),
      makeInput("session_junk/desktop.ini", 128),
      makeInput("session_junk/image.dm4.Zone.Identifier", 64),
      makeInput("session_junk/notes.pdf", 4096),
      makeInput("session_junk/sub/image.dm4", 8192),
    ])

    expect(plan.items).toHaveLength(1)
    expect(plan.items[0].datasetName).toBe("image.dm4")
    expect(plan.ignoredCount).toBe(5)
    expect(plan.emptyFiles).toEqual([])
    expect(plan.oversizedFiles).toEqual([])
  })

  it("flags zero-byte and >500 GiB primary or companion files and allows files >20 GiB up to 500 GiB", () => {
    const thirtyGiB = 30 * 1024 ** 3
    const overLimit = MAX_FILE_BYTES + 1

    const plan = planTemSessionUploads([
      makeInput("size_test/valid_30gib.dm4", thirtyGiB),
      makeInput("size_test/exact_500gib.emd", MAX_FILE_BYTES),
      makeInput("size_test/empty_primary.tif", 0),
      makeInput("size_test/oversized_primary.mrc", overLimit),
      makeInput("size_test/bad_emi_1.ser", 1024),
      makeInput("size_test/bad_emi.emi", 0),
      makeInput("size_test/huge_sidecar.mrc", 2048),
      makeInput("size_test/huge_sidecar.rawtlt", overLimit),
    ])

    expect(plan.items.map((i) => i.datasetName)).toEqual([
      "exact_500gib.emd",
      "valid_30gib.dm4",
    ])
    expect(plan.emptyFiles).toEqual([
      "size_test/bad_emi.emi",
      "size_test/empty_primary.tif",
    ])
    expect(plan.oversizedFiles).toEqual([
      "size_test/huge_sidecar.rawtlt",
      "size_test/oversized_primary.mrc",
    ])
    expect(plan.totalUploadBytes).toBe(thirtyGiB + MAX_FILE_BYTES)
  })

  it("normalizes Windows backslashes and leading ./ or / segments", () => {
    const plan = planTemSessionUploads([
      makeInput(".\\win_session\\sub\\scan_1.ser", 500),
      makeInput("/win_session/sub//scan.emi", 100),
      makeInput("./win_session/overview.png", 300),
    ])

    expect(plan.folderName).toBe("win_session")
    expect(plan.items).toHaveLength(2)
    expect(plan.items[0].relativePath).toBe("win_session/overview.png")
    expect(plan.items[1].relativePath).toBe("win_session/sub/scan_1.ser")
    expect(plan.items[1].directoryPath).toBe("win_session/sub")
    expect(plan.items[1].companionFiles.map((f) => f.name)).toEqual(["scan.emi"])
  })

  it("throws validation errors for empty input, bare files, or mixed top-level folders", () => {
    expect(() => planTemSessionUploads([])).toThrow(/No files selected/i)
    expect(() => planTemSessionUploads([makeInput("bare_file.dm4", 100)])).toThrow(
      /folder/i,
    )
    expect(() =>
      planTemSessionUploads([
        makeInput("folder_a/img1.dm4", 100),
        makeInput("folder_b/img2.dm4", 100),
      ]),
    ).toThrow(/single top-level session folder/i)
  })

  it("exposes all 15 expected TEM extensions by default", () => {
    expect(TEM_ACCEPTABLE_EXTENSIONS).toEqual([
      ".bcf",
      ".bmp",
      ".csv",
      ".dm3",
      ".dm4",
      ".emd",
      ".h5",
      ".jpeg",
      ".mrc",
      ".mtd",
      ".png",
      ".ser",
      ".tif",
      ".txt",
      ".xls",
    ])
  })
})
