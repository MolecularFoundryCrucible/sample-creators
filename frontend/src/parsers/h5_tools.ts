// HDF5 client-side parsing utilities using jsfive.
// Ports ScopeFoundry embedded ID/tray extraction and Nirvana multi-position parsing.
import { File as H5File, Group as H5Group } from "jsfive"

export interface NirvanaPosition {
  position: string
  raw_key: string
  name: string
  uuid: string
  tray_uuid: string
  tray_name: string
  excluded: boolean
}

export interface H5EmbeddedInfo {
  dsid: string | null
  projectId: string | null
  trays: Array<{ mfid: string; name: string }>
}

/**
 * Cleanly decodes an HDF5 attribute value to a string, stripping null-byte padding.
 */
export function decodeH5Attr(val: unknown): string {
  if (val === null || val === undefined) return ""

  if (typeof val === "string") {
    return val.replace(/\0+$/, "")
  }

  if (typeof val === "number" || typeof val === "boolean") {
    return String(val)
  }

  if (val instanceof Uint8Array) {
    const decoded = new TextDecoder("utf-8").decode(val)
    return decoded.replace(/\0+$/, "")
  }

  if (Array.isArray(val)) {
    if (val.length === 0) return ""
    if (val.length === 1) return decodeH5Attr(val[0])
    return val.map((v) => decodeH5Attr(v)).filter(Boolean).join(" ")
  }

  if (ArrayBuffer.isView(val)) {
    const uint8 = new Uint8Array(val.buffer, val.byteOffset, val.byteLength)
    const decoded = new TextDecoder("utf-8").decode(uint8)
    return decoded.replace(/\0+$/, "")
  }

  return String(val).replace(/\0+$/, "")
}

/**
 * Returns NirvanaMultiPosSpecRunIngestor or NirvanaMultiPosLineScanIngestor based on filename.
 */
export function detectNirvanaIngestor(filename: string): string {
  return /pollux_multipos_spec_run.*\.h5$/i.test(filename)
    ? "NirvanaMultiPosSpecRunIngestor"
    : "NirvanaMultiPosLineScanIngestor"
}

function safeGetGroup(parent: H5Group, path: string): H5Group | null {
  try {
    const parts = path.split("/").filter(Boolean)
    let cur: H5Group = parent
    for (const part of parts) {
      if (!cur.keys.includes(part)) {
        return null
      }
      const child = cur.get(part)
      if (!child || typeof (child as H5Group).get !== "function") {
        return null
      }
      cur = child as H5Group
    }
    return cur
  } catch {
    return null
  }
}

/**
 * Extracts sample positions, names, and UUIDs from a Nirvana ScopeFoundry H5 file.
 */
export async function readNirvanaH5Positions(
  fileOrBuffer: Blob | ArrayBuffer,
  filename?: string
): Promise<NirvanaPosition[]> {
  const buffer = fileOrBuffer instanceof Blob ? await fileOrBuffer.arrayBuffer() : fileOrBuffer
  const f = new H5File(buffer, filename)

  if (!f.keys.includes("measurement")) {
    throw new Error("No /measurement group found in this file")
  }
  const measGrp = f.get("measurement") as H5Group
  if (!measGrp || measGrp.keys.length === 0) {
    throw new Error("No /measurement group found in this file")
  }

  const measName = measGrp.keys[0]
  const meas = measGrp.get(measName) as H5Group
  if (!meas) {
    throw new Error(`Measurement '${measName}' not found under /measurement`)
  }

  let positions: H5Group | null = null
  if (measName.endsWith("_spec_run")) {
    for (const k of meas.keys) {
      if (k === "settings") continue
      const child = meas.get(k) as H5Group | null
      if (child && child.keys && child.keys.includes("positions")) {
        positions = child.get("positions") as H5Group
        break
      }
    }
    if (!positions) {
      throw new Error(`No positions group found in spec_run measurement '${measName}'`)
    }
  } else {
    if (!meas.keys.includes("positions")) {
      throw new Error(`No positions group found under /measurement/${measName}`)
    }
    positions = meas.get("positions") as H5Group
  }

  const sortedPosKeys = positions.keys.slice().sort()
  const samples: NirvanaPosition[] = []

  for (let i = 0; i < sortedPosKeys.length; i++) {
    const posName = sortedPosKeys[i]
    const posObj = positions.get(posName) as H5Group | null
    const attrs = posObj?.attrs ?? {}

    let sampleName = posName
    if (attrs["sample_name"] != null) {
      const decoded = decodeH5Attr(attrs["sample_name"])
      if (decoded.length > 0) {
        sampleName = decoded
      }
    }

    let sampleUuid = ""
    if (attrs["sample_uuid"] != null) {
      sampleUuid = decodeH5Attr(attrs["sample_uuid"])
    }

    samples.push({
      position: `S${String(i + 1).padStart(2, "0")}`,
      raw_key: posName,
      name: sampleName,
      uuid: sampleUuid,
      tray_uuid: "",
      tray_name: "",
      excluded: false,
    })
  }

  return samples
}

