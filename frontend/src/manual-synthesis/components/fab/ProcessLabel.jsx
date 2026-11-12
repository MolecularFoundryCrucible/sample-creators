// Copied from manual-synthesis-ui frontend/src/components/fab/ProcessLabel.jsx at c25ae5c.
import { useState, useEffect, useMemo, useRef } from 'react';
import QRCode from 'qrcode';

// Follows the team's label_printer conventions: one section per process,
// separated by a dashed line, each with its own notes; "Name, unit: value".
const DEFAULT_SECTIONS = ['wafer', 'ebeam_evaporation', 'sputtering'];
const DEFAULT_FIELDS = {
  wafer: ['substrate_name', 'date', 'material_name'],
  ebeam_evaporation: ['process', 'date', 'deposit_thickness_a', 'stabilize_rate_a_s'],
  sputtering: ['process', 'date', 'deposition_deposition_temp_c', 'deposition_target_output_pct',
    'deposition_calibrated_rate_a_s', 'deposition_thickness_nm'],
};
const DEFAULT_STEP_FIELDS = ['process', 'date'];

const LABEL_STYLE =
  'body{margin:0}#label-print{width:6cm;font-size:12px;font-family:Times New Roman,serif;padding:5px;' +
  'border:2px solid black;background:white;overflow-wrap:break-word;overflow:hidden}#label-print p{margin:0}' +
  '.process{border-bottom:1px dashed black;margin-bottom:5px;padding-bottom:5px}' +
  '.process:last-child{border-bottom:none;margin-bottom:0;padding-bottom:0}' +
  '.label-qr{float:right;width:1.6cm;height:1.6cm;margin-left:4px}.label-notes{white-space:pre-wrap}';

const escapeHtml = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// Same vocabulary label_printer applies to its "Material name" column.
const abbreviateMaterial = (name) => String(name)
  .replace(/Titanium/g, 'Ti')
  .replace(/Tungsten/g, 'W')
  .replace(/Hafnium/g, 'Hf')
  .replace(/Silicon/g, 'Si')
  .replace(/Niobium/g, 'Nb')
  .replace(/ Nitride/g, 'N')
  .replace(/Gold/g, 'Au')
  .replace(/Aluminum/g, 'Al');

const present = (v) => v !== undefined && v !== null && v !== '';

const buildSections = (traveler) => {
  const { wafer, wafer_options: options, spec, spec_record: specRecord, steps } = traveler;
  const sections = [{
    id: 'wafer',
    title: 'Wafer',
    fields: [
      { id: 'substrate_name', label: 'Substrate name', value: wafer.sample_name },
      { id: 'date', label: 'Date', value: specRecord?.step_date },
      { id: 'material_name', label: 'Material name', value: present(spec.base_metal) ? abbreviateMaterial(spec.base_metal) : null },
      { id: 'substrate_material', label: 'Substrate material', value: spec.substrate_material },
      { id: 'substrate_spec', label: 'Substrate specification', value: spec.substrate_spec },
      { id: 'batch_number', label: 'Batch number', value: spec.batch_number },
      { id: 'wafer_type', label: 'Wafer type', value: options.wafer_type },
    ],
  }];
  steps.forEach((step) => {
    const done = step.records.filter((r) => r.status === 'done');
    const last = done[done.length - 1];
    if (!last) return;
    // Prefix the sub-step name only when several rows have fields, e.g. "Deposit Thickness, A".
    const multiRow = step.rows.filter((r) => r.fields.length).length > 1;
    sections.push({
      id: step.id,
      title: `${step.label} ${step.name}`,
      fields: [
        { id: 'process', label: 'Process', value: `${step.label} ${step.name}` },
        { id: 'date', label: 'Date', value: last.step_date },
        ...step.rows.flatMap((r) => r.fields.map((f) => {
          const name = multiRow ? `${r.process} ${f.label}` : f.label;
          return {
            id: `${r.key}_${f.key}`,
            label: f.unit ? `${name}, ${f.unit}` : name,
            value: last.values?.[`${r.key}_${f.key}`],
          };
        })),
      ],
    });
  });
  return sections.map((s) => ({ ...s, fields: s.fields.filter((f) => present(f.value)) }));
};

