// Adapted from manual-synthesis-ui frontend/src/services/api.js at c25ae5c: same functions,
// pointed at this app's /synthesis/api and /fabrication/api routes. Login is handled by the
// page (the usual login panel), so the auth calls are gone; step files go through
// CrucibleUpload (browser-direct), so uploadStepFiles is gone too.
import axios from 'axios';

// base.html defines `const BASE_URL` (the app's URL prefix, e.g. /sample-creators).
// eslint-disable-next-line no-undef
const prefix = typeof BASE_URL === 'string' ? BASE_URL : '';

const api = axios.create({
  baseURL: prefix,
  headers: { 'Content-Type': 'application/json' },
});

// ---------- Synthesis ----------

export const getSynthesisFields = async () => (await api.get('/synthesis/api/fields')).data;

export const uploadSynthesisData = async (uploadData) => (await api.post('/synthesis/api/upload', uploadData)).data;

// ---------- Fabrication traveler ----------

export const getFabTemplates = async () => (await api.get('/fabrication/api/templates')).data;

export const listWafers = async (project) =>
  (await api.get('/fabrication/api/wafers', { params: { project } })).data;

export const createWafer = async (body) => (await api.post('/fabrication/api/wafers', body)).data;

export const getTraveler = async (waferId) =>
  (await api.get(`/fabrication/api/wafers/${encodeURIComponent(waferId)}/traveler`)).data;

export const recordStep = async (body) => (await api.post('/fabrication/api/steps', body)).data;

export const getStepRecord = async (datasetId) =>
  (await api.get(`/fabrication/api/steps/${encodeURIComponent(datasetId)}`)).data;

export const editStepRecord = async (datasetId, body) =>
  (await api.put(`/fabrication/api/steps/${encodeURIComponent(datasetId)}`, body)).data;

export const listPrinters = async () => (await api.get('/fabrication/api/printers')).data;

export const printCrucibleLabel = async (printerId, sampleId) =>
  (await api.post('/fabrication/api/print', { printer_id: printerId, sample_id: sampleId })).data;

export default api;
