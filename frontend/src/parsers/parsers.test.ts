import { existsSync, openAsBlob, readdirSync } from "node:fs"
import { join } from "node:path"
import { describe, expect, it } from "vitest"

import { readBrukerPrimaryEnergy } from "./bruker_edx"
import { feiFormFields, readFeiTiffMetadata } from "./fei_tiff"
import { readNgsFields } from "./horiba_ngs"

// Real instrument files live in crucible-ingestion's test data (also gs://crucible-ingestion-test-data).
const DATA = process.env.INGESTION_TEST_DATA ?? join(process.env.HOME ?? "", "Github_repos/crucible-ingestion/tests/data")
const RAMAN = join(DATA, "B30_Raman")
const have = (path: string) => existsSync(path)

describe("readNgsFields", () => {
  const files = have(RAMAN) ? readdirSync(RAMAN).filter((f) => f.endsWith(".ngs")) : []

  it.skipIf(!files.length)("reads the acquisition settings of every real LabRAM spectrum", async () => {
    expect(files.length).toBe(7)
    for (const name of files) {
      const fields = await readNgsFields(await openAsBlob(join(RAMAN, name)))
      expect(fields, name).toEqual({
        laser_wavelength_nm: 532.06,
        exposure_time_s: 60,
        accumulation: "1 x 9",
        grating: "1800",
        objective: "x50",
        raman_shift_range: [150, 1500],
      })
    }
  })

  it.skipIf(!files.length)("keeps the table values when the spectrum block is cut off", async () => {
    const bytes = new Uint8Array(await (await openAsBlob(join(RAMAN, files[0]))).arrayBuffer())
    const damaged = bytes.slice()
    damaged.fill(0, 60, 400) // wipe the spectrum header
    const fields = await readNgsFields(new Blob([damaged]))
    expect(fields?.laser_wavelength_nm).toBe(532.06)
    expect(fields?.raman_shift_range).toBeUndefined()
  })

  it("returns null for other files", async () => {
    expect(await readNgsFields(new Blob(["not a LabSpec file"]))).toBeNull()
    expect(await readNgsFields(new Blob(["NGSNextGen"]))).toBeNull()
  })
})

describe("FEI TIFF autofill", () => {
  const tif = join(DATA, "tmpewufz11q.tif")

  it.skipIf(!have(tif))("matches the FeiSemTifIngestor mapping on the real B30 TIFF", async () => {
    const md = await readFeiTiffMetadata(await openAsBlob(tif))
    const fields = feiFormFields(md!)
    expect(fields).toMatchObject({ vacuum_level: "High", spot_size: "3", high_voltage_V: "10000", emission_current_A: "0.000154675" })
    expect(Number(fields.chamber_pressure_Torr)).toBeCloseTo(4.4047e-6, 9)
  })

  it("returns null for non-TIFF data", async () => {
    expect(await readFeiTiffMetadata(new Blob(["hello"]))).toBeNull()
  })
})

describe("readBrukerPrimaryEnergy", () => {
  const exports = ["EDX_SiN-TiA-CFO_window3.spx", "EDX_spectra_data_evaluation.rtx"].map((f) => join(DATA, f))

  it.skipIf(!exports.every(have))("reads 10 keV from the real Esprit exports", async () => {
    for (const path of exports) expect(await readBrukerPrimaryEnergy(await openAsBlob(path))).toBe(10)
  })

  it("returns null when there is no PrimaryEnergy", async () => {
    expect(await readBrukerPrimaryEnergy(new Blob(["<TRTSpectrum></TRTSpectrum>"]))).toBeNull()
  })
})