/**
 * Reads embedded dsid, projectId, and trays from a ScopeFoundry/SpinBot H5 file.
 */
export async function readH5EmbeddedInfo(
  fileOrBuffer: Blob | ArrayBuffer,
  filename?: string
): Promise<H5EmbeddedInfo> {
  try {
    const buffer = fileOrBuffer instanceof Blob ? await fileOrBuffer.arrayBuffer() : fileOrBuffer
    const f = new H5File(buffer, filename)

    // 1. dsid: measurement/spin_run/settings -> run_id, then root -> unique_id
    let dsid: string | null = null
    const spinSettings = safeGetGroup(f, "measurement/spin_run/settings")
    if (spinSettings?.attrs && spinSettings.attrs["run_id"] != null) {
      const val = decodeH5Attr(spinSettings.attrs["run_id"])
      if (val.length > 0) {
        dsid = val
      }
    }
    if (!dsid && f.attrs && f.attrs["unique_id"] != null) {
      const val = decodeH5Attr(f.attrs["unique_id"])
      if (val.length > 0) {
        dsid = val
      }
    }

    // 2. projectId: hardware/<comp>/settings -> proposal or project attr, take first token
    let projectId: string | null = null
    const hw = safeGetGroup(f, "hardware")
    if (hw) {
      for (const comp of hw.keys) {
        const settings = safeGetGroup(hw, `${comp}/settings`)
        if (settings?.attrs) {
          for (const attrName of ["proposal", "project"]) {
            if (settings.attrs[attrName] != null) {
              const val = decodeH5Attr(settings.attrs[attrName])
              if (val.length > 0) {
                projectId = val.split(" ")[0] || null
                break
              }
            }
          }
          if (projectId) break
        }
      }
    }

    // 3. trays: measurement/spin_run/samples -> batch_id & batch_name deduped in order
    const trays: Array<{ mfid: string; name: string }> = []
    const seen = new Set<string>()
    const samplesGrp = safeGetGroup(f, "measurement/spin_run/samples")
    if (samplesGrp) {
      for (const key of samplesGrp.keys) {
        const sample = samplesGrp.get(key) as H5Group | null
        if (!sample?.attrs) continue
        const batchIdRaw = sample.attrs["batch_id"]
        if (batchIdRaw == null) continue
        const batchId = decodeH5Attr(batchIdRaw)
        if (!batchId || seen.has(batchId)) continue
        seen.add(batchId)
        const batchName = sample.attrs["batch_name"] != null ? decodeH5Attr(sample.attrs["batch_name"]) : ""
        trays.push({ mfid: batchId, name: batchName })
      }
    }

    return { dsid, projectId, trays }
  } catch {
    return { dsid: null, projectId: null, trays: [] }
  }
}
