// Client-side parser for Gas Chromatography (.log) and Bio-Logic EC-Lab (.mpt) files,
// porting GCLogIngestor, BiologicMptIngestor, and prefect_backend.py preview folding.

export interface ParsedPacket {
  scientific_metadata: Record<string, unknown>
  dataset_fields: Record<string, unknown>
  keywords: string[]
  samples: Array<{ unique_id?: string; [k: string]: unknown }>
  children: Array<{ dataset?: { unique_id?: string }; [k: string]: unknown }>
  thumbnails: unknown[]
  ingestion_class: string
}

export interface Collision {
  field: string
  kept: unknown
  discarded: unknown
  file?: string
}

export interface FormFieldDescriptor {
  path: string[]
  key: string
  label: string
  group_labels: string[]
  description: string
  type: string
  items_type: string | null
  enum: unknown
  value: unknown
  editable: boolean
  missing: boolean
}

export const LOCKED_FIELDS = new Set(["size", "parse_provenance"])
export const HIDDEN_FIELDS = new Set(["parse_provenance"])
const MISSING_STRINGS = new Set(["na", "nan", "unknown"])

export const DATASET_FORM_FIELDS: Array<{ key: string; label: string; description: string }> = [
  { key: "dataset_name", label: "Dataset name", description: "Human-readable name for this dataset." },
  { key: "measurement", label: "Measurement", description: "What was measured, e.g. \"cyclic voltammetry\"." },
  { key: "data_type", label: "Data type", description: "Kind of data produced, e.g. \"spectrum\", \"image\"." },
  { key: "session_name", label: "Session", description: "Session this dataset belongs to." },
]
export const DATASET_FORM_KEYS = new Set(DATASET_FORM_FIELDS.map((f) => f.key))

export function basename(filePath: string): string {
  const norm = filePath.replace(/\\/g, "/")
  const idx = norm.lastIndexOf("/")
  return idx >= 0 ? norm.slice(idx + 1) : norm
}

export function stem(filePath: string): string {
  const base = basename(filePath)
  const idx = base.lastIndexOf(".")
  return idx > 0 ? base.slice(0, idx) : base
}

const pad2 = (n: number) => String(n).padStart(2, "0")

/**
 * Parses tab-delimited GC log text.
 * Returns null if file is not supported.
 */
export function parseGcLogText(text: string, fileName: string, fileSize: number): ParsedPacket | null {
  if (!fileName.toLowerCase().endsWith(".log")) return null

  const lines = text.split(/\r?\n/).filter((l) => l.trim().length > 0)
  if (lines.length === 0) return null

  // GC files should have min > 3 cols, tab separated
  if (lines[0].split("\t").length <= 3) return null

  const runNamePattern = /([A-Za-z]+)(\d+)\.CHR$/i
  const byDetector: Record<string, string[]> = {}

  for (const line of lines) {
    const fields = line.split("\t")
    if (fields.length < 3) continue

    const runMatch = runNamePattern.exec(fields[0].trim())
    if (!runMatch) continue

    const detector = runMatch[1].toUpperCase()

    // Parse %m/%d/%Y %H:%M:%S
    const rawTs = `${fields[1].trim()} ${fields[2].trim()}`
    const dtMatch = /^(\d{1,2})\/(\d{1,2})\/(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})$/.exec(rawTs)
    if (!dtMatch) continue

    const month = parseInt(dtMatch[1], 10)
    const day = parseInt(dtMatch[2], 10)
    const year = parseInt(dtMatch[3], 10)
    const hour = parseInt(dtMatch[4], 10)
    const min = parseInt(dtMatch[5], 10)
    const sec = parseInt(dtMatch[6], 10)

    if (month < 1 || month > 12 || day < 1 || day > 31 || hour > 23 || min > 59 || sec > 59) {
      continue
    }

    const iso = `${year}-${pad2(month)}-${pad2(day)}T${pad2(hour)}:${pad2(min)}:${pad2(sec)}`
    if (!byDetector[detector]) {
      byDetector[detector] = []
    }
    byDetector[detector].push(iso)
  }

  const sortedDetectors = Object.keys(byDetector).sort()
  const scientificMetadata: Record<string, unknown> = {
    technique: "gas chromatography",
  }

  let minFirstTimestamp: string | null = null

  for (const detector of sortedDetectors) {
    const timestamps = byDetector[detector]
    const firstTs = timestamps[0]
    const lastTs = timestamps[timestamps.length - 1]

    if (minFirstTimestamp === null || firstTs < minFirstTimestamp) {
      minFirstTimestamp = firstTs
    }

    scientificMetadata[detector] = {
      log_file: basename(fileName),
      injection_count: timestamps.length,
      first_injection_timestamp: firstTs,
      last_injection_timestamp: lastTs,
      injection_volume_uL: null,
      carrier_gas: null,
      product_gas_flow_rate_sccm: null,
    }
  }

  const datasetFields: Record<string, unknown> = {
    dataset_name: stem(fileName),
    measurement: "Gas Chromatography",
    data_type: "GC Peak Table",
    data_format: "log",
    timestamp: minFirstTimestamp,
    size: fileSize,
    public: false,
    session_name: null,
  }

  return {
    scientific_metadata: scientificMetadata,
    dataset_fields: datasetFields,
    keywords: sortedDetectors,
    samples: [],
    children: [],
    thumbnails: [],
    ingestion_class: "GCLogIngestor",
  }
}