const ProcessLabel = ({ traveler, onClose }) => {
  const sections = useMemo(() => buildSections(traveler), [traveler]);
  const [included, setIncluded] = useState(
    () => new Set(sections.filter((s) => DEFAULT_SECTIONS.includes(s.id)).map((s) => s.id))
  );
  const [checked, setChecked] = useState(() => new Set(sections.flatMap((s) =>
    (DEFAULT_FIELDS[s.id] || DEFAULT_STEP_FIELDS).map((f) => `${s.id}.${f}`))));
  const [notes, setNotes] = useState({});
  const [showQr, setShowQr] = useState(true);
  const [qrSrc, setQrSrc] = useState('');
  const [toast, setToast] = useState('');
  const labelRef = useRef(null);

  useEffect(() => {
    QRCode.toDataURL(traveler.wafer.explorer_url, { margin: 0, width: 160 }).then(setQrSrc);
  }, [traveler.wafer.explorer_url]);

  const toggleIn = (setter, id) =>
    setter((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  // label_printer skips sections with nothing to show.
  const shown = sections
    .filter((s) => included.has(s.id))
    .map((s) => ({
      ...s,
      lines: s.fields.filter((f) => checked.has(`${s.id}.${f.id}`)),
      note: (notes[s.id] || '').trim(),
    }))
    .filter((s) => s.lines.length || s.note);

  // Print from a hidden iframe holding only the label: its load event fires
  // reliably (unlike a document.write'd pop-up, whose print() Chrome can defer
  // forever) and only the label ends up on the page.
  const print = () => {
    const frame = document.createElement('iframe');
    frame.setAttribute('aria-hidden', 'true');
    frame.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;';
    // innerHTML of the React-rendered preview is already escaped.
    frame.srcdoc = `<!doctype html><html><head><title>${escapeHtml(traveler.wafer.sample_name)}</title>` +
      `<style>${LABEL_STYLE}</style></head><body><div id="label-print">${labelRef.current.innerHTML}</div></body></html>`;
    frame.onload = () => {
      const win = frame.contentWindow;
      win.addEventListener('afterprint', () => frame.remove(), { once: true });
      win.focus();
      win.print();
      setTimeout(() => frame.isConnected && frame.remove(), 60000);
    };
    document.body.appendChild(frame);
  };

  const capture = async () => {
    const { default: html2canvas } = await import('html2canvas');
    return html2canvas(labelRef.current, { scale: 3, backgroundColor: '#ffffff' });
  };

  const saveImage = async () => {
    const canvas = await capture();
    const link = document.createElement('a');
    link.href = canvas.toDataURL('image/png');
    link.download = `${traveler.wafer.sample_name}.png`;
    link.click();
  };

  const copyImage = async () => {
    const canvas = await capture();
    canvas.toBlob(async (blob) => {
      try {
        await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
        setToast(`Label for "${traveler.wafer.sample_name}" copied to clipboard.`);
      } catch {
        setToast('Failed to copy image to clipboard.');
      }
      setTimeout(() => setToast(''), 2500);
    });
  };

  return (
    <div className="modal-backdrop">
      <div className="modal-panel">
        <div className="traveler-header">
          <h3>Create label</h3>
          <button className="btn btn-secondary btn-small" onClick={onClose}>Close</button>
        </div>

        <div className="label-layout">
          <div className="label-fields">
            {sections.map((s) => (
              <div key={s.id} className="label-section-picker">
                <label className="confirm-checkbox section-toggle">
                  <input type="checkbox" checked={included.has(s.id)} onChange={() => toggleIn(setIncluded, s.id)} />
                  {s.title}
                </label>
                {included.has(s.id) && s.fields.map((f) => (
                  <label key={f.id} className="confirm-checkbox field-toggle">
                    <input type="checkbox" checked={checked.has(`${s.id}.${f.id}`)}
                           onChange={() => toggleIn(setChecked, `${s.id}.${f.id}`)} />
                    {f.label}
                  </label>
                ))}
              </div>
            ))}
            <label className="confirm-checkbox section-toggle">
              <input type="checkbox" checked={showQr} onChange={() => setShowQr(!showQr)} />
              Crucible QR code
            </label>
          </div>

          <div>
            <div id="label-print" className="label-preview" ref={labelRef}>
              {showQr && qrSrc && <img className="label-qr" src={qrSrc} alt="Crucible QR" />}
              {shown.map((s) => (
                <div key={s.id} className="process">
                  {s.lines.map((f) => <p key={f.id}><b>{f.label}:</b> {f.value}</p>)}
                  {s.note && <div className="label-notes"><b>Note:</b> {s.note}</div>}
                </div>
              ))}
            </div>
            {sections.filter((s) => included.has(s.id)).map((s) => (
              <label key={s.id} className="label-note-field">
                <span className="muted">Notes: {s.title}</span>
                <textarea className="label-notes-input" rows="2" placeholder="Add notes here..."
                          value={notes[s.id] || ''}
                          onChange={(e) => setNotes({ ...notes, [s.id]: e.target.value })} />
              </label>
            ))}
          </div>
        </div>

        <div className="button-group">
          <button className="btn btn-primary" onClick={print}>Print</button>
          <button className="btn btn-secondary" onClick={saveImage}>Save image</button>
          <button className="btn btn-secondary" onClick={copyImage}>Copy image</button>
        </div>
        {toast && <div className="success-box">{toast}</div>}
      </div>
    </div>
  );
};

export default ProcessLabel;
