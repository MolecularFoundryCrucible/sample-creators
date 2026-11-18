import { describe, expect, it } from "vitest"
import {
  applyDatasetFieldEdits,
  applyMetadataEdits,
  buildDatasetFormDescriptor,
  buildFormDescriptor,
  DATASET_FORM_KEYS,
  foldIntoPacket,
  isMissing,
  otherDatasetFields,
  parseBiologicMptBytes,
  parseFilesForPreview,
  parseGcLogText,
} from "./gc_ec"
import {
  decodeH5Attr,
  detectNirvanaIngestor,
  readH5EmbeddedInfo,
  readNirvanaH5Positions,
} from "./h5_tools"
import { parseXrdText, readXrdFile } from "./inorganic_xrd"
import { readKalFields } from "./kratos_xps"
import { computeBlobSha256 } from "./sha256"
import {
  NIRVANA_LINE_SCAN_B64,
  NIRVANA_SPEC_RUN_B64,
  ROOT_UNIQUE_ID_B64,
  SPIN_RUN_B64,
} from "./test_h5_fixtures"

function b64ToArrayBuffer(b64: string): ArrayBuffer {
  const binary = atob(b64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes.buffer
}

describe("computeBlobSha256", () => {
  it("hashes empty blob", async () => {
    const blob = new Blob([])
    const hash = await computeBlobSha256(blob)
    expect(hash).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
  })

  it("hashes short ASCII text", async () => {
    const blob = new Blob(["hello world"])
    const hash = await computeBlobSha256(blob)
    expect(hash).toBe("b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9")
  })

  it("hashes multi-chunk data > 4 MiB", async () => {
    const chunkSize = 1024 * 1024
    const chunks = [
      new Uint8Array(chunkSize).fill(65), // 'A'
      new Uint8Array(chunkSize).fill(66), // 'B'
      new Uint8Array(chunkSize).fill(67), // 'C'
      new Uint8Array(chunkSize).fill(68), // 'D'
      new Uint8Array(chunkSize).fill(69), // 'E'
    ]
    const blob = new Blob(chunks)
    expect(blob.size).toBe(5 * 1024 * 1024) // 5 MiB
    const hash = await computeBlobSha256(blob)
    expect(hash).toHaveLength(64)
    expect(hash).toMatch(/^[0-9a-f]{64}$/)
  })
})

describe("parseGcLogText", () => {
  const sampleLog = [
    "FID1.CHR\t04/15/2024\t10:20:30\tcol4\tcol5",
    "FID2.CHR\t04/15/2024\t10:30:00\tcol4\tcol5",
    "TCD1.CHR\t04/15/2024\t10:25:00\tcol4\tcol5",
  ].join("\n")

  it("parses multi-detector FID + TCD log with timestamps and keywords", () => {
    const packet = parseGcLogText(sampleLog, "run_log_01.log", 1234)
    expect(packet).not.toBeNull()
    if (!packet) return

    expect(packet.ingestion_class).toBe("GCLogIngestor")
    expect(packet.keywords).toEqual(["FID", "TCD"])
    expect(packet.dataset_fields.dataset_name).toBe("run_log_01")
    expect(packet.dataset_fields.measurement).toBe("Gas Chromatography")
    expect(packet.dataset_fields.data_type).toBe("GC Peak Table")
    expect(packet.dataset_fields.data_format).toBe("log")
    expect(packet.dataset_fields.timestamp).toBe("2024-04-15T10:20:30")
    expect(packet.dataset_fields.size).toBe(1234)

    const meta = packet.scientific_metadata
    expect(meta.technique).toBe("gas chromatography")

    const fid = meta.FID as Record<string, unknown>
    expect(fid.log_file).toBe("run_log_01.log")
    expect(fid.injection_count).toBe(2)
    expect(fid.first_injection_timestamp).toBe("2024-04-15T10:20:30")
    expect(fid.last_injection_timestamp).toBe("2024-04-15T10:30:00")
    expect(fid.injection_volume_uL).toBeNull()
    expect(fid.carrier_gas).toBeNull()
    expect(fid.product_gas_flow_rate_sccm).toBeNull()

    const tcd = meta.TCD as Record<string, unknown>
    expect(tcd.log_file).toBe("run_log_01.log")
    expect(tcd.injection_count).toBe(1)
    expect(tcd.first_injection_timestamp).toBe("2024-04-15T10:25:00")
    expect(tcd.last_injection_timestamp).toBe("2024-04-15T10:25:00")
  })

  it("returns null for non-log or insufficient columns", () => {
    expect(parseGcLogText(sampleLog, "run.txt", 100)).toBeNull()
    expect(parseGcLogText("col1\tcol2\tcol3\n", "run.log", 100)).toBeNull()
    expect(parseGcLogText("", "run.log", 0)).toBeNull()
  })
})

describe("parseBiologicMptBytes", () => {
  function makeMptContent(acqStarted = "04/15/2024 10:20:30.123456"): Uint8Array {
    const lines = [
      "EC-Lab ASCII FILE",
      "Nb header lines : 11",
      "Cyclic Voltammetry",
      "Device : VSP-300",
      "Run on channel : 1",
      `Acquisition started on : ${acqStarted}`,
      "Technique started on : 04/15/2024 10:21:00",
      "Electrode surface area : 4.000 cm²",
      "ti (h:m:s)   1:00:00",
      "EC-Lab for windows v11.30",
      "time/s\tI/mA\tEwe/V",
      "0.0\t0.1\t0.5",
      "1.0\t0.2\t0.6",
      "2.0\t0.3\t0.7",
      "3.0\t0.4\t0.8",
      "4.0\t0.5\t0.9",
    ]
    return new TextEncoder().encode(lines.join("\n"))
  }

  it("parses latin-1 .mpt with fractional seconds and computes interval median", () => {
    const bytes = makeMptContent()
    const packet = parseBiologicMptBytes(bytes, "ec_run.mpt", 2048)
    expect(packet).not.toBeNull()
    if (!packet) return

    expect(packet.ingestion_class).toBe("BiologicMptIngestor")
    expect(packet.dataset_fields.dataset_name).toBe("ec_run")
    expect(packet.dataset_fields.measurement).toBe("Cyclic Voltammetry")
    expect(packet.dataset_fields.data_type).toBe("Electrochemistry Time Series")
    expect(packet.dataset_fields.data_format).toBe("mpt")
    expect(packet.dataset_fields.timestamp).toBe("2024-04-15T10:20:30.123456")
    expect(packet.dataset_fields.size).toBe(2048)

    const meta = packet.scientific_metadata
    expect(meta.technique).toBe("Cyclic Voltammetry")
    expect(meta.device).toBe("VSP-300")
    expect(meta.channel).toBe("1")
    expect(meta.software).toBe("EC-Lab for windows v11.30")
    expect(meta.electrode_surface_area_cm2).toBe(4.0)
    expect(meta.point_count).toBe(5)
    expect(meta.duration_s).toBe(4.0)
    expect(meta.sampling_interval_s).toBe(1.0)
    expect(meta.reference_electrode).toBeNull()
    expect(meta.ir_compensation_ohm).toBeNull()
  })

  it("parses timestamp without fractional seconds", () => {
    const bytes = makeMptContent("04/15/2024 10:20:30")
    const packet = parseBiologicMptBytes(bytes, "ec_run.mpt", 1024)
    expect(packet).not.toBeNull()
    if (!packet) return
    expect(packet.dataset_fields.timestamp).toBe("2024-04-15T10:20:30")
    expect(packet.scientific_metadata.acquisition_started_on).toBe("2024-04-15T10:20:30")
  })

  it("returns null for non-.mpt or invalid header", () => {
    const bytes = makeMptContent()
    expect(parseBiologicMptBytes(bytes, "ec_run.csv", 1000)).toBeNull()
    const invalidHeader = new TextEncoder().encode("SOME OTHER FILE\n")
    expect(parseBiologicMptBytes(invalidHeader, "ec_run.mpt", 1000)).toBeNull()
  })
})

describe("parseFilesForPreview & folding", () => {
  it("folds .mpt and .log into combined preview packet, sums sizes, records collisions", async () => {
    const mptContent = [
      "EC-Lab ASCII FILE",
      "Nb header lines : 6",
      "Cyclic Voltammetry",
      "Device : VSP-300",
      "Acquisition started on : 04/15/2024 10:20:30",
      "time/s\tI/mA\tEwe/V",
      "0.0\t0.1\t0.5",
    ].join("\n")

    const gcContent = [
      "FID1.CHR\t04/15/2024\t10:20:30\tcol4\tcol5",
    ].join("\n")

    const files = [
      {
        name: "run.mpt",
        size: 500,
        arrayBuffer: async () => new TextEncoder().encode(mptContent).buffer as ArrayBuffer,
      },
      {
        name: "run.log",
        size: 300,
        text: async () => gcContent,
      },
      {
        name: "unsupported.bin",
        size: 100,
      },
    ]

    const { packet, collisions, per_file, skipped } = await parseFilesForPreview(files)

    expect(skipped).toEqual(["unsupported.bin"])
    expect(per_file).toEqual([
      { file: "run.mpt", ingestion_class: "BiologicMptIngestor" },
      { file: "run.log", ingestion_class: "GCLogIngestor" },
    ])

    // Size summed
    expect(packet.dataset_fields.size).toBe(800)

    // Scientific metadata combined
    expect(packet.scientific_metadata.device).toBe("VSP-300")
    expect(packet.scientific_metadata.FID).toBeDefined()

    // Collision recorded for differing technique
    expect(collisions.length).toBeGreaterThan(0)
    const techCollision = collisions.find((c) => c.field === "technique")
    expect(techCollision).toBeDefined()
    expect(techCollision?.kept).toBe("Cyclic Voltammetry")
    expect(techCollision?.discarded).toBe("gas chromatography")
    expect(techCollision?.file).toBe("run.log")
  })

  it("buildFormDescriptor generates fields with missing/locked/hidden checks", () => {
    const meta = {
      device: "VSP-300",
      unknown_val: "unknown",
      null_val: null,
      parse_provenance: { hash: "123" },
      size: 100,
      nested: {
        setting_a: 42,
      },
    }

    const fields = buildFormDescriptor(meta)
    const keys = fields.map((f) => f.key)

    // parse_provenance should be hidden
    expect(keys).not.toContain("parse_provenance")
    expect(keys).not.toContain("parse_provenance.hash")

    // device is editable and not missing
    const devField = fields.find((f) => f.key === "device")
    expect(devField?.editable).toBe(true)
    expect(devField?.missing).toBe(false)

    // unknown_val is missing
    const unkField = fields.find((f) => f.key === "unknown_val")
    expect(unkField?.missing).toBe(true)

    // null_val is missing
    const nullField = fields.find((f) => f.key === "null_val")
    expect(nullField?.missing).toBe(true)

    // size is locked
    const sizeField = fields.find((f) => f.key === "size")
    expect(sizeField?.editable).toBe(false)

    // nested setting
    const nestedField = fields.find((f) => f.key === "nested.setting_a")
    expect(nestedField?.value).toBe(42)
    expect(nestedField?.type).toBe("integer")
    expect(nestedField?.group_labels).toEqual(["nested"])
  })

  it("buildDatasetFormDescriptor & otherDatasetFields work as expected", () => {
    expect(DATASET_FORM_KEYS.has("dataset_name")).toBe(true)
    expect(isMissing(null)).toBe(true)
    expect(isMissing("na")).toBe(true)
    expect(isMissing("valid")).toBe(false)

    const datasetFields = {
      dataset_name: "test_ds",
      measurement: "cyclic voltammetry",
      data_type: "timeseries",
      session_name: null,
      size: 1024,
      public: false,
    }

    const formDesc = buildDatasetFormDescriptor(datasetFields)
    expect(formDesc).toHaveLength(4)
    expect(formDesc.find((f) => f.key === "dataset_name")?.value).toBe("test_ds")
    expect(formDesc.find((f) => f.key === "session_name")?.missing).toBe(true)

    const other = otherDatasetFields(datasetFields)
    expect(other).toEqual({ size: 1024, public: false })
  })

  it("foldIntoPacket merges packets directly", () => {
    const base = {
      scientific_metadata: { a: 1 },
      dataset_fields: { size: 10 },
      keywords: ["k1"],
      samples: [{ unique_id: "s1" }],
      children: [],
      thumbnails: [],
      ingestion_class: "A",
    }
    const incoming = {
      scientific_metadata: { b: 2 },
      dataset_fields: { size: 20 },
      keywords: ["k2"],
      samples: [{ unique_id: "s1" }, { unique_id: "s2" }],
      children: [],
      thumbnails: [],
      ingestion_class: "B",
    }
    const collisions: any[] = []
    foldIntoPacket(base, incoming, collisions, "file_b")
    expect(base.scientific_metadata).toEqual({ a: 1, b: 2 })
    expect(base.dataset_fields.size).toBe(30)
    expect(base.keywords).toEqual(["k1", "k2"])
    expect(base.samples).toHaveLength(2)
  })

  it("applyDatasetFieldEdits and applyMetadataEdits update packet correctly", () => {
    const packet = {
      scientific_metadata: {
        technique: "gas chromatography",
        FID: { carrier_gas: null },
      },
      dataset_fields: {
        dataset_name: "old_name",
        measurement: "old_measurement",
        size: 500,
      },
      keywords: [],
      samples: [],
      children: [],
      thumbnails: [],
      ingestion_class: "GCLogIngestor",
    }

    applyDatasetFieldEdits(packet, {
      dataset_name: "new_name",
      size: 9999, // Should be ignored because size is not in DATASET_FORM_KEYS
    })
    expect(packet.dataset_fields.dataset_name).toBe("new_name")
    expect(packet.dataset_fields.size).toBe(500)

    applyMetadataEdits(packet, {
      "FID.carrier_gas": "Helium",
      "size": 9999, // locked field, ignored
      "new_group.new_field": "val123",
    })
    expect((packet.scientific_metadata.FID as any).carrier_gas).toBe("Helium")
    expect((packet.scientific_metadata as any).size).toBeUndefined()
    expect((packet.scientific_metadata as any).new_group.new_field).toBe("val123")
  })
})

describe("inorganic_xrd parsers", () => {
  it("parses multi-sample tab-separated line", () => {
    const text = "SampleA\tSampleB\tSampleC\n10.0\t20.0\t30.0\n"
    const result = parseXrdText(text)
    expect(result).toEqual([
      { position: "S01", name: "SampleA", uuid: "", excluded: false },
      { position: "S02", name: "SampleB", uuid: "", excluded: false },
      { position: "S03", name: "SampleC", uuid: "", excluded: false },
    ])
  })

  it("parses single-sample line", () => {
    const text = "SingleSample\n10.0\t20.0\n"
    const result = parseXrdText(text)
    expect(result).toEqual([
      { position: "S01", name: "SingleSample", uuid: "", excluded: false },
    ])
  })

  it("parses empty text as S01 with empty name", async () => {
    const blob = new Blob([""])
    const result = await readXrdFile(blob)
    expect(result).toEqual([
      { position: "S01", name: "", uuid: "", excluded: false },
    ])
  })
})

describe("h5_tools parsers", () => {
  it("detectNirvanaIngestor distinguishes spec_run from line_scan", () => {
    expect(detectNirvanaIngestor("20261118_pollux_multipos_spec_run_01.h5")).toBe(
      "NirvanaMultiPosSpecRunIngestor"
    )
    expect(detectNirvanaIngestor("20261118_pollux_multipos_line_scan_01.h5")).toBe(
      "NirvanaMultiPosLineScanIngestor"
    )
  })

  it("decodeH5Attr cleans strings, Uint8Arrays, numbers, and null-padding", () => {
    expect(decodeH5Attr("hello\0\0")).toBe("hello")
    expect(decodeH5Attr(new Uint8Array([65, 66, 67, 0]))).toBe("ABC")
    expect(decodeH5Attr(42)).toBe("42")
    expect(decodeH5Attr(true)).toBe("true")
    expect(decodeH5Attr(null)).toBe("")
    expect(decodeH5Attr(["item1\0", "item2"])).toBe("item1 item2")
  })

  it("readNirvanaH5Positions extracts positions from Nirvana line_scan H5", async () => {
    const buf = b64ToArrayBuffer(NIRVANA_LINE_SCAN_B64)
    const positions = await readNirvanaH5Positions(buf, "test_line_scan.h5")
    expect(positions).toEqual([
      {
        position: "S01",
        raw_key: "pos_001",
        name: "Sample_A",
        uuid: "uuid-111",
        tray_uuid: "",
        tray_name: "",
        excluded: false,
      },
      {
        position: "S02",
        raw_key: "pos_002",
        name: "Sample_B",
        uuid: "uuid-222",
        tray_uuid: "",
        tray_name: "",
        excluded: false,
      },
    ])
  })

  it("readNirvanaH5Positions extracts positions from Nirvana spec_run H5", async () => {
    const buf = b64ToArrayBuffer(NIRVANA_SPEC_RUN_B64)
    const positions = await readNirvanaH5Positions(buf, "test_spec_run.h5")
    expect(positions).toEqual([
      {
        position: "S01",
        raw_key: "pos_001",
        name: "Sample_PL_1",
        uuid: "uuid-pl-1",
        tray_uuid: "",
        tray_name: "",
        excluded: false,
      },
    ])
  })

  it("readH5EmbeddedInfo extracts dsid, projectId, and deduped trays from spin_run", async () => {
    const buf = b64ToArrayBuffer(SPIN_RUN_B64)
    const info = await readH5EmbeddedInfo(buf, "spin_run.h5")
    expect(info.dsid).toBe("spin_dsid_001")
    expect(info.projectId).toBe("PROP_123")
    expect(info.trays).toEqual([
      { mfid: "tray_01", name: "Tray Alpha" },
      { mfid: "tray_02", name: "Tray Beta" },
    ])
  })

  it("readH5EmbeddedInfo extracts root unique_id and project from fallback H5", async () => {
    const buf = b64ToArrayBuffer(ROOT_UNIQUE_ID_B64)
    const info = await readH5EmbeddedInfo(buf, "root_unique.h5")
    expect(info.dsid).toBe("root_unique_dsid_999")
    expect(info.projectId).toBe("PROJ_888")
    expect(info.trays).toEqual([])
  })
})

describe("readKalFields", () => {
  it("extracts acquisition parameters from multi-region .kal file", async () => {
    const text = `
Dataset filename = test_sample.kal
Dataset Comment = Multi region sample run

Object name = Survey/1
  Technique = F_XPS
  3191 NICPU X-ray Gun Active Anode Material = F_NICPU_XRAY_ANODE_STD_MONO
  NICPU X-ray Gun Anode HT Voltage = 15000 V
  NICPU X-ray Gun Emission Current = 0.005 A
  Xray Reference Energy = F_REFER_TO_XRAY_MONO_AL
  Spectrum scan start = 0
  Spectrum scan step size = 1.0
  Ordinate values = {10, 20, 30}

Object name = C 1s/2
  Technique = F_XPS
  Spectrum scan start = 280
  Spectrum scan step size = 0.1
  Ordinate values = {100, 250, 400}

Object name = Stage Event
  Stage Position Name = S37
`
    const blob = new Blob([text], { type: "text/plain" })
    const fields = await readKalFields(blob)
    expect(fields).toEqual({
      anode_material: "Al Mono",
      anode_voltage_V: 15000,
      emission_current_A: 0.005,
      photon_energy_eV: 1486.69,
      stage_position_name: "S37",
      technique: "XPS",
      dataset_comment: "Multi region sample run",
      total_spectra: 2,
      regions: ["Survey", "C 1s"],
    })
  })

  it("extracts parameters from depth-profile .kal with Scan Sweep OBJECT and comment", async () => {
    const text = `
Dataset filename = depth.kal
Dataset Comment = Etch depth profile

Object name = Ion Gun Etch
  Scan Sweep OBJECT = {
    NICPU X-ray Gun Active Anode Material = F_NICPU_XRAY_ANODE_STD_MONO
    NICPU X-ray Gun Anode HT Voltage = 15000 V
    NICPU X-ray Gun Emission Current = 0.005 A
    Xray Reference Energy = F_REFER_TO_XRAY_MONO_AL
  }

Object name = Si 2p/1
  Technique = F_XPS
  Spectrum scan start = 95
  Spectrum scan step size = 0.1
  Ordinate values = {50, 60, 70}
`
    const blob = new Blob([text], { type: "text/plain" })
    const fields = await readKalFields(blob)
    expect(fields).toEqual({
      anode_material: "Al Mono",
      anode_voltage_V: 15000,
      emission_current_A: 0.005,
      photon_energy_eV: 1486.69,
      technique: "XPS",
      dataset_comment: "Etch depth profile",
      total_spectra: 1,
      regions: ["Si 2p"],
    })
  })

  it("returns null for binary content with NUL bytes", async () => {
    const blob = new Blob([new Uint8Array([0x41, 0x00, 0x42])])
    const fields = await readKalFields(blob)
    expect(fields).toBeNull()
  })

  it("returns null for event-only .kal without spectra", async () => {
    const text = `
Dataset filename = event_only.kal
Dataset Comment = Just an event

Object name = Ion Gun Etch
  Scan Sweep OBJECT = {
    NICPU X-ray Gun Active Anode Material = F_NICPU_XRAY_ANODE_STD_MONO
  }
`
    const blob = new Blob([text], { type: "text/plain" })
    const fields = await readKalFields(blob)
    expect(fields).toBeNull()
  })
})