function parseMptTimestamp(value: string | null | undefined): string | null {
  if (!value || !value.trim()) return null
  const str = value.trim()
  const match = /^(\d{1,2})\/(\d{1,2})\/(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})(?:\.(\d+))?$/.exec(str)
  if (!match) return null

  const month = pad2(parseInt(match[1], 10))
  const day = pad2(parseInt(match[2], 10))
  const year = match[3]
  const hour = pad2(parseInt(match[4], 10))
  const min = match[5]
  const sec = match[6]
  const frac = match[7]

  if (frac !== undefined) {
    const microseconds = (frac + "000000").slice(0, 6)
    return `${year}-${month}-${day}T${hour}:${min}:${sec}.${microseconds}`
  }
  return `${year}-${month}-${day}T${hour}:${min}:${sec}`
}

function leadingFloat(value: string | null | undefined): number | null {
  if (!value) return null
  const match = /[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?/.exec(value.trim())
  return match ? parseFloat(match[0]) : null
}

/**
 * Parses Bio-Logic EC-Lab ASCII .mpt export bytes (latin-1).
 * Returns null if file is not supported.
 */
export function parseBiologicMptBytes(
  bytes: Uint8Array,
  fileName: string,
  fileSize: number
): ParsedPacket | null {
  if (!fileName.toLowerCase().endsWith(".mpt")) return null

  const decoder = new TextDecoder("iso-8859-1")
  const text = decoder.decode(bytes)
  const lines = text.split(/\r?\n/)

  if (lines.length === 0 || lines[0]?.trim() !== "EC-Lab ASCII FILE") {
    return null
  }

  const headerMatch = /(\d+)/.exec(lines[1] ?? "")
  if (!headerMatch) {
    throw new Error(`${fileName} has no header line count on line 2`)
  }
  const headerLength = parseInt(headerMatch[1], 10)
  const headerLines = lines.slice(0, headerLength - 1)
  const columnLine = lines[headerLength - 1] ?? ""
  const dataLines = lines.slice(headerLength)

  const fields: Record<string, string | null> = {}
  const settings: Record<string, string | string[]> = {}
  const notes: string[] = []

  for (const rawLine of headerLines.slice(2)) {
    const stripped = rawLine.trim()
    if (!stripped) continue

    if (stripped.includes(" : ") || stripped.endsWith(" :")) {
      const colonIdx = stripped.indexOf(":")
      const key = stripped.slice(0, colonIdx).trim()
      const val = stripped.slice(colonIdx + 1).trim()
      fields[key] = val.length > 0 ? val : null
      continue
    }

    const parts = stripped.split(/\s{2,}/).map((p) => p.trim()).filter(Boolean)
    if (parts.length === 1) {
      notes.push(stripped)
    } else if (parts.length === 2) {
      settings[parts[0]] = parts[1]
    } else if (parts.length >= 3) {
      settings[parts[0]] = parts.slice(1)
    }
  }

  const columns = columnLine.split("\t").map((s) => s.trim()).filter(Boolean)
  const timeIdx = columns.indexOf("time/s")
  const times: number[] = []

  if (timeIdx !== -1) {
    for (const dl of dataLines) {
      if (!dl.trim()) continue
      const vals = dl.split("\t")
      if (timeIdx < vals.length) {
        const v = parseFloat(vals[timeIdx])
        if (!isNaN(v)) {
          times.push(v)
        }
      }
    }
  }

  const pointCount = times.length
  const durationS = times.length > 0 ? times[times.length - 1] : null
  const intervals: number[] = []
  for (let i = 0; i < times.length - 1; i++) {
    intervals.push(times[i + 1] - times[i])
  }

  let samplingIntervalS: number | null = null
  if (intervals.length > 0) {
    intervals.sort((a, b) => a - b)
    const mid = Math.floor(intervals.length / 2)
    if (intervals.length % 2 === 1) {
      samplingIntervalS = intervals[mid]
    } else {
      samplingIntervalS = (intervals[mid - 1] + intervals[mid]) / 2
    }
  }

  const technique = headerLines.slice(2).map((l) => l.trim()).find((l) => l.length > 0) ?? null
  const software = notes.find((n) => n.startsWith("EC-Lab for windows")) ?? null
  const acqStartedRaw = fields["Acquisition started on"] ?? null
  const acqStarted = parseMptTimestamp(acqStartedRaw)
  const techStarted = parseMptTimestamp(fields["Technique started on"])

  const scientificMetadata: Record<string, unknown> = {
    technique,
    device: fields["Device"] ?? null,
    channel: fields["Run on channel"] ?? null,
    software,
    acquisition_started_on: acqStarted,
    technique_started_on: techStarted,
    acquisition_started_on_raw: acqStartedRaw,
    saved_file: fields["File"] ?? null,
    saved_directory: fields["Directory"] ?? null,
    host: fields["Host"] ?? null,
    potential_control: fields["Potential control"] ?? null,
    electrode_connection: fields["Electrode connection"] ?? null,
    anode_material: fields["Anode material"] ?? null,
    cathode_material: fields["Cathode material"] ?? null,
    electrolyte: fields["Electrolyte"] ?? null,
    initial_state: fields["Initial state"] ?? null,
    comments: fields["Comments"] ?? null,
    electrode_surface_area_cm2: leadingFloat(fields["Electrode surface area"]),
    ewe_control_range: fields["Ewe ctrl range"] ?? null,
    technique_settings: settings,
    point_count: pointCount,
    duration_s: durationS,
    sampling_interval_s: samplingIntervalS,
    reference_electrode: null,
    reference_electrode_potential_V_vs_SHE: null,
    ir_compensation_ohm: null,
    cell_temperature_C: null,
  }

  const datasetFields: Record<string, unknown> = {
    dataset_name: stem(fileName),
    measurement: technique,
    data_type: "Electrochemistry Time Series",
    data_format: "mpt",
    timestamp: acqStarted,
    size: fileSize,
    public: false,
    session_name: null,
  }

  return {
    scientific_metadata: scientificMetadata,
    dataset_fields: datasetFields,
    keywords: [],
    samples: [],
    children: [],
    thumbnails: [],
    ingestion_class: "BiologicMptIngestor",
  }
}

function _isEmpty(value: unknown): boolean {
  if (value === null || value === undefined || value === "") return true
  if (Array.isArray(value) && value.length === 0) return true
  if (typeof value === "object" && Object.keys(value as Record<string, unknown>).length === 0) return true
  return false
}

function _isNumber(value: unknown): boolean {
  return typeof value === "number" && !isNaN(value)
}

function _sumFields(
  base: Record<string, unknown>,
  incoming: Record<string, unknown>,
  keys: Iterable<string>
): void {
  for (const key of keys) {
    const val = incoming[key]
    if (!_isNumber(val)) continue
    const cur = base[key]
    base[key] = (_isNumber(cur) ? (cur as number) : 0) + (val as number)
  }
}

function _fillGaps(
  base: Record<string, unknown>,
  incoming: Record<string, unknown>,
  collisions: Collision[],
  path = "",
  skip: ReadonlySet<string> = new Set()
): Record<string, unknown> {
  for (const [key, value] of Object.entries(incoming)) {
    const here = path ? `${path}.${key}` : key
    if (skip.has(key)) continue
    if (!(key in base) || _isEmpty(base[key])) {
      base[key] = value
    } else if (
      typeof base[key] === "object" &&
      base[key] !== null &&
      !Array.isArray(base[key]) &&
      typeof value === "object" &&
      value !== null &&
      !Array.isArray(value)
    ) {
      _fillGaps(base[key] as Record<string, unknown>, value as Record<string, unknown>, collisions, here, skip)
    } else if (!_isEmpty(value) && JSON.stringify(base[key]) !== JSON.stringify(value)) {
      collisions.push({ field: here, kept: base[key], discarded: value })
    }
  }
  return base
}

/**
 * Folds a parsed packet into a running packet.
 */
export function foldIntoPacket(
  packet: ParsedPacket,
  parsed: ParsedPacket,
  collisions: Collision[],
  source = ""
): ParsedPacket {
  const found: Collision[] = []
  _fillGaps(packet.scientific_metadata, parsed.scientific_metadata, found)
  _fillGaps(packet.dataset_fields, parsed.dataset_fields, found, "", new Set(["size"]))
  _sumFields(packet.dataset_fields, parsed.dataset_fields, ["size"])

  for (const c of found) {
    c.file = source
  }
  collisions.push(...found)

  packet.keywords = Array.from(new Set([...packet.keywords, ...parsed.keywords]))

  const sampleSeen = new Set<string>()
  const mergedSamples: typeof packet.samples = []
  for (const s of [...packet.samples, ...parsed.samples]) {
    const uid = s.unique_id
    if (uid == null) {
      mergedSamples.push(s)
    } else if (!sampleSeen.has(uid)) {
      sampleSeen.add(uid)
      mergedSamples.push(s)
    }
  }
  packet.samples = mergedSamples

  const childSeen = new Set<string>()
  const mergedChildren: typeof packet.children = []
  for (const c of [...packet.children, ...parsed.children]) {
    const uid = c.dataset?.unique_id
    if (uid == null) {
      mergedChildren.push(c)
    } else if (!childSeen.has(uid)) {
      childSeen.add(uid)
      mergedChildren.push(c)
    }
  }
  packet.children = mergedChildren
  packet.thumbnails = [...packet.thumbnails, ...parsed.thumbnails]
  return packet
}

export interface PreviewableFile {
  name: string
  size: number
  text?: () => Promise<string>
  arrayBuffer?: () => Promise<ArrayBuffer>
}

/**
 * Parses a batch of files into one combined preview packet.
 */
export async function parseFilesForPreview(
  files: PreviewableFile[],
  requestedIngestor?: string
): Promise<{
  packet: ParsedPacket
  collisions: Collision[]
  per_file: Array<{ file: string; ingestion_class: string }>
  skipped: string[]
}> {
  let packet: ParsedPacket | null = null
  const collisions: Collision[] = []
  const per_file: Array<{ file: string; ingestion_class: string }> = []
  const skipped: string[] = []

  for (const file of files) {
    const name = basename(file.name)
    let parsed: ParsedPacket | null = null

    const tryMpt = async () => {
      if (file.arrayBuffer) {
        const buf = await file.arrayBuffer()
        return parseBiologicMptBytes(new Uint8Array(buf), name, file.size)
      }
      return null
    }

    const tryGc = async () => {
      if (file.text) {
        const str = await file.text()
        return parseGcLogText(str, name, file.size)
      }
      return null
    }

    if (requestedIngestor === "BiologicMptIngestor") {
      parsed = await tryMpt()
    } else if (requestedIngestor === "GCLogIngestor") {
      parsed = await tryGc()
    }

    if (!parsed) {
      if (name.toLowerCase().endsWith(".mpt")) {
        parsed = await tryMpt()
      } else if (name.toLowerCase().endsWith(".log")) {
        parsed = await tryGc()
      }
    }

    if (!parsed) {
      skipped.push(name)
      continue
    }

    per_file.push({ file: name, ingestion_class: parsed.ingestion_class })
    if (packet === null) {
      packet = parsed
    } else {
      foldIntoPacket(packet, parsed, collisions, name)
    }
  }

  if (packet === null) {
    packet = {
      scientific_metadata: {},
      dataset_fields: {
        dataset_name: "",
        measurement: null,
        data_type: null,
        session_name: null,
      },
      keywords: [],
      samples: [],
      children: [],
      thumbnails: [],
      ingestion_class: "",
    }
  }

  return { packet, collisions, per_file, skipped }
}

export function isMissing(value: unknown): boolean {
  if (value === null || value === undefined) return true
  if (typeof value === "number" && isNaN(value)) return true
  if (typeof value === "string") {
    const stripped = value.trim().toLowerCase()
    return stripped === "" || MISSING_STRINGS.has(stripped)
  }
  return false
}

function fieldType(value: unknown): [string, string | null, boolean] {
  if (typeof value === "boolean") return ["boolean", null, true]
  if (Number.isInteger(value)) return ["integer", null, true]
  if (typeof value === "number" && !isNaN(value)) return ["number", null, true]
  if (value === null || typeof value === "string") return ["string", null, true]
  if (Array.isArray(value)) {
    if (value.some((v) => typeof v === "object" && v !== null)) {
      return ["json", null, false]
    }
    const first = value.find((v) => v != null)
    const itemsType = first == null ? "string" : fieldType(first)[0]
    return ["array", itemsType, true]
  }
  return ["json", null, false]
}

/**
 * Turns parsed scientific metadata into form fields, one per key, in parse order.
 */
export function buildFormDescriptor(scientificMetadata: Record<string, unknown>): FormFieldDescriptor[] {
  const fields: FormFieldDescriptor[] = []

  function walk(node: Record<string, unknown>, path: string[]): void {
    for (const [name, value] of Object.entries(node)) {
      const here = [...path, name]
      if (here.length === 1 && HIDDEN_FIELDS.has(name)) {
        continue
      }
      if (
        typeof value === "object" &&
        value !== null &&
        !Array.isArray(value) &&
        Object.keys(value as Record<string, unknown>).length > 0
      ) {
        walk(value as Record<string, unknown>, here)
        continue
      }
      const [ftype, itemsType, editable] = fieldType(value)
      fields.push({
        path: here,
        key: here.join("."),
        label: name,
        group_labels: path,
        description: "",
        type: ftype,
        items_type: itemsType,
        enum: null,
        value,
        editable: editable && !LOCKED_FIELDS.has(here[0]),
        missing: isMissing(value),
      })
    }
  }

  walk(scientificMetadata || {}, [])
  return fields
}

/**
 * Builds editable dataset column descriptors.
 */
export function buildDatasetFormDescriptor(datasetFields: Record<string, unknown>): FormFieldDescriptor[] {
  const values = datasetFields || {}
  return DATASET_FORM_FIELDS.map((spec) => ({
    path: [spec.key],
    key: spec.key,
    label: spec.label,
    group_labels: [],
    description: spec.description,
    type: "string",
    items_type: null,
    enum: null,
    value: values[spec.key] ?? null,
    editable: true,
    missing: isMissing(values[spec.key]),
  }))
}

/**
 * Dataset columns the form does not offer, shown read-only for context.
 */
export function otherDatasetFields(datasetFields: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(datasetFields || {})) {
    if (!DATASET_FORM_KEYS.has(k)) {
      out[k] = v
    }
  }
  return out
}

/**
 * Write operator corrections onto the packet's dataset columns.
 */
export function applyDatasetFieldEdits(packet: ParsedPacket, edits: Record<string, unknown>): ParsedPacket {
  for (const [key, value] of Object.entries(edits || {})) {
    if (DATASET_FORM_KEYS.has(key)) {
      packet.dataset_fields[key] = value
    }
  }
  return packet
}

/**
 * Write edited values back to their dotted paths in scientific_metadata.
 */
export function applyMetadataEdits(packet: ParsedPacket, edits: Record<string, unknown>): ParsedPacket {
  for (const [key, value] of Object.entries(edits || {})) {
    const parts = String(key).split(".").filter(Boolean)
    if (parts.length === 0 || LOCKED_FIELDS.has(parts[0])) {
      continue
    }
    let cur = packet.scientific_metadata
    for (let i = 0; i < parts.length - 1; i++) {
      const part = parts[i]
      if (typeof cur[part] !== "object" || cur[part] === null || Array.isArray(cur[part])) {
        cur[part] = {}
      }
      cur = cur[part] as Record<string, unknown>
    }
    cur[parts[parts.length - 1]] = value
  }
  return packet
}
