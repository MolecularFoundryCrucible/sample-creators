// Adapted from crucible-hub src/features/dataset-files/upload-orchestrator.ts at 7ac135b.
// Changes: talks to this app's /api/uploads routes instead of Hub server functions, no
// replace-existing-file flow, and the part PUT can be injected for tests.
import {
  computeUploadDigests,
  createUploadPartChecksums,
  MAX_UPLOAD_PART_NUMBER,
  MAX_UPLOAD_SIZE,
  planUploadParts,
  runUploadParts,
  UploadSizeError,
  validateUploadFilename,
} from "./uploads"
import { uploadsApi } from "./api"
import type { DatasetFile } from "./api"
import { HubApiClientError } from "./result"

export type UploadPhase = "preparing" | "uploading" | "completing" | "done"

export type UploadProgress = {
  phase: UploadPhase
  preparedBytes: number
  uploadedBytes: number
}

export type PutPart = (options: {
  body: Blob
  headers: Readonly<Record<string, string>>
  onProgress?: (loadedBytes: number) => void
  partNumber: number
  signal?: AbortSignal
  url: string
}) => Promise<void>

const PROGRESS_INTERVAL_MS = 250
const DEFAULT_COMPLETION_RETRY_SECONDS = 5
const MAX_COMPLETION_ATTEMPTS = 3

export class UploadFilenameError extends Error {
  constructor(issues: readonly string[]) {
    super(issues[0] ?? "The file name is invalid.")
    this.name = "UploadFilenameError"
  }
}

function wait(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timer)
      reject(signal.reason)
    }
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort)
      resolve()
    }, milliseconds)
    signal.addEventListener("abort", onAbort, { once: true })
  })
}

function partTransferError(partNumber: number, retryAfter: string | null) {
  const seconds = retryAfter === null ? NaN : Number(retryAfter)
  return Object.assign(
    new Error(`Part ${partNumber} could not be transferred.`),
    Number.isSafeInteger(seconds) && seconds >= 0 ? { retryAfterSeconds: seconds } : {}
  )
}

export const putPartWithXhr: PutPart = (options) => {
  const { body, headers, onProgress, partNumber, signal, url } = options
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason)
      return
    }
    const request = new XMLHttpRequest()
    const abort = () => request.abort()
    const settle = () => signal?.removeEventListener("abort", abort)
    request.open("PUT", url)
    for (const [name, value] of Object.entries(headers)) {
      request.setRequestHeader(name, value)
    }
    request.upload.onprogress = (event) => onProgress?.(event.loaded)
    request.onload = () => {
      settle()
      if (request.status >= 200 && request.status < 300) resolve()
      else reject(partTransferError(partNumber, request.getResponseHeader("Retry-After")))
    }
    request.onerror = () => {
      settle()
      reject(partTransferError(partNumber, null))
    }
    request.onabort = () => {
      settle()
      reject(signal?.reason ?? new DOMException("The upload was cancelled.", "AbortError"))
    }
    signal?.addEventListener("abort", abort, { once: true })
    request.send(body)
  })
}

async function completeWithRetry(
  complete: () => Promise<DatasetFile>,
  signal: AbortSignal
): Promise<DatasetFile> {
  for (let attempt = 1; ; attempt += 1) {
    try {
      return await complete()
    } catch (error) {
      if (
        attempt >= MAX_COMPLETION_ATTEMPTS ||
        !(error instanceof HubApiClientError) ||
        !error.details.retryable
      ) {
        throw error
      }
      await wait((error.details.retryAfterSeconds ?? DEFAULT_COMPLETION_RETRY_SECONDS) * 1000, signal)
    }
  }
}

