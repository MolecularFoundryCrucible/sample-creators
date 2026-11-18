import { createSHA256 } from "hash-wasm"

const CHUNK_SIZE = 4 * 1024 * 1024 // 4 MiB

/**
 * Computes the SHA-256 hexadecimal digest of a Blob or File in 4 MiB chunks.
 */
export async function computeBlobSha256(blob: Blob): Promise<string> {
  const hasher = await createSHA256()
  hasher.init()
  let offset = 0
  while (offset < blob.size) {
    const slice = blob.slice(offset, Math.min(offset + CHUNK_SIZE, blob.size))
    const buf = await slice.arrayBuffer()
    hasher.update(new Uint8Array(buf))
    offset += CHUNK_SIZE
  }
  return hasher.digest("hex")
}
