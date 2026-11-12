// Copied from crucible-hub src/data/crucible/uploads.test.ts at 7ac135b (2026-11-11). Keep in sync by hand.
import { crc32, sha256 } from "hash-wasm"
import { describe, expect, it, vi } from "vitest"

import {
  computeUploadDigests,
  createUploadPartChecksums,
  CRC32C_POLYNOMIAL,
  MAX_CONCURRENT_PARTS,
  MAX_PARTS_PER_SIGN_REQUEST,
  MAX_UPLOAD_SIZE,
  planUploadParts,
  runUploadParts,
  UPLOAD_PART_SIZE,
  UploadPartError,
  UploadSizeError,
  validateUploadFilename,
} from "./uploads"
import type { UploadPartTransport } from "./uploads"
import { HubApiClientError } from "./result"

function rateLimitedError(retryAfterSeconds: number): HubApiClientError {
  return new HubApiClientError({
    kind: "rate-limited",
    message: "Too many requests were made. Try again shortly.",
    correlationId: "request-1",
    retryable: true,
    retryAfterSeconds,
  })
}

const SHA256_EMPTY =
  "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

function crc32cBase64FromHex(hex: string): string {
  const bytes = new Uint8Array(hex.length / 2)
  for (let index = 0; index < bytes.length; index += 1) {
    bytes[index] = Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16)
  }
  let binary = ""
  for (const byte of bytes) {
    binary += String.fromCharCode(byte)
  }
  return btoa(binary)
}

describe("upload part planning", () => {
  it("plans one part for a small file", () => {
    expect(planUploadParts(1024)).toEqual([
      { partNumber: 1, start: 0, end: 1024 },
    ])
  })

  it("keeps one part for a file at the part size", () => {
    expect(planUploadParts(UPLOAD_PART_SIZE)).toEqual([
      { partNumber: 1, start: 0, end: UPLOAD_PART_SIZE },
    ])
  })

  it("adds a final short part above the part size", () => {
    expect(planUploadParts(UPLOAD_PART_SIZE + 1)).toEqual([
      { partNumber: 1, start: 0, end: UPLOAD_PART_SIZE },
      { partNumber: 2, start: UPLOAD_PART_SIZE, end: UPLOAD_PART_SIZE + 1 },
    ])
  })

  it("plans the maximum 500 GiB upload", () => {
    const parts = planUploadParts(MAX_UPLOAD_SIZE)
    const partCount = MAX_UPLOAD_SIZE / UPLOAD_PART_SIZE
    expect(parts).toHaveLength(partCount)
    expect(parts[0]).toEqual({
      partNumber: 1,
      start: 0,
      end: UPLOAD_PART_SIZE,
    })
    expect(parts.at(-1)).toEqual({
      partNumber: partCount,
      start: MAX_UPLOAD_SIZE - UPLOAD_PART_SIZE,
      end: MAX_UPLOAD_SIZE,
    })
  })

  it("rejects uploads above the maximum size", () => {
    expect(() => planUploadParts(MAX_UPLOAD_SIZE + 1)).toThrow(UploadSizeError)
  })

  it("rejects non-positive part sizes", () => {
    expect(() => planUploadParts(10, 0)).toThrow()
    expect(() => planUploadParts(10, -4)).toThrow()
  })

  it("plans no parts for an empty file", () => {
    expect(planUploadParts(0)).toEqual([])
  })

  it("rejects invalid sizes", () => {
    expect(() => planUploadParts(-1)).toThrow()
    expect(() => planUploadParts(1.5)).toThrow()
  })
})

describe("upload filename validation", () => {
  it("accepts relative paths", () => {
    expect(validateUploadFilename("runs/run-001/data.csv")).toEqual([])
  })

  it("requires a name", () => {
    expect(validateUploadFilename("")).toHaveLength(1)
  })

  it("rejects backslashes and control characters", () => {
    expect(validateUploadFilename("a\\b")).toHaveLength(1)
    expect(validateUploadFilename("a\nb")).toHaveLength(1)
    expect(validateUploadFilename("a\u0000b")).toHaveLength(1)
  })

  it("rejects absolute paths and empty segments", () => {
    expect(validateUploadFilename("/abs/path")).toHaveLength(2)
    expect(validateUploadFilename("a//b")).toHaveLength(1)
    expect(validateUploadFilename("a/")).toHaveLength(1)
  })

  it("rejects dot segments", () => {
    expect(validateUploadFilename("./a")).toHaveLength(1)
    expect(validateUploadFilename("../a")).toHaveLength(1)
    expect(validateUploadFilename("a/./b")).toHaveLength(1)
    expect(validateUploadFilename("a/../b")).toHaveLength(1)
  })
})

