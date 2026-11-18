// Parser for inorganic XRD text files.
// Port of parse_xrd_file in crucible-upload-uis/instruments/inorganic_xrd/parse.py.

export interface XrdSampleAssignment {
  position: string
  name: string
  uuid: string
  excluded: boolean
}

/**
 * Parses inorganic XRD text header line.
 * Combined format: line 1 is tab-separated sample names.
 * Single-sample format: line 1 is a single name or empty.
 */
export function parseXrdText(text: string): XrdSampleAssignment[] {
  const line1 = text.split(/\r?\n/)[0] ?? ""
  const parts = line1.split("\t").map((p) => p.trim())
  const names = parts.filter(Boolean)

  if (names.length <= 1) {
    const name = names[0] ?? ""
    return [{ position: "S01", name, uuid: "", excluded: false }]
  }

  return names.map((name, i) => ({
    position: `S${String(i + 1).padStart(2, "0")}`,
    name,
    uuid: "",
    excluded: false,
  }))
}

/**
 * Reads an inorganic XRD Blob/File and extracts sample assignments from its first line.
 */
export async function readXrdFile(file: Blob): Promise<XrdSampleAssignment[]> {
  const text = await file.text()
  return parseXrdText(text)
}
