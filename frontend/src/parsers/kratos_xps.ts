// Reads acquisition parameters from a Kratos Vision .kal file for the B30 XPS form.
// Matches crucible-ingestion's KratosXpsIngestor logic. Fails soft: returns null on
// invalid or binary files, leaving the server-side ingestor to handle/fill parameters.

export type KalFormFields = {
  anode_material?: string
  photon_energy_eV?: number
  anode_voltage_V?: number
  emission_current_A?: number
  stage_position_name?: string
  technique?: string
  dataset_comment?: string
  total_spectra?: number
  regions?: string[]
}

const XRAY_PHOTON_ENERGY_EV: Record<string, number> = {
  F_REFER_TO_XRAY_MONO_AL: 1486.69,
  F_NICPU_XRAY_ANODE_STD_MONO: 1486.69,
  F_REFER_TO_XRAY_AL: 1486.6,
  F_REFER_TO_XRAY_MG: 1253.6,
  F_REFER_TO_XRAY_MONO_AG: 2984.3,
  F_NICPU_XRAY_ANODE_AG_MONO: 2984.3,
  F_REFER_TO_XRAY_MONO_CR: 5414.8,
  F_NICPU_XRAY_ANODE_CR_MONO: 5414.8,
}

function _tryNumber(text: string): any {
  const trimmed = text.trim()
  if (!trimmed) return trimmed
  const num = Number(trimmed)
  return isFinite(num) ? num : trimmed
}

function _parseValue(text: string): any {
  const trimmed = text.trim()
  if (!trimmed) return undefined
  const match = trimmed.match(/^(-?\d+\.?\d*(?:[eE][-+]?\d+)?)\s+([A-Za-z/%_.]+)$/)
  if (match) {
    return { value: _tryNumber(match[1]), unit: match[2] }
  }
  return _tryNumber(trimmed)
}

function _parseInlineArray(inner: string): any[] {
  if (!inner.trim()) return []
  return inner.split(",").map((item) => _tryNumber(item))
}

function _unwrap(value: any): any {
  if (value && typeof value === "object" && "value" in value && "unit" in value) {
    return value.value
  }
  return value
}

function _asStr(value: any): string | undefined {
  if (value == null) return undefined
  if (typeof value === "object") {
    if ("value" in value && "unit" in value) {
      const s = `${value.value} ${value.unit}`.trim()
      return s || undefined
    }
    return undefined
  }
  const s = String(value).trim()
  return s || undefined
}

function _asFloat(value: any): number | undefined {
  const raw = _unwrap(value)
  if (raw == null || typeof raw === "boolean" || typeof raw === "object") return undefined
  const num = Number(raw)
  return isFinite(num) ? num : undefined
}

function _formatAnodeMaterial(raw: any): string | undefined {
  if (!raw) return undefined
  const rawStr = String(raw).trim()
  const mapping: Record<string, string> = {
    F_NICPU_XRAY_ANODE_STD_MONO: "Al Mono",
    F_NICPU_XRAY_ANODE_STD_DUAL: "Al/Mg Dual",
    F_NICPU_XRAY_ANODE_AG_MONO: "Ag Mono",
    F_NICPU_XRAY_ANODE_CR_MONO: "Cr Mono",
  }
  return mapping[rawStr] || rawStr
}

function resolvePhotonEnergy(...candidates: any[]): number | undefined {
  for (const cand of candidates) {
    if (cand == null) continue
    const candStr = String(cand).trim()
    if (candStr in XRAY_PHOTON_ENERGY_EV) {
      return XRAY_PHOTON_ENERGY_EV[candStr]
    }
  }
  return undefined
}

interface RawKratosObject {
  name: string
  index?: number
  dataset_filename?: string
  dataset_comment?: string
  fields: Record<string, any>
}

