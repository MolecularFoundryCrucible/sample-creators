// File parsers for the instrument pages' live autofill, exposed to their plain-JS page scripts.
import { readBrukerPrimaryEnergy } from "./bruker_edx"
import { feiFormFields, readFeiTiffMetadata } from "./fei_tiff"
import { readNgsFields } from "./horiba_ngs"

export { readBrukerPrimaryEnergy, feiFormFields, readFeiTiffMetadata, readNgsFields }

declare global {
  interface Window {
    InstrumentParsers?: {
      readFeiTiffMetadata: typeof readFeiTiffMetadata
      feiFormFields: typeof feiFormFields
      readBrukerPrimaryEnergy: typeof readBrukerPrimaryEnergy
      readNgsFields: typeof readNgsFields
    }
  }
}

if (typeof window !== "undefined") {
  window.InstrumentParsers = { readFeiTiffMetadata, feiFormFields, readBrukerPrimaryEnergy, readNgsFields }
}
