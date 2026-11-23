import { createSHA256 } from "hash-wasm"

const CHUNK_SIZE = 4 * 1024 * 1024 // 4 MiB
const PROGRESS_INTERVAL_MS = 150

/**
 * Computes the SHA-256 hexadecimal digest of a Blob or File in 4 MiB chunks.
 */
export async function computeBlobSha256(
  blob: Blob,
  onProgress?: (hashedBytes: number, totalBytes: number) => void,
  signal?: AbortSignal
): Promise<string> {
  signal?.throwIfAborted()
  const hasher = await createSHA256()
  signal?.throwIfAborted()
  hasher.init()
  onProgress?.(0, blob.size)
  signal?.throwIfAborted()
  let offset = 0
  let lastReport = performance.now()
  while (offset < blob.size) {
    signal?.throwIfAborted()
    const nextOffset = Math.min(offset + CHUNK_SIZE, blob.size)
    const slice = blob.slice(offset, nextOffset)
    const buf = await slice.arrayBuffer()
    signal?.throwIfAborted()
    hasher.update(new Uint8Array(buf))
    offset = nextOffset
    const now = performance.now()
    if (offset >= blob.size || now - lastReport >= PROGRESS_INTERVAL_MS) {
      onProgress?.(offset, blob.size)
      signal?.throwIfAborted()
      lastReport = now
    }
  }
  signal?.throwIfAborted()
  return hasher.digest("hex")
}
