// File parsers for the instrument pages' live autofill, exposed to their plain-JS page scripts.
import { readBrukerPrimaryEnergy } from "./bruker_edx"
import { feiFormFields, readFeiTiffMetadata } from "./fei_tiff"
import {
  applyDatasetFieldEdits,
  applyMetadataEdits,
  buildDatasetFormDescriptor,
  buildFormDescriptor,
  DATASET_FORM_FIELDS,
  DATASET_FORM_KEYS,
  foldIntoPacket,
  HIDDEN_FIELDS,
  isMissing,
  LOCKED_FIELDS,
  otherDatasetFields,
  parseBiologicMptBytes,
  parseFilesForPreview,
  parseGcLogText,
} from "./gc_ec"
import type { Collision, FormFieldDescriptor, ParsedPacket, PreviewableFile } from "./gc_ec"
import {
  decodeH5Attr,
  detectNirvanaIngestor,
  readH5EmbeddedInfo,
  readNirvanaH5Positions,
} from "./h5_tools"
import type { H5EmbeddedInfo, NirvanaPosition } from "./h5_tools"
import { readNgsFields } from "./horiba_ngs"
import { readKalFields } from "./kratos_xps"
import type { KalFormFields } from "./kratos_xps"
import { parseXrdText, readXrdFile } from "./inorganic_xrd"
import type { XrdSampleAssignment } from "./inorganic_xrd"
import { computeBlobSha256 } from "./sha256"
import {
  filesToSessionInputs,
  MAX_FILE_BYTES,
  planTemSessionUploads,
  TEM_ACCEPTABLE_EXTENSIONS,
} from "./tem_session"
import type {
  PlanTemSessionOptions,
  SessionFileInput,
  TemSessionItem,
  TemSessionPlan,
} from "./tem_session"

export {
  readBrukerPrimaryEnergy,
  feiFormFields,
  readFeiTiffMetadata,
  readNgsFields,
  readKalFields,
  computeBlobSha256,
  parseGcLogText,
  parseBiologicMptBytes,
  parseFilesForPreview,
  buildFormDescriptor,
  buildDatasetFormDescriptor,
  otherDatasetFields,
  applyMetadataEdits,
  applyDatasetFieldEdits,
  foldIntoPacket,
  isMissing,
  LOCKED_FIELDS,
  HIDDEN_FIELDS,
  DATASET_FORM_FIELDS,
  DATASET_FORM_KEYS,
  parseXrdText,
  readXrdFile,
  decodeH5Attr,
  detectNirvanaIngestor,
  readNirvanaH5Positions,
  readH5EmbeddedInfo,
  TEM_ACCEPTABLE_EXTENSIONS,
  MAX_FILE_BYTES,
  filesToSessionInputs,
  planTemSessionUploads,
}

export type {
  ParsedPacket,
  Collision,
  FormFieldDescriptor,
  PreviewableFile,
  XrdSampleAssignment,
  NirvanaPosition,
  H5EmbeddedInfo,
  KalFormFields,
  SessionFileInput,
  PlanTemSessionOptions,
  TemSessionItem,
  TemSessionPlan,
}

const parserBundle = {
  readFeiTiffMetadata,
  feiFormFields,
  readBrukerPrimaryEnergy,
  readNgsFields,
  readKalFields,
  computeBlobSha256,
  parseGcLogText,
  parseBiologicMptBytes,
  parseFilesForPreview,
  buildFormDescriptor,
  buildDatasetFormDescriptor,
  otherDatasetFields,
  applyMetadataEdits,
  applyDatasetFieldEdits,
  foldIntoPacket,
  isMissing,
  parseXrdText,
  readXrdFile,
  decodeH5Attr,
  detectNirvanaIngestor,
  readNirvanaH5Positions,
  readH5EmbeddedInfo,
  TEM_ACCEPTABLE_EXTENSIONS,
  MAX_FILE_BYTES,
  filesToSessionInputs,
  planTemSessionUploads,
}

declare global {
  interface Window {
    InstrumentParsers?: typeof parserBundle
  }
}

if (typeof window !== "undefined") {
  window.InstrumentParsers = parserBundle
}
