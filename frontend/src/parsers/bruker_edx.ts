// Primary energy from a Bruker Esprit .spx/.rtx export for the B30 SEM form (moved from b30_sem.js).

export async function readBrukerPrimaryEnergy(file: Blob): Promise<number | null> {
    const CHUNK = 4 * 1024 * 1024;
    const OVERLAP = 256;
    const decoder = new TextDecoder('windows-1252');
    const pattern = /<PrimaryEnergy>\s*([^<\s]+)\s*<\/PrimaryEnergy>/;
    for (let offset = 0; offset < file.size; offset += CHUNK) {
        const start = Math.max(0, offset - OVERLAP);
        const text = decoder.decode(await file.slice(start, offset + CHUNK).arrayBuffer());
        const match = pattern.exec(text);
        if (match) {
            const keV = Number(match[1]);
            return Number.isFinite(keV) ? keV : null;
        }
    }
    return null;
}