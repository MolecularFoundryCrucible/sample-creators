// Calls to this app's /api/uploads routes (routes/uploads.py), which hold the API key and
// talk to crucible-api. Errors come back as HubApiClientError so uploads.ts can decide
// whether to retry.
import { HubApiClientError } from "./result"

export type DatasetFile = {
  mfid: string
  filename: string
  size?: number
  [key: string]: unknown
}

export type Initiation =
  | { state: "completed"; file: DatasetFile }
  | { state: "uploading" | "aborted" | "failed"; upload_id: string; part_size?: number | null }

export type UploadStatus = {
  state: "uploading" | "completed" | "aborted" | "failed"
  acknowledged_part_numbers: number[]
  part_size?: number | null
  failure_code?: string | null
  file?: DatasetFile | null
}

export type SignedPart = {
  part_number: number
  url: string
  headers: Record<string, string>
}

function baseUrl(): string {
  const base = (globalThis as { BASE_URL?: unknown }).BASE_URL
  return typeof base === "string" ? base : ""
}

async function call<T>(
  method: "GET" | "POST",
  path: string,
  body?: unknown,
  signal?: AbortSignal
): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${baseUrl()}/api/uploads/${path}`, {
      method,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
      signal,
    })
  } catch (error) {
    if (signal?.aborted) throw error
    throw new HubApiClientError({ message: "The server could not be reached.", retryable: true })
  }
  const data = (await response.json().catch(() => ({}))) as Record<string, unknown>
  if (!response.ok) {
    throw new HubApiClientError({
      message: typeof data.error === "string" ? data.error : `Request failed (${response.status})`,
      retryable: data.retryable === true,
      retryAfterSeconds: typeof data.retry_after === "number" ? data.retry_after : undefined,
      status: response.status,
      code: typeof data.code === "string" ? data.code : undefined,
    })
  }
  return data as T
}

export const uploadsApi = {
  initiate: (
    input: { dataset_mfid: string; filename: string; size: number; idempotency_key: string },
    signal?: AbortSignal
  ) => call<Initiation>("POST", "initiate", input, signal),

  sign: (
    input: { dataset_mfid: string; upload_id: string; parts: { part_number: number; crc32c: string }[] },
    signal?: AbortSignal
  ) => call<{ parts: SignedPart[] }>("POST", "sign", input, signal),

  status: (input: { dataset_mfid: string; upload_id: string }, signal?: AbortSignal) =>
    call<UploadStatus>("GET", `status?${new URLSearchParams(input)}`, undefined, signal),

  complete: (
    input: { dataset_mfid: string; upload_id: string; sha256_hash: string; crc32c: string },
    signal?: AbortSignal
  ) => call<DatasetFile>("POST", "complete", input, signal),

  abort: (input: { dataset_mfid: string; upload_id: string }) =>
    call<{ ok: true }>("POST", "abort", input),

  ingest: (input: {
    dataset_mfid: string
    file_mfid: string
    requested: boolean
    ingestion_class?: string
  }) => call<unknown>("POST", "ingest", input),
}