describe("upload digests", () => {
  it("computes known digests for a single part", async () => {
    const file = new Blob(["123456789"])
    const digests = await computeUploadDigests(file, planUploadParts(file.size))

    expect(digests).toEqual({
      sha256Hex:
        "15e2b0d3c33891ebb0f1ef609ec419420c20e320ce94c65fbc8c3312448eb225",
      crc32cBase64: "4waSgw==",
      partCrc32cBase64: ["4waSgw=="],
    })
  })

  it("computes known CRC32C per part and for the whole file", async () => {
    const file = new Blob(["hello world"])
    const digests = await computeUploadDigests(
      file,
      planUploadParts(file.size, 6)
    )

    expect(digests.crc32cBase64).toBe("yZRlqg==")
    expect(digests.partCrc32cBase64).toEqual([
      crc32cBase64FromHex(await crc32("hello ", CRC32C_POLYNOMIAL)),
      crc32cBase64FromHex(await crc32("world", CRC32C_POLYNOMIAL)),
    ])
    expect(digests.sha256Hex).toBe(
      "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    )
  })

  it("rotates part digests across read chunk boundaries", async () => {
    const size = 8 * 1024 * 1024 + 4096
    const bytes = new Uint8Array(size)
    for (let index = 0; index < size; index += 1) {
      bytes[index] = index % 251
    }
    const file = new Blob([bytes])
    const firstPartEnd = 5 * 1024 * 1024
    const digests = await computeUploadDigests(
      file,
      planUploadParts(size, firstPartEnd)
    )

    expect(digests.sha256Hex).toBe(await sha256(bytes))
    expect(digests.crc32cBase64).toBe(
      crc32cBase64FromHex(await crc32(bytes, CRC32C_POLYNOMIAL))
    )
    expect(digests.partCrc32cBase64).toEqual([
      crc32cBase64FromHex(
        await crc32(bytes.slice(0, firstPartEnd), CRC32C_POLYNOMIAL)
      ),
      crc32cBase64FromHex(
        await crc32(bytes.slice(firstPartEnd), CRC32C_POLYNOMIAL)
      ),
    ])
  })

  it("digests an empty file without parts", async () => {
    const digests = await computeUploadDigests(new Blob([]), [])

    expect(digests.sha256Hex).toBe(SHA256_EMPTY)
    expect(digests.crc32cBase64).toBe("AAAAAA==")
    expect(digests.partCrc32cBase64).toEqual([])
  })

  it("reports progress after each read chunk", async () => {
    const file = new Blob(["123456789"])
    const progress = vi.fn()

    await computeUploadDigests(file, planUploadParts(file.size), progress)

    expect(progress).toHaveBeenCalledWith(9)
  })

  it("fails when parts do not cover the file", async () => {
    await expect(
      computeUploadDigests(new Blob(["123456789"]), [])
    ).rejects.toThrow("do not tile the file")
  })

  it("fails when parts overhang or offset the file", async () => {
    await expect(
      computeUploadDigests(new Blob([new Uint8Array(10)]), planUploadParts(8))
    ).rejects.toThrow("do not tile the file")
    await expect(
      computeUploadDigests(new Blob([new Uint8Array(10)]), [
        { partNumber: 1, start: 2, end: 10 },
      ])
    ).rejects.toThrow("do not tile the file")
    await expect(
      computeUploadDigests(new Blob([]), [{ partNumber: 1, start: 0, end: 4 }])
    ).rejects.toThrow("do not tile the file")
  })
})

type SignedTransportHandlers = {
  acknowledged?: number[]
  onPut?: (partNumber: number, attempt: number) => Promise<void> | void
}

function signedTransport(handlers: SignedTransportHandlers = {}) {
  const signRequests: number[][] = []
  const puts: { partNumber: number; url: string; size: number }[] = []
  const putAttempts = new Map<number, number>()
  let active = 0
  let maxActive = 0

  const transport: UploadPartTransport = {
    async readAcknowledgedPartNumbers() {
      return new Set(handlers.acknowledged ?? [])
    },
    async signParts(parts) {
      signRequests.push(parts.map((part) => part.partNumber))
      return new Map(
        parts.map((part) => [
          part.partNumber,
          {
            headers: { "x-goog-hash": `crc32c=${part.crc32cBase64}` },
            url: `https://uploads.crucible.invalid/part-${part.partNumber}`,
          },
        ])
      )
    },
    async putPart(part, { url }, body) {
      const attempt = (putAttempts.get(part.partNumber) ?? 0) + 1
      putAttempts.set(part.partNumber, attempt)
      active += 1
      maxActive = Math.max(maxActive, active)
      try {
        await handlers.onPut?.(part.partNumber, attempt)
        puts.push({
          partNumber: part.partNumber,
          url,
          size: body.size,
        })
      } finally {
        active -= 1
      }
    },
  }

  return {
    transport,
    signRequests,
    puts,
    putAttempts,
    get maxActive() {
      return maxActive
    },
  }
}

describe("part uploads", () => {
  it("uploads every part with signed URLs and sliced bodies", async () => {
    const file = new Blob(["abcdef"])
    const { transport, puts, signRequests } = signedTransport()

    await runUploadParts({
      file,
      parts: planUploadParts(file.size, 2),
      signatures: ["c2lnLTE=", "c2lnLTI=", "c2lnLTM="],
      transport,
      wait: async () => {},
    })

    expect(signRequests).toEqual([[1, 2, 3]])
    expect(puts.map((put) => put.partNumber)).toEqual([1, 2, 3])
    expect(puts.map((put) => put.size)).toEqual([2, 2, 2])
    expect(
      puts.every((put) =>
        put.url.startsWith("https://uploads.crucible.invalid/")
      )
    ).toBe(true)
  })

  it("runs at most the concurrent part limit at once", async () => {
    const file = new Blob([new Uint8Array(10)])
    const stats = signedTransport()

    await runUploadParts({
      file,
      parts: planUploadParts(file.size, 1),
      signatures: Array.from({ length: file.size }, () => "c2ln"),
      transport: stats.transport,
      wait: async () => {},
    })

    expect(stats.maxActive).toBe(MAX_CONCURRENT_PARTS)
  })

  it("signs just-in-time windows capped at the API limit", async () => {
    const file = new Blob([new Uint8Array(40)])
    const { transport, signRequests } = signedTransport()

    await runUploadParts({
      file,
      parts: planUploadParts(file.size, 1),
      signatures: Array.from({ length: file.size }, () => "c2ln"),
      transport,
      wait: async () => {},
    })

    expect(signRequests).toEqual([
      Array.from({ length: 32 }, (_, index) => index + 1),
      [33, 34, 35, 36, 37, 38, 39, 40],
    ])
    for (const request of signRequests) {
      expect(request.length).toBeLessThanOrEqual(MAX_PARTS_PER_SIGN_REQUEST)
    }
  })

  it("keeps the other lanes busy while one part is slow", async () => {
    const file = new Blob([new Uint8Array(6)])
    let releaseSlowPart: () => void = () => undefined
    const slowPart = new Promise<void>((resolve) => {
      releaseSlowPart = resolve
    })
    const { transport, puts, signRequests } = signedTransport({
      onPut: async (partNumber) => {
        if (partNumber === 1) await slowPart
      },
    })
    const run = runUploadParts({
      file,
      parts: planUploadParts(file.size, 1),
      signatures: Array.from({ length: file.size }, () => "c2ln"),
      transport,
      maxConcurrentParts: 2,
      signWindowParts: 2,
      wait: async () => {},
    })

    await vi.waitFor(() => expect(puts).toHaveLength(5))
    releaseSlowPart()
    await run

    expect(puts.map((put) => put.partNumber)).toEqual([2, 3, 4, 5, 6, 1])
    expect(signRequests).toEqual([
      [1, 2],
      [3, 4],
      [5, 6],
    ])
  })

  it("skips acknowledged parts", async () => {
    const file = new Blob(["abcd"])
    const { transport, puts } = signedTransport({ acknowledged: [1] })

    await runUploadParts({
      file,
      parts: planUploadParts(file.size, 2),
      signatures: ["c2lnLTE=", "c2lnLTI="],
      transport,
      wait: async () => {},
    })

    expect(puts.map((put) => put.partNumber)).toEqual([2])
  })

  it("waits for Retry-After and re-signs failed parts", async () => {
    const file = new Blob(["abcd"])
    const waits: number[] = []
    const rateLimited = Object.assign(new Error("Too many requests."), {
      retryAfterSeconds: 2,
    })
    const { transport, signRequests, puts } = signedTransport({
      onPut: (partNumber, attempt) => {
        if (partNumber === 1 && attempt === 1) {
          throw rateLimited
        }
      },
    })

    await runUploadParts({
      file,
      parts: planUploadParts(file.size, 2),
      signatures: ["c2lnLTE=", "c2lnLTI="],
      transport,
      wait: async (milliseconds) => {
        waits.push(milliseconds)
      },
    })

    expect(waits).toEqual([2000])
    expect(signRequests).toEqual([[1, 2], [1]])
    expect(puts.map((put) => put.partNumber)).toEqual([2, 1])
  })

  it("gives up after the maximum attempts", async () => {
    const file = new Blob(["a"])
    const { transport, signRequests } = signedTransport({
      onPut: () => {
        throw new Error("storage unavailable and the signed URL leaked here")
      },
    })

    const caught = await runUploadParts({
      file,
      parts: planUploadParts(file.size, 1),
      signatures: ["c2ln"],
      transport,
      wait: async () => {},
    }).then(
      () => null,
      (error: unknown) => error
    )

    expect(caught).toBeInstanceOf(UploadPartError)
    if (caught instanceof UploadPartError) {
      expect(caught.partNumber).toBe(1)
      expect(caught.message).toBe("Part 1 could not be transferred.")
    }
    expect(String(caught)).not.toContain("storage unavailable")
    expect(signRequests).toHaveLength(3)
  })

  it("keeps retrying while each attempt makes progress", async () => {
    const file = new Blob(["abcd"])
    const { transport, puts, signRequests } = signedTransport({
      onPut: (partNumber, attempt) => {
        if (attempt < partNumber) {
          throw new Error("signed URL expired")
        }
      },
    })

    await runUploadParts({
      file,
      parts: planUploadParts(file.size, 1),
      signatures: ["c2ln", "c2ln", "c2ln", "c2ln"],
      transport,
      wait: async () => {},
    })

    expect(signRequests).toEqual([[1, 2, 3, 4], [2, 3, 4], [3, 4], [4]])
    expect(puts.map((put) => put.partNumber)).toEqual([1, 2, 3, 4])
  })

  it("stops without retrying when signing fails permanently", async () => {
    const forbidden = new HubApiClientError({
      kind: "forbidden",
      message: "You do not have permission to upload to this dataset.",
      correlationId: "request-2",
      retryable: false,
    })
    const { transport } = signedTransport()
    let signCalls = 0

    await expect(
      runUploadParts({
        file: new Blob(["a"]),
        parts: planUploadParts(1, 1),
        signatures: ["c2ln"],
        transport: {
          ...transport,
          async signParts() {
            signCalls += 1
            throw forbidden
          },
        },
        wait: async () => {},
      })
    ).rejects.toBe(forbidden)
    expect(signCalls).toBe(1)
  })

  it("starts uploading as soon as the first checksums are ready", async () => {
    const file = new Blob([new Uint8Array(12)])
    const checksums = createUploadPartChecksums()
    const { transport, signRequests, puts } = signedTransport()
    const run = runUploadParts({
      file,
      parts: planUploadParts(file.size, 1),
      signatures: checksums,
      transport,
      wait: async () => {},
    })

    for (let part = 1; part <= 8; part += 1) checksums.resolve(part, "c2ln")
    await vi.waitFor(() => expect(signRequests).toHaveLength(1))
    expect(signRequests[0]).toEqual([1, 2, 3, 4, 5, 6, 7, 8])

    for (let part = 9; part <= 12; part += 1) checksums.resolve(part, "c2ln")
    await run
    expect(signRequests[1]).toEqual([9, 10, 11, 12])
    expect(puts).toHaveLength(12)
  })

  it("stops when preparing the checksums fails", async () => {
    const checksums = createUploadPartChecksums()
    const { transport } = signedTransport()
    const run = runUploadParts({
      file: new Blob(["ab"]),
      parts: planUploadParts(2, 1),
      signatures: checksums,
      transport,
      wait: async () => {},
    })
    checksums.fail(new Error("The file could not be read."))
    await expect(run).rejects.toThrow("The file could not be read.")
  })

  it("reports bytes in flight and resets them on a failed attempt", async () => {
    const progress: [number, number][] = []
    const { transport } = signedTransport()
    let attempts = 0
    await runUploadParts({
      file: new Blob(["abcd"]),
      parts: planUploadParts(4, 4),
      signatures: ["c2ln"],
      transport: {
        ...transport,
        async putPart(part, signed, body, signal, onProgress) {
          attempts += 1
          onProgress?.(2)
          if (attempts === 1) throw new Error("connection reset")
          onProgress?.(4)
          return transport.putPart(part, signed, body, signal)
        },
      },
      wait: async () => {},
      onPartProgress: (partNumber, loaded) =>
        progress.push([partNumber, loaded]),
    })
    expect(progress).toEqual([
      [1, 2],
      [1, 0],
      [1, 2],
      [1, 4],
    ])
  })

  it("fails when a requested part is not signed", async () => {
    const transport: UploadPartTransport = {
      async readAcknowledgedPartNumbers() {
        return new Set()
      },
      async signParts() {
        return new Map()
      },
      async putPart() {},
    }

    await expect(
      runUploadParts({
        file: new Blob(["ab"]),
        parts: planUploadParts(2, 1),
        signatures: ["c2ln", "c2ln"],
        transport,
        wait: async () => {},
      })
    ).rejects.toThrow("could not be transferred")
  })

  it("retries signing failures within the attempt bound", async () => {
    const file = new Blob(["abcd"])
    const waits: number[] = []
    let signCalls = 0
    const { transport, signRequests, puts } = signedTransport()
    const failingSign: UploadPartTransport = {
      ...transport,
      async signParts(parts) {
        signCalls += 1
        if (signCalls === 1) {
          throw rateLimitedError(2)
        }
        return transport.signParts(parts)
      },
    }

    await runUploadParts({
      file,
      parts: planUploadParts(file.size, 2),
      signatures: ["c2lnLTE=", "c2lnLTI="],
      transport: failingSign,
      wait: async (milliseconds) => {
        waits.push(milliseconds)
      },
    })

    expect(waits).toEqual([2000])
    expect(signRequests).toEqual([[1, 2]])
    expect(puts.map((put) => put.partNumber)).toEqual([1, 2])
  })

  it("honors long Retry-After values from the server", async () => {
    const file = new Blob(["a"])
    const waits: number[] = []
    let signCalls = 0
    const { transport, puts } = signedTransport()
    const failingSign: UploadPartTransport = {
      ...transport,
      async signParts(parts) {
        signCalls += 1
        if (signCalls === 1) {
          throw rateLimitedError(3600)
        }
        return transport.signParts(parts)
      },
    }

    await runUploadParts({
      file,
      parts: planUploadParts(file.size, 1),
      signatures: ["c2ln"],
      transport: failingSign,
      wait: async (milliseconds) => {
        waits.push(milliseconds)
      },
    })

    expect(waits).toEqual([3600000])
    expect(puts).toHaveLength(1)
  })

  it("caps signing windows at the API limit", async () => {
    const file = new Blob([new Uint8Array(70)])
    const { transport, signRequests } = signedTransport()

    await runUploadParts({
      file,
      parts: planUploadParts(file.size, 1),
      signatures: Array.from({ length: file.size }, () => "c2ln"),
      transport,
      signWindowParts: 128,
      wait: async () => {},
    })

    expect(signRequests).toHaveLength(2)
    expect(signRequests[0]).toHaveLength(MAX_PARTS_PER_SIGN_REQUEST)
    expect(signRequests[1]).toEqual([65, 66, 67, 68, 69, 70])
  })

  it("stops mid-flight when the signal aborts", async () => {
    const file = new Blob([new Uint8Array(4)])
    const controller = new AbortController()
    const signals: (AbortSignal | undefined)[] = []
    const { transport, signRequests } = signedTransport({
      onPut: (partNumber) => {
        if (partNumber === 1) {
          controller.abort()
          throw controller.signal.reason
        }
      },
    })
    const recording: UploadPartTransport = {
      ...transport,
      async putPart(part, url, body, signal) {
        signals.push(signal)
        return transport.putPart(part, url, body, signal)
      },
    }

    const caught = await runUploadParts({
      file,
      parts: planUploadParts(file.size, 2),
      signatures: ["c2lnLTE=", "c2lnLTI="],
      transport: recording,
      signal: controller.signal,
      wait: async () => {},
    }).then(
      () => null,
      (error: unknown) => error
    )

    expect(caught).not.toBeNull()
    expect(String(caught)).toContain("AbortError")
    expect(caught instanceof UploadPartError).toBe(false)
    expect(signals[0]).toBe(controller.signal)
    expect(signRequests).toHaveLength(1)
  })

  it("stops before signing when the signal is already aborted", async () => {
    const controller = new AbortController()
    controller.abort()
    const { transport, signRequests } = signedTransport()

    await expect(
      runUploadParts({
        file: new Blob(["ab"]),
        parts: planUploadParts(2, 1),
        signatures: ["c2ln", "c2ln"],
        transport,
        signal: controller.signal,
        wait: async () => {},
      })
    ).rejects.toThrow()
    expect(signRequests).toEqual([])
  })
})
