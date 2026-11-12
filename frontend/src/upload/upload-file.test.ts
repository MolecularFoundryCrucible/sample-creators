import { crc32, sha256 } from "hash-wasm"
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("./api", () => ({
  uploadsApi: {
    initiate: vi.fn(),
    sign: vi.fn(),
    status: vi.fn(),
    complete: vi.fn(),
    abort: vi.fn(),
    ingest: vi.fn(),
  },
}))

import { uploadsApi } from "./api"
import { HubApiClientError } from "./result"
import { uploadDatasetFile } from "./upload-file"
import type { PutPart } from "./upload-file"
import { uploadFiles } from "./index"

const api = vi.mocked(uploadsApi)
const DATASET = "0tqn3vn2xhrbs00069f98s8s94"
const RECORD = { mfid: "0tqn3vrnb5zc9000td6rzcetr4", filename: "a.txt" }

function base64Crc32c(hex: string) {
  const bytes = hex.match(/../g)!.map((h) => parseInt(h, 16))
  return btoa(String.fromCharCode(...bytes))
}

function happySession(partSize: number) {
  api.initiate.mockResolvedValue({ state: "uploading", upload_id: "up-1", part_size: partSize })
  api.status.mockResolvedValue({ state: "uploading", acknowledged_part_numbers: [] })
  api.sign.mockImplementation(async ({ parts }) => ({
    parts: parts.map((p) => ({ part_number: p.part_number, url: `https://storage.example/${p.part_number}`, headers: { "x-goog-hash": `crc32c=${p.crc32c}` } })),
  }))
  api.complete.mockResolvedValue(RECORD)
  api.abort.mockResolvedValue({ ok: true })
}

beforeEach(() => {
  vi.resetAllMocks()
})

describe("uploadDatasetFile", () => {
  it("returns the existing file when the API deduplicates", async () => {
    api.initiate.mockResolvedValue({ state: "completed", file: RECORD })
    const result = await uploadDatasetFile({ datasetMfid: DATASET, file: new Blob(["hello"]), filename: "a.txt" })
    expect(result).toEqual(RECORD)
    expect(api.sign).not.toHaveBeenCalled()
  })

  it("uploads every part and completes with whole-file checksums", async () => {
    happySession(4)
    const content = "0123456789"
    const puts: { partNumber: number; text: string; headers: Record<string, string> }[] = []
    const putPart: PutPart = async ({ body, partNumber, headers }) => {
      puts.push({ partNumber, text: await body.text(), headers: { ...headers } })
    }

    const result = await uploadDatasetFile({ datasetMfid: DATASET, file: new Blob([content]), filename: "a.txt", putPart })

    expect(result).toEqual(RECORD)
    expect(puts.map((p) => [p.partNumber, p.text]).sort()).toEqual([[1, "0123"], [2, "4567"], [3, "89"]])
    expect(puts[0].headers["x-goog-hash"]).toMatch(/^crc32c=/)
    expect(api.complete).toHaveBeenCalledWith(
      {
        dataset_mfid: DATASET,
        upload_id: "up-1",
        sha256_hash: await sha256(content),
        crc32c: base64Crc32c(await crc32(content, 0x82f63b78)),
      },
      expect.anything()
    )
    expect(api.abort).not.toHaveBeenCalled()
  })

  it("aborts the session when a part keeps failing", async () => {
    happySession(4)
    const putPart: PutPart = async () => {
      throw Object.assign(new Error("boom"), { retryAfterSeconds: 0 })
    }
    await expect(
      uploadDatasetFile({ datasetMfid: DATASET, file: new Blob(["0123456789"]), filename: "a.txt", putPart })
    ).rejects.toThrow()
    expect(api.abort).toHaveBeenCalledWith({ dataset_mfid: DATASET, upload_id: "up-1" })
    expect(api.complete).not.toHaveBeenCalled()
  })

  it("retries completion on a retryable error", async () => {
    happySession(1024)
    api.complete
      .mockRejectedValueOnce(new HubApiClientError({ message: "busy", retryable: true, retryAfterSeconds: 0 }))
      .mockResolvedValueOnce(RECORD)
    const result = await uploadDatasetFile({ datasetMfid: DATASET, file: new Blob(["abc"]), filename: "a.txt", putPart: async () => {} })
    expect(result).toEqual(RECORD)
    expect(api.complete).toHaveBeenCalledTimes(2)
  })

  it("rejects bad file names before contacting the server", async () => {
    await expect(uploadDatasetFile({ datasetMfid: DATASET, file: new Blob(["x"]), filename: "../x" })).rejects.toThrow(
      /dot path segments/
    )
    expect(api.initiate).not.toHaveBeenCalled()
  })
})

describe("uploadFiles", () => {
  it("uploads at most two files at once and requests ingestion once per file", async () => {
    let active = 0
    let maxActive = 0
    api.initiate.mockImplementation(async ({ filename }) => {
      active++
      maxActive = Math.max(maxActive, active)
      await new Promise((resolve) => setTimeout(resolve, 5))
      active--
      return { state: "completed", file: { mfid: `mfid-${filename}`, filename } }
    })
    api.ingest.mockRejectedValueOnce(new Error("ingestion is off"))

    const files = ["a.tif", "b.tif", "c.png"].map((name) => new File(["data"], name))
    const results = await uploadFiles({
      datasetMfid: DATASET,
      files,
      ingestion: (file) => (file.name.endsWith(".tif") ? { requested: true, ingestionClass: "FeiSemTifIngestor" } : { requested: false }),
    })

    expect(maxActive).toBe(2)
    expect(results.every((r) => r.ok)).toBe(true)
    expect(api.ingest).toHaveBeenCalledTimes(3)
    expect(api.ingest).toHaveBeenCalledWith({ dataset_mfid: DATASET, file_mfid: "mfid-a.tif", requested: true, ingestion_class: "FeiSemTifIngestor" })
    expect(api.ingest).toHaveBeenCalledWith({ dataset_mfid: DATASET, file_mfid: "mfid-c.png", requested: false })
    expect(results.filter((r) => r.ok && r.ingestionError)).toHaveLength(1)
  })
})
