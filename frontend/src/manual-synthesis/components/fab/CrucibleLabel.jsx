// Copied from manual-synthesis-ui frontend/src/components/fab/CrucibleLabel.jsx at c25ae5c.
import { useState, useEffect } from 'react';
import { listPrinters, printCrucibleLabel } from '../../services/api';

const CrucibleLabel = ({ units }) => {
  const [printers, setPrinters] = useState([]);
  const [printerId, setPrinterId] = useState(localStorage.getItem('fabPrinterId') || '');
  const [sampleId, setSampleId] = useState(units[0]?.unique_id || '');
  const [message, setMessage] = useState(null);
  const [printing, setPrinting] = useState(false);

  useEffect(() => {
    listPrinters()
      .then((res) => setPrinters(res.printers))
      .catch(() => setMessage({ ok: false, text: 'Could not load printers' }));
  }, []);

  const print = async () => {
    setPrinting(true);
    setMessage(null);
    localStorage.setItem('fabPrinterId', printerId);
    try {
      const res = await printCrucibleLabel(printerId, sampleId);
      setMessage({ ok: res.success, text: res.success ? 'Label printed' : res.detail });
    } catch (err) {
      setMessage({ ok: false, text: err.response?.data?.detail || 'Print failed' });
    } finally {
      setPrinting(false);
    }
  };

  return (
    <div className="crucible-label">
      <h4>Crucible QR label</h4>
      <select value={printerId} onChange={(e) => setPrinterId(e.target.value)}>
        <option value="">-- Printer --</option>
        {printers.map((p) => (
          <option key={p.printer_id} value={p.printer_id}>
            {p.printer_id}{p.online ? '' : ' (offline)'}
          </option>
        ))}
      </select>
      <select value={sampleId} onChange={(e) => setSampleId(e.target.value)}>
        {units.map((u) => (
          <option key={u.unique_id} value={u.unique_id}>{u.sample_name} ({u.sample_type})</option>
        ))}
      </select>
      <button className="btn btn-secondary" onClick={print} disabled={!printerId || !sampleId || printing}>
        {printing ? 'Printing...' : 'Print Crucible label'}
      </button>
      {message && <div className={message.ok ? 'success-box' : 'error-message'}>{message.text}</div>}
    </div>
  );
};

export default CrucibleLabel;
