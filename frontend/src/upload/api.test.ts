import { afterEach, describe, expect, it, vi } from "vitest"

import { uploadsApi } from "./api"

describe("uploadsApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("prefixes requests with the page's BASE_URL", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: true }), { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)
    vi.stubGlobal("BASE_URL", "/sample-creators")
    await uploadsApi.abort({ dataset_mfid: "d", upload_id: "u" })
    expect(fetchMock).toHaveBeenCalledWith("/sample-creators/api/uploads/abort", expect.anything())
  })

  it("turns error responses into HubApiClientError with the server message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: "nope", retryable: true, retry_after: 3 }), { status: 502 })))
    await expect(uploadsApi.abort({ dataset_mfid: "d", upload_id: "u" })).rejects.toMatchObject({
      message: "nope",
      details: { retryable: true, retryAfterSeconds: 3, status: 502 },
    })
  })
})
