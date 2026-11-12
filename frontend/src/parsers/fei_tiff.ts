// Reads FEI/Thermo SEM settings from a TIFF for the B30 SEM form (moved from b30_sem.js).
// FEI writes them as INI text in TIFF tag 34682 (34680 on older instruments), often at the end
// of a large image; following the TIFF directory reads only a few small slices.

export type FeiMetadata = Record<string, Record<string, string>>

export async function readFeiTiffMetadata(file: Blob): Promise<FeiMetadata | null> {
    const FEI_TAGS = [34682, 34680];
    const bytes = async (start: number, length: number) => new DataView(await file.slice(start, start + length).arrayBuffer());

    const header = await bytes(0, 8);
    if (header.byteLength < 8) return null;
    const order = String.fromCharCode(header.getUint8(0), header.getUint8(1));
    if (order !== 'II' && order !== 'MM') return null;
    const le = order === 'II';
    if (header.getUint16(2, le) !== 42) return null;  // classic TIFF only (not BigTIFF)

    let ifdOffset = header.getUint32(4, le);
    for (let n = 0; ifdOffset > 0 && ifdOffset < file.size && n < 16; n++) {
        const count = (await bytes(ifdOffset, 2)).getUint16(0, le);
        const ifd = await bytes(ifdOffset + 2, count * 12 + 4);
        if (ifd.byteLength < count * 12) return null;
        for (let i = 0; i < count; i++) {
            const entry = i * 12;
            if (!FEI_TAGS.includes(ifd.getUint16(entry, le))) continue;
            const length = ifd.getUint32(entry + 4, le);  // ASCII/BYTE: one byte per value
            const raw = length <= 4
                ? new Uint8Array(ifd.buffer, ifd.byteOffset + entry + 8, length)
                : new Uint8Array((await bytes(ifd.getUint32(entry + 8, le), length)).buffer);
            return parseFeiIni(new TextDecoder('windows-1252').decode(raw));
        }
        ifdOffset = ifd.byteLength >= count * 12 + 4 ? ifd.getUint32(count * 12, le) : 0;
    }
    return null;
}
export function parseFeiIni(text: string): FeiMetadata {
    const sections: FeiMetadata = {};
    let current: Record<string, string> | null = null;
    for (const line of text.split(/\r?\n/)) {
        const header = /^\s*\[([^\]]+)\]\s*$/.exec(line);
        if (header) {
            current = sections[header[1]] = sections[header[1]] || {};
        } else if (current && line.includes('=')) {
            const at = line.indexOf('=');
            current[line.slice(0, at).trim()] = line.slice(at + 1).trim();
        }
    }
    return sections;
}
export function feiFormFields(md: FeiMetadata): Record<string, string> {
    const find = (...pairs: [string, string][]) => {
        for (const [section, key] of pairs) {
            const value = (md[section] || {})[key];
            if (value != null && String(value).trim() !== '') return String(value).trim();
        }
        return null;
    };
    const number = (value: string | null) => {
        const n = Number(value);
        return value !== null && Number.isFinite(n) ? n : null;
    };
    const fields: Record<string, string> = {};

    const mode = find(['Vacuum', 'UserMode']);
    if (mode) {
        const v = mode.toLowerCase();
        fields.vacuum_level = (v.includes('esem') || v.includes('wet') || v.includes('environ')) ? 'ESEM'
            : v.includes('low') ? 'Low' : 'High';
    }
    const spot = number(find(['Beam', 'Spot'], ['EBeam', 'Spot']));
    if (spot !== null) fields.spot_size = String(spot);
    const hv = number(find(['Beam', 'HV'], ['EBeam', 'HV']));
    if (hv !== null) fields.high_voltage_V = String(hv);
    const current = number(find(['EBeam', 'EmissionCurrent']));
    if (current !== null) fields.emission_current_A = String(current);
    const pressurePa = number(find(['Vacuum', 'ChPressure']));  // FEI writes pascals
    if (pressurePa !== null) fields.chamber_pressure_Torr = String(pressurePa * 0.00750062);
    return fields;
}