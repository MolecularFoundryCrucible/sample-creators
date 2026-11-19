// Pure folder and sidecar planner for TEM session uploads (legacy crucible-upload-uis parity).

export const TEM_ACCEPTABLE_EXTENSIONS = [
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
] as const

export const MAX_FILE_BYTES = 500 * 1024 ** 3 // 500 GiB

export type SessionFileInput = {
  file: File
  relativePath: string
}

export type PlanTemSessionOptions = {
  acceptableExtensions?: readonly string[]
  maxFileBytes?: number
}

export type TemSessionItem = {
  clientId: string
  datasetName: string
  relativePath: string
  directoryPath: string
  dataFormat: string
  primaryFile: File
  companionFiles: File[]
  totalBytes: number
  warning?: string
}

export type TemSessionPlan = {
  folderName: string
  items: TemSessionItem[]
  ignoredCount: number
  companionCount: number
  emptyFiles: string[]
  oversizedFiles: string[]
  totalUploadBytes: number
}

type NormalizedEntry = {
  file: File
  relativePath: string
  directoryPath: string
  fileName: string
  stem: string
  ext: string
}

const OS_JUNK_EXACT = new Set([".ds_store", "thumbs.db", "desktop.ini"])

function isOsJunkFile(fileName: string): boolean {
  const lower = fileName.toLowerCase()
  return (
    OS_JUNK_EXACT.has(lower) ||
    lower.endsWith(".zone.identifier") ||
    lower.endsWith(":zone.identifier")
  )
}

function normalizeRelativePath(rawPath: string): string {
  const slashesNormalized = rawPath.replace(/\\/g, "/").replace(/\/+/g, "/")
  const trimmedLeading = slashesNormalized.replace(/^(?:\.\/|\/)+/, "")
  return trimmedLeading.replace(/\/+$/, "")
}

function splitFileName(fileName: string): { stem: string; ext: string } {
  const dotIdx = fileName.lastIndexOf(".")
  if (dotIdx <= 0) {
    return { stem: fileName, ext: "" }
  }
  return {
    stem: fileName.slice(0, dotIdx),
    ext: fileName.slice(dotIdx).toLowerCase(),
  }
}

function normalizeExtensions(extensions: readonly string[]): Set<string> {
  const out = new Set<string>()
  for (const raw of extensions) {
    const trimmed = raw.trim().toLowerCase()
    if (!trimmed) continue
    out.add(trimmed.startsWith(".") ? trimmed : `.${trimmed}`)
  }
  return out
}

/**
 * Convert an Iterable of browser File objects (e.g. FileList from webkitdirectory)
 * into SessionFileInput entries preserving webkitRelativePath when present.
 */
export function filesToSessionInputs(files: Iterable<File>): SessionFileInput[] {
  const out: SessionFileInput[] = []
  for (const file of files) {
    const rel = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
    out.push({ file, relativePath: rel })
  }
  return out
}

/**
 * Plan child datasets and companion sidecar attachments for a TEM session folder.
 *
 * Enforces exact legacy crucible-upload-uis sidecar pairing rules per relative directory:
 * - `.ser` pairs with `<stem without trailing _digits>.emi` (non-blocking warning if absent).
 * - `.mrc` pairs with `<stem>.rawtlt` and `<stem>.txt` (in that order) while preserving
 *   `<stem>.txt` as its own standalone `.txt` primary item.
 */
export function planTemSessionUploads(
  inputs: readonly SessionFileInput[],
  options?: PlanTemSessionOptions,
): TemSessionPlan {
  if (!inputs.length) {
    throw new Error("No files selected for session upload.")
  }

  const acceptableExtSet = normalizeExtensions(
    options?.acceptableExtensions ?? TEM_ACCEPTABLE_EXTENSIONS,
  )
  const maxFileBytes = options?.maxFileBytes ?? MAX_FILE_BYTES

  let folderName = ""
  let ignoredCount = 0
  const nonJunkEntries: NormalizedEntry[] = []

  for (const input of inputs) {
    const normalizedPath = normalizeRelativePath(input.relativePath || input.file.name)
    const segments = normalizedPath.split("/").filter(Boolean)
    if (segments.length < 2) {
      throw new Error(
        `Session upload requires selecting a folder; bare file "${normalizedPath || input.file.name}" has no folder segment.`,
      )
    }

    const topFolder = segments[0]
    if (!folderName) {
      folderName = topFolder
    } else if (topFolder !== folderName) {
      throw new Error(
        `All selected files must belong to a single top-level session folder (found "${folderName}" and "${topFolder}").`,
      )
    }

    const fileName = segments[segments.length - 1]
    if (isOsJunkFile(fileName)) {
      ignoredCount += 1
      continue
    }

    const directoryPath = segments.slice(0, -1).join("/")
    const { stem, ext } = splitFileName(fileName)
    nonJunkEntries.push({
      file: input.file,
      relativePath: segments.join("/"),
      directoryPath,
      fileName,
      stem,
      ext,
    })
  }

  // Deterministic ordering across browsers and OS filesystems.
  nonJunkEntries.sort((a, b) =>
    a.relativePath < b.relativePath ? -1 : a.relativePath > b.relativePath ? 1 : 0,
  )

  // Per-directory case-insensitive lookup index so sidecars never cross-pair across folders.
  const dirIndex = new Map<string, Map<string, NormalizedEntry>>()
  for (const entry of nonJunkEntries) {
    let filesInDir = dirIndex.get(entry.directoryPath)
    if (!filesInDir) {
      filesInDir = new Map<string, NormalizedEntry>()
      dirIndex.set(entry.directoryPath, filesInDir)
    }
    const key = entry.fileName.toLowerCase()
    if (!filesInDir.has(key)) {
      filesInDir.set(key, entry)
    }
  }

  const items: TemSessionItem[] = []
  const usedCompanionPaths = new Set<string>()
  const emptyFileSet = new Set<string>()
  const oversizedFileSet = new Set<string>()

  for (const entry of nonJunkEntries) {
    if (!acceptableExtSet.has(entry.ext)) {
      continue
    }

    const sameDir = dirIndex.get(entry.directoryPath)
    const companionEntries: NormalizedEntry[] = []
    let warning: string | undefined

    if (entry.ext === ".ser") {
      const emiStem = entry.stem.replace(/_\d+$/, "")
      const expectedEmiName = `${emiStem}.emi`
      const emiEntry = sameDir?.get(expectedEmiName.toLowerCase())
      if (emiEntry) {
        companionEntries.push(emiEntry)
        usedCompanionPaths.add(emiEntry.relativePath)
      } else {
        warning = `Missing companion .emi file (expected ${expectedEmiName})`
      }
    } else if (entry.ext === ".mrc") {
      // Exact legacy parity: attach .rawtlt then .txt if present, without suppressing
      // the .txt file from also appearing as its own standalone primary item.
      const rawtltEntry = sameDir?.get(`${entry.stem}.rawtlt`.toLowerCase())
      if (rawtltEntry) {
        companionEntries.push(rawtltEntry)
        usedCompanionPaths.add(rawtltEntry.relativePath)
      }
      const txtEntry = sameDir?.get(`${entry.stem}.txt`.toLowerCase())
      if (txtEntry) {
        companionEntries.push(txtEntry)
        usedCompanionPaths.add(txtEntry.relativePath)
      }
    }

    let hasInvalidFile = false
    for (const candidate of [entry, ...companionEntries]) {
      const size = candidate.file.size
      if (size <= 0) {
        emptyFileSet.add(candidate.relativePath)
        hasInvalidFile = true
      } else if (size > maxFileBytes) {
        oversizedFileSet.add(candidate.relativePath)
        hasInvalidFile = true
      }
    }

    if (hasInvalidFile) {
      continue
    }

    const companionFiles = companionEntries.map((c) => c.file)
    const totalBytes =
      entry.file.size + companionFiles.reduce((sum, file) => sum + file.size, 0)

    items.push({
      clientId: `item-${items.length + 1}`,
      datasetName: entry.file.name,
      relativePath: entry.relativePath,
      directoryPath: entry.directoryPath,
      dataFormat: entry.ext.slice(1),
      primaryFile: entry.file,
      companionFiles,
      totalBytes,
      ...(warning ? { warning } : {}),
    })
  }

  for (const entry of nonJunkEntries) {
    if (!acceptableExtSet.has(entry.ext) && !usedCompanionPaths.has(entry.relativePath)) {
      ignoredCount += 1
    }
  }

  const companionCount = items.reduce((sum, item) => sum + item.companionFiles.length, 0)
  const totalUploadBytes = items.reduce((sum, item) => sum + item.totalBytes, 0)

  return {
    folderName,
    items,
    ignoredCount,
    companionCount,
    emptyFiles: Array.from(emptyFileSet),
    oversizedFiles: Array.from(oversizedFileSet),
    totalUploadBytes,
  }
}
