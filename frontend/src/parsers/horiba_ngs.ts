// Reads the acquisition settings of a Horiba LabSpec 6 .ngs single spectrum for the B30 Raman
// form. Port of parse_ngs/read_table in crucible-ingestion's horiba_ngs_ingestor.py (the format
// is undocumented and reverse-engineered there). Fails soft: anything it can't read is left
// out, and the HoribaNgsIngestor fills it in after upload.

export type NgsFormFields = {
  laser_wavelength_nm?: number
  exposure_time_s?: number
  accumulation?: string
  grating?: string
  objective?: string
  raman_shift_range?: [number, number]
}

const MAGIC = "NGSNextGen"

class FormatError extends Error {}

class Reader {
  pos: number
  constructor(readonly view: DataView, pos = 0) {
    this.pos = pos
  }
  private need(size: number) {
    if (this.pos + size > this.view.byteLength) throw new FormatError("unexpected end of file")
  }
  u8() { this.need(1); return this.view.getUint8(this.pos++) }
  u16() { this.need(2); const v = this.view.getUint16(this.pos, true); this.pos += 2; return v }
  u32() { this.need(4); const v = this.view.getUint32(this.pos, true); this.pos += 4; return v }
  i32() { this.need(4); const v = this.view.getInt32(this.pos, true); this.pos += 4; return v }
  f32() { this.need(4); const v = this.view.getFloat32(this.pos, true); this.pos += 4; return v }
  str() {
    const n = this.u8()
    this.need(n)
    let s = ""
    for (let i = 0; i < n; i++) s += String.fromCharCode(this.view.getUint8(this.pos + i)) // latin-1
    this.pos += n
    return s
  }
  strs(count: number) { return Array.from({ length: count }, () => this.str()) }
  expect(value: string) { if (this.str() !== value) throw new FormatError(`expected ${value}`) }
  skipToCount(count: number, limit = 16) {
    // tables pad a variable number of bytes before each column's uint16 value count
    for (let i = 0; i < limit; i++) {
      this.need(2)
      if (this.view.getUint16(this.pos, true) === count) { this.pos += 2; return }
      this.pos += 1
    }
    throw new FormatError("no value count")
  }
}

function indexOf(bytes: Uint8Array, marker: Uint8Array): number {
  outer: for (let i = 0; i + marker.length <= bytes.length; i++) {
    for (let j = 0; j < marker.length; j++) if (bytes[i + j] !== marker[j]) continue outer
    return i
  }
  return -1
}

/** {row: value} of a named LabSpec table ("Param", "Acq"), or null if absent/unreadable. */
function readTable(bytes: Uint8Array, view: DataView, name: string): Record<string, string> | null {
  const marker = new Uint8Array([5, ..."Table"].map((c) => (typeof c === "number" ? c : c.charCodeAt(0))))
  const full = new Uint8Array([...marker, name.length, ...Array.from(name, (c) => c.charCodeAt(0))])
  const start = indexOf(bytes, full)
  if (start < 0) return null
  try {
    const r = new Reader(view, start + full.length)
    r.str()
    r.u32()
    const rows = r.strs(r.u16())
    const columns = r.strs(r.u16())
    if (columns[0] !== "Value") return null
    r.skipToCount(rows.length)
    const values = r.strs(rows.length)
    return Object.fromEntries(rows.map((row, i) => [row, values[i]]))
  } catch {
    return null
  }
}

/** Raman shift range from the spectrum header and axis trailer, or null. */
function readShiftRange(view: DataView): [number, number] | null {
  try {
    const r = new Reader(view, MAGIC.length + 8)
    r.expect("DataMatrix")
    r.expect("Spectrum")
    r.str() // title
    r.u32(); r.u32(); r.u32()
    const marker = r.i32()
    const n = r.u32()
    const dims = r.u16()
    const nAgain = r.u32()
    r.u16()
    if (marker !== -1 || dims !== 1 || n !== nAgain || n < 2) return null
    r.pos += 4 * n
    if (r.u16() !== 2) return null
    r.strs(2) // axis labels
    if (r.u16() !== 2) return null
    const [xUnit] = r.strs(2)
    r.pos += 16
    const start = r.f32()
    const end = r.f32()
    if (xUnit !== "1/cm" || !Number.isFinite(start) || !Number.isFinite(end) || start === end) return null
    return [Math.round(start * 1000) / 1000, Math.round(end * 1000) / 1000]
  } catch {
    return null
  }
}

const number = (value: string | undefined) => {
  if (value === undefined || value.trim() === "") return undefined
  const n = Number(value)
  return Number.isFinite(n) ? n : undefined
}
const text = (value: string | undefined) => (value && value.trim() ? value.trim() : undefined)

export async function readNgsFields(file: Blob): Promise<NgsFormFields | null> {
  const buffer = await file.arrayBuffer() // single spectra are ~35 KB
  const bytes = new Uint8Array(buffer)
  const view = new DataView(buffer)
  if (String.fromCharCode(...bytes.slice(0, MAGIC.length)) !== MAGIC) return null

  const acq = readTable(bytes, view, "Acq") ?? {}
  const fields: NgsFormFields = {
    laser_wavelength_nm: number(acq["Laser"]),
    exposure_time_s: number(acq["Exposition"]),
    accumulation: text(acq["Accumulation"]),
    grating: text(acq["Grating"]),
    objective: text(acq["Objective"]),
  }
  const range = readShiftRange(view)
  if (range) fields.raman_shift_range = range
  for (const key of Object.keys(fields) as (keyof NgsFormFields)[]) {
    if (fields[key] === undefined) delete fields[key]
  }
  return Object.keys(fields).length ? fields : null
}
