// Browser-direct dataset file uploads. Plain-JS pages use window.CrucibleUpload; module code
// can import these functions directly.
import { uploadsApi } from "./api"
import type { DatasetFile } from "./api"
import { uploadDatasetFile } from "./upload-file"
import type { PutPart, UploadProgress } from "./upload-file"

export { uploadDatasetFile } from "./upload-file"
export type { UploadProgress } from "./upload-file"
export type { DatasetFile } from "./api"

// The app shares one API key, and crucible-api allows 8 concurrent upload sessions per key,
// so each browser uploads at most this many files at once.
export const MAX_CONCURRENT_FILES = 2

export type IngestionChoice = { requested: false } | { requested: true; ingestionClass?: string }

export type FileUploadResult =
  | { file: File; ok: true; record: DatasetFile; ingestionError?: string }
  | { file: File; ok: false; error: string }

export async function uploadFiles(options: {
  datasetMfid: string
  files: readonly File[]
  // Per file: whether to request ingestion and with which ingestor. Omit to skip the call.
  ingestion?: (file: File) => IngestionChoice | undefined
  onProgress?: (file: File, progress: UploadProgress) => void
  signal?: AbortSignal
  putPart?: PutPart
}): Promise<FileUploadResult[]> {
  const { datasetMfid, files, ingestion, onProgress, signal, putPart } = options
  const results: FileUploadResult[] = new Array(files.length)
  let next = 0

  const worker = async () => {
    while (next < files.length) {
      const index = next++
      const file = files[index]
      try {
        const record = await uploadDatasetFile({
          datasetMfid,
          file,
          filename: file.name,
          onProgress: (progress) => onProgress?.(file, progress),
          signal,
          putPart,
        })
        const result: FileUploadResult = { file, ok: true, record }
        const choice = ingestion?.(file)
        if (choice) {
          // Each ingest call creates a new ingestion request, so it is never retried here.
          try {
            await uploadsApi.ingest({
              dataset_mfid: datasetMfid,
              file_mfid: record.mfid,
              requested: choice.requested,
              ...(choice.requested && choice.ingestionClass ? { ingestion_class: choice.ingestionClass } : {}),
            })
          } catch (error) {
            result.ingestionError = error instanceof Error ? error.message : String(error)
          }
        }
        results[index] = result
      } catch (error) {
        if (signal?.aborted) throw error
        results[index] = { file, ok: false, error: error instanceof Error ? error.message : String(error) }
      }
    }
  }

  await Promise.all(Array.from({ length: Math.min(MAX_CONCURRENT_FILES, files.length) }, worker))
  return results
}

declare global {
  interface Window {
    CrucibleUpload?: { uploadFiles: typeof uploadFiles; uploadDatasetFile: typeof uploadDatasetFile }
  }
}

if (typeof window !== "undefined") {
  window.CrucibleUpload = { uploadFiles, uploadDatasetFile }
}