function parseKalText(text: string): RawKratosObject[] {
  if (text.includes("\x00")) {
    throw new Error("binary content in .kal text")
  }

  const objects: RawKratosObject[] = []
  let datasetFilename: string | undefined
  let datasetComment: string | undefined
  let currentFields: Record<string, any> | undefined
  let stack: any[] = []

  const lines = text.split(/\r?\n/)
  const n = lines.length
  let i = 0

  while (i < n) {
    const line = lines[i]
    const stripped = line.trim()
    i++
    if (!stripped) continue

    if (stripped === "{") {
      if (stack.length === 0) throw new Error("unexpected opening brace")
      const top = stack[stack.length - 1]
      if (!Array.isArray(top)) throw new Error("unexpected standalone opening brace")
      const newObj: Record<string, any> = {}
      top.push(newObj)
      stack.push(newObj)
      continue
    }

    if (stripped === "}") {
      if (stack.length <= 1) throw new Error("unmatched closing brace")
      stack.pop()
      continue
    }

    const eqIdx = line.indexOf("=")
    if (eqIdx === -1) continue

    const left = line.slice(0, eqIdx).trim()
    const valueText = line.slice(eqIdx + 1).trim()

    const idMatch = left.match(/^(\d+)\s+(.*)$/)
    const key = idMatch ? idMatch[2].trim() : left

    if (key === "Dataset filename") {
      datasetFilename = valueText
      continue
    }
    if (key === "Dataset Comment") {
      datasetComment = valueText
      continue
    }
    if (key === "Object name") {
      if (objects.length > 0 && stack.length !== 1) {
        throw new Error("unclosed brace block")
      }
      const slashIdx = valueText.lastIndexOf("/")
      let name = valueText
      let objIndex: number | undefined
      if (slashIdx !== -1) {
        const head = valueText.slice(0, slashIdx)
        const tail = valueText.slice(slashIdx + 1)
        if (/^\d+$/.test(tail)) {
          name = head
          objIndex = parseInt(tail, 10)
        }
      }
      currentFields = {}
      objects.push({
        name,
        index: objIndex,
        dataset_filename: datasetFilename,
        dataset_comment: datasetComment,
        fields: currentFields,
      })
      stack = [currentFields]
      continue
    }

    if (stack.length === 0) {
      throw new Error(`field ${key} outside object`)
    }

    const target = stack[stack.length - 1]
    const arrayMatch = valueText.match(/^\{(.*)\}$/)
    let parsed: any
    if (arrayMatch) {
      parsed = _parseInlineArray(arrayMatch[1])
    } else if (valueText === "{") {
      let j = i
      while (j < n && !lines[j].trim()) j++
      const isList = j < n && lines[j].trim() === "{"
      parsed = isList ? [] : {}
      stack.push(parsed)
    } else {
      parsed = _parseValue(valueText)
    }

    if (Array.isArray(target)) {
      target.push(parsed)
    } else {
      target[key] = parsed
    }
  }

  if (objects.length > 0 && stack.length !== 1) {
    throw new Error("unclosed brace block")
  }
  if (objects.length === 0) {
    throw new Error("no Kratos objects found")
  }

  return objects
}