export async function uploadDatasetFile(options: {
  datasetMfid: string
  file: Blob
  filename: string
  onProgress?: (progress: UploadProgress) => void
  signal?: AbortSignal
  putPart?: PutPart
}): Promise<DatasetFile> {
  const { datasetMfid, file, filename, putPart = putPartWithXhr } = options
  const onProgress = options.onProgress ?? (() => undefined)
  const signal = options.signal ?? new AbortController().signal

  const filenameIssues = validateUploadFilename(filename)
  if (filenameIssues.length > 0) throw new UploadFilenameError(filenameIssues)
  if (file.size === 0) throw new Error("Empty files can't be uploaded.")
  if (file.size > MAX_UPLOAD_SIZE) throw new UploadSizeError()

  const partLoaded = new Map<number, number>()
  let preparedBytes = 0
  let completedBytes = 0
  let phase: UploadPhase = "preparing"
  let lastReport = 0
  const report = (force = false) => {
    const now = performance.now()
    if (!force && now - lastReport < PROGRESS_INTERVAL_MS) return
    lastReport = now
    let uploadedBytes = completedBytes
    for (const loaded of partLoaded.values()) uploadedBytes += loaded
    if (phase === "preparing" && uploadedBytes > 0) phase = "uploading"
    onProgress({ phase, preparedBytes, uploadedBytes })
  }
  report(true)

  const initiation = await uploadsApi.initiate(
    { dataset_mfid: datasetMfid, filename, size: file.size, idempotency_key: crypto.randomUUID() },
    signal
  )
  if (initiation.state === "completed") {
    onProgress({ phase: "done", preparedBytes: file.size, uploadedBytes: file.size })
    return initiation.file
  }
  const uploadId = initiation.upload_id
  const partSize = initiation.part_size ?? undefined
  const abortSession = () =>
    uploadsApi.abort({ dataset_mfid: datasetMfid, upload_id: uploadId }).catch(() => undefined)

  let parts: ReturnType<typeof planUploadParts>
  try {
    parts = planUploadParts(file.size, partSize)
    if (parts.length > MAX_UPLOAD_PART_NUMBER) {
      throw new Error("The upload session uses an unsupported part size.")
    }
  } catch (error) {
    await abortSession()
    throw error
  }
  const partSizes = new Map(parts.map((part) => [part.partNumber, part.end - part.start]))
  const checksums = createUploadPartChecksums()
  const preparation = new AbortController()
  const stopPreparation = () => preparation.abort(signal.reason)
  signal.addEventListener("abort", stopPreparation, { once: true })
  const digests = computeUploadDigests(
    file,
    parts,
    (bytes) => {
      preparedBytes = bytes
      report()
    },
    preparation.signal,
    (partNumber, crc32cBase64) => checksums.resolve(partNumber, crc32cBase64)
  )
  digests.catch((error: unknown) => checksums.fail(error))

  try {
    if (initiation.state !== "uploading") throw new Error("The upload could not be started.")

    await runUploadParts({
      file,
      parts,
      signatures: checksums,
      signal,
      transport: {
        readAcknowledgedPartNumbers: async () => {
          const current = await uploadsApi.status({ dataset_mfid: datasetMfid, upload_id: uploadId }, signal)
          if (current.state !== "uploading") {
            throw new Error(
              current.failure_code
                ? `The upload failed (${current.failure_code}).`
                : "The upload is no longer accepting parts."
            )
          }
          if (current.part_size != null && partSize !== undefined && current.part_size !== partSize) {
            throw new Error("The upload session uses an unsupported part size.")
          }
          return new Set(current.acknowledged_part_numbers)
        },
        signParts: async (signatures) => {
          const signed = await uploadsApi.sign(
            {
              dataset_mfid: datasetMfid,
              upload_id: uploadId,
              parts: signatures.map((s) => ({ part_number: s.partNumber, crc32c: s.crc32cBase64 })),
            },
            signal
          )
          return new Map(
            signed.parts.map((part) => [part.part_number, { headers: part.headers, url: part.url }])
          )
        },
        putPart: (part, signed, body, partSignal, onPartProgress) =>
          putPart({
            body,
            headers: signed.headers,
            onProgress: onPartProgress,
            partNumber: part.partNumber,
            signal: partSignal,
            url: signed.url,
          }),
      },
      wait: (milliseconds) => wait(milliseconds, signal),
      onPartProgress: (partNumber, loadedBytes) => {
        partLoaded.set(partNumber, loadedBytes)
        report()
      },
      onPartUploaded: (partNumber) => {
        partLoaded.delete(partNumber)
        completedBytes += partSizes.get(partNumber) ?? 0
        report()
      },
    })

    const { crc32cBase64, sha256Hex } = await digests
    phase = "completing"
    report(true)
    const completed = await completeWithRetry(
      () =>
        uploadsApi.complete(
          { dataset_mfid: datasetMfid, upload_id: uploadId, sha256_hash: sha256Hex, crc32c: crc32cBase64 },
          signal
        ),
      signal
    )
    phase = "done"
    report(true)
    return completed
  } catch (error) {
    preparation.abort()
    await digests.catch(() => undefined)
    await abortSession()
    throw error
  } finally {
    signal.removeEventListener("abort", stopPreparation)
  }
}