export async function readKalFields(file: Blob): Promise<KalFormFields | null> {
  try {
    const buffer = await file.arrayBuffer()
    const bytes = new Uint8Array(buffer)
    if (bytes.includes(0)) {
      return null
    }

    const text = new TextDecoder("utf-8").decode(buffer)
    const objects = parseKalText(text)

    const spectraObjs: RawKratosObject[] = []
    const events: RawKratosObject[] = []

    for (const obj of objects) {
      const fields = obj.fields || {}
      if ("Ordinate values" in fields) {
        const rawY = fields["Ordinate values"]
        if (!Array.isArray(rawY) || rawY.length < 2) {
          return null
        }
        for (const yVal of rawY) {
          const num = Number(yVal)
          if (!isFinite(num)) return null
        }
        const stepRaw = _unwrap(fields["Spectrum scan step size"] ?? 1.0)
        const step = Number(stepRaw)
        if (!isFinite(step) || step === 0) {
          return null
        }
        spectraObjs.push(obj)
      } else {
        events.push(obj)
      }
    }

    if (spectraObjs.length === 0) {
      return null
    }

    let fallbackPhotonEnergy: number | undefined
    for (const ev of events) {
      const f = ev.fields || {}
      const scanObj = f["Scan Sweep OBJECT"] && typeof f["Scan Sweep OBJECT"] === "object" ? f["Scan Sweep OBJECT"] : {}
      const cand = resolvePhotonEnergy(
        f["Xray Reference Energy"],
        f["NICPU X.Gun Energy Reference"],
        f["NICPU X-ray Gun Active Anode Material"],
        scanObj["Xray Reference Energy"],
        scanObj["NICPU X.Gun Energy Reference"],
        scanObj["NICPU X-ray Gun Active Anode Material"],
      )
      if (cand !== undefined) {
        fallbackPhotonEnergy = cand
        break
      }
    }

    let anodeRaw: string | undefined
    let voltage: number | undefined
    let current: number | undefined
    let photonEnergy: number | undefined
    const techniquesSet = new Set<string>()
    const regions: string[] = []

    for (const s of spectraObjs) {
      const f = s.fields || {}
      if (s.name && !regions.includes(s.name)) {
        regions.push(s.name)
      }
      let tech = _asStr(f["Technique"])
      if (tech) {
        if (tech.startsWith("F_")) tech = tech.slice(2)
        techniquesSet.add(tech)
      }
      if (anodeRaw === undefined) {
        const cand = _asStr(f["NICPU X-ray Gun Active Anode Material"])
        if (cand !== undefined) anodeRaw = cand
      }
      if (voltage === undefined) {
        const cand = _asFloat(f["NICPU X-ray Gun Anode HT Voltage"])
        if (cand !== undefined) voltage = cand
      }
      if (current === undefined) {
        const cand = _asFloat(f["NICPU X-ray Gun Emission Current"])
        if (cand !== undefined) current = cand
      }
      if (photonEnergy === undefined) {
        const cand = resolvePhotonEnergy(
          f["Xray Reference Energy"],
          f["NICPU X.Gun Energy Reference"],
          f["NICPU X-ray Gun Active Anode Material"],
          fallbackPhotonEnergy,
        )
        if (cand !== undefined) photonEnergy = cand
      }
    }

    if (anodeRaw === undefined || voltage === undefined || current === undefined || photonEnergy === undefined) {
      for (const ev of events) {
        const f = ev.fields || {}
        const scanObj = f["Scan Sweep OBJECT"] && typeof f["Scan Sweep OBJECT"] === "object" ? f["Scan Sweep OBJECT"] : {}
        if (anodeRaw === undefined) {
          let cand = _asStr(f["NICPU X-ray Gun Active Anode Material"])
          if (cand === undefined) cand = _asStr(scanObj["NICPU X-ray Gun Active Anode Material"])
          if (cand !== undefined) anodeRaw = cand
        }
        if (voltage === undefined) {
          let cand = _asFloat(f["NICPU X-ray Gun Anode HT Voltage"])
          if (cand === undefined) cand = _asFloat(scanObj["NICPU X-ray Gun Anode HT Voltage"])
          if (cand !== undefined) voltage = cand
        }
        if (current === undefined) {
          let cand = _asFloat(f["NICPU X-ray Gun Emission Current"])
          if (cand === undefined) cand = _asFloat(scanObj["NICPU X-ray Gun Emission Current"])
          if (cand !== undefined) current = cand
        }
        if (photonEnergy === undefined) {
          const cand = resolvePhotonEnergy(
            f["Xray Reference Energy"],
            f["NICPU X.Gun Energy Reference"],
            f["NICPU X-ray Gun Active Anode Material"],
            scanObj["Xray Reference Energy"],
            scanObj["NICPU X.Gun Energy Reference"],
            scanObj["NICPU X-ray Gun Active Anode Material"],
          )
          if (cand !== undefined) photonEnergy = cand
        }
      }
    }

    let stagePositionName: string | undefined
    for (const ev of events) {
      const f = ev.fields || {}
      const name = _asStr(f["Stage Position Name"])
      if (name !== undefined) {
        stagePositionName = name
        break
      }
    }

    const datasetComment = objects[0]?.dataset_comment ? objects[0].dataset_comment.trim() : undefined
    const technique = Array.from(techniquesSet).sort().join(", ") || undefined

    const res: KalFormFields = {
      total_spectra: spectraObjs.length,
      regions,
    }
    if (anodeRaw !== undefined) {
      const formatted = _formatAnodeMaterial(anodeRaw)
      if (formatted) res.anode_material = formatted
    }
    if (photonEnergy !== undefined) res.photon_energy_eV = photonEnergy
    if (voltage !== undefined) res.anode_voltage_V = voltage
    if (current !== undefined) res.emission_current_A = current
    if (stagePositionName !== undefined) res.stage_position_name = stagePositionName
    if (technique !== undefined) res.technique = technique
    if (datasetComment !== undefined) res.dataset_comment = datasetComment

    return res
  } catch {
    return null
  }
}
