// Copied from manual-synthesis-ui frontend/src/components/DataTable.jsx at c25ae5c.
import { useState, useEffect, useMemo, useCallback } from 'react';
import { DataGrid } from 'react-data-grid';
import 'react-data-grid/lib/styles.css';

// Simple text editor component
function TextEditor({ row, column, onRowChange, onClose }) {
  return (
    <input
      autoFocus
      className="rdg-text-editor"
      value={row[column.key] ?? ''}
      onChange={(e) => onRowChange({ ...row, [column.key]: e.target.value })}
      onBlur={onClose}
    />
  );
}

const DataTable = ({ fields, onChange, operatorName }) => {
  const [rows, setRows] = useState([]);

  // Get today's date in YYYY-MM-DD format
  const getTodayDate = () => {
    const today = new Date();
    return today.toISOString().split('T')[0];
  };

  useEffect(() => {
    // Initialize with 0 rows when fields change
    if (fields && fields.length > 0) {
      setRows([]);
      onChange([]);
    }
  }, [fields, operatorName]);

  // Create columns in specific order: Sample Name, Operator, Timestamp, other fields, Sample Description
  const columns = useMemo(() => {
    if (!fields || fields.length === 0) return [];

    const operatorColumn = {
      key: 'Operator',
      name: 'Operator',
      resizable: true,
      width: 150,
      renderEditCell: TextEditor,
    };

    const timestampColumn = {
      key: 'Timestamp',
      name: 'Timestamp',
      resizable: true,
      width: 120,
      renderEditCell: TextEditor,
    };

    // Separate Sample Name, Sample Description, and other fields
    const sampleNameField = fields.find(f => f === 'Sample Name');
    const sampleDescField = fields.find(f => f === 'Sample Description');
    const otherFields = fields.filter(f => f !== 'Sample Name' && f !== 'Sample Description');

    const orderedColumns = [];

    // 1. Sample Name (if exists)
    if (sampleNameField) {
      orderedColumns.push({
        key: sampleNameField,
        name: sampleNameField,
        resizable: true,
        width: 150,
        renderEditCell: TextEditor,
      });
    }

    // 2. Operator
    orderedColumns.push(operatorColumn);

    // 3. Timestamp
    orderedColumns.push(timestampColumn);

    // 4. All other fields
    otherFields.forEach(field => {
      orderedColumns.push({
        key: field,
        name: field,
        resizable: true,
        width: 150,
        renderEditCell: TextEditor,
      });
    });

    // 5. Sample Description (if exists)
    if (sampleDescField) {
      orderedColumns.push({
        key: sampleDescField,
        name: sampleDescField,
        resizable: true,
        width: 200,
        renderEditCell: TextEditor,
      });
    }

    return orderedColumns;
  }, [fields]);

  const handleRowsChange = useCallback((newRows) => {
    setRows(newRows);
    // Filter out completely empty rows before passing to parent
    const nonEmptyRows = newRows.filter(row => {
      return fields.some(field => row[field] && String(row[field]).trim() !== '');
    });
    // Remove the id field before passing to parent
    const cleanedRows = nonEmptyRows.map(row => {
      const { id, ...rest } = row;
      return rest;
    });
    onChange(cleanedRows);
  }, [fields, onChange]);

  const handlePaste = useCallback((event) => {
    // While a cell is being edited, its own input should receive the paste
    // (e.g. pasting a single MFID into a cell) instead of this bulk-row
    // paste handler hijacking it into a new row.
    if (event.target && event.target.classList.contains('rdg-text-editor')) {
      return;
    }

    const pastedData = event.clipboardData.getData('text');
    const pastedRows = pastedData.split('\n').filter(row => row.trim());

    if (pastedRows.length === 0) return;

    // Parse pasted data (tab-separated or comma-separated)
    const parsedRows = pastedRows.map(rowString => {
      // Try tab-separated first (typical for spreadsheets)
      const cells = rowString.includes('\t')
        ? rowString.split('\t')
        : rowString.split(',');
      return cells.map(cell => cell.trim());
    });

    // Build the column order to match what's displayed in the table
    // Order: Sample Name, Operator, Timestamp, other fields, Sample Description
    const sampleNameField = fields.find(f => f === 'Sample Name');
    const sampleDescField = fields.find(f => f === 'Sample Description');
    const otherFields = fields.filter(f => f !== 'Sample Name' && f !== 'Sample Description');

    const columnOrder = [];
    if (sampleNameField) columnOrder.push(sampleNameField);
    columnOrder.push('Operator');
    columnOrder.push('Timestamp');
    columnOrder.push(...otherFields);
    if (sampleDescField) columnOrder.push(sampleDescField);

    // Create new rows from pasted data, mapping cells to columns in order
    const newRows = parsedRows.map((cells, idx) => {
      const row = {
        id: `row-${rows.length + idx}`,
        Timestamp: '',
        Operator: operatorName || ''
      };

      // Initialize all fields
      fields.forEach(field => {
        row[field] = '';
      });

      // Map pasted cells to columns based on columnOrder
      cells.forEach((cell, cellIdx) => {
        if (cellIdx < columnOrder.length) {
          const columnKey = columnOrder[cellIdx];
          row[columnKey] = cell;
        }
      });

      return row;
    });

    // Add new rows to existing rows
    setRows(prevRows => [...prevRows, ...newRows]);

    // Update parent
    const allRows = [...rows, ...newRows];
    const nonEmptyRows = allRows.filter(row => {
      return fields.some(field => row[field] && String(row[field]).trim() !== '');
    });
    const cleanedRows = nonEmptyRows.map(row => {
      const { id, ...rest } = row;
      return rest;
    });
    onChange(cleanedRows);

    event.preventDefault();
  }, [fields, rows, operatorName, onChange]);

  const handleAddRow = () => {
    const newRow = {
      id: `row-${rows.length}`,
      Timestamp: '',
      Operator: operatorName || ''
    };
    fields.forEach(field => {
      newRow[field] = '';
    });
    setRows(prevRows => [...prevRows, newRow]);
  };

  const handleRemoveRow = () => {
    if (rows.length > 0) {
      setRows(prevRows => prevRows.slice(0, -1));
      // Update parent with new data
      const newRows = rows.slice(0, -1);
      const nonEmptyRows = newRows.filter(row => {
        return fields.some(field => row[field] && String(row[field]).trim() !== '');
      });
      const cleanedRows = nonEmptyRows.map(row => {
        const { id, ...rest } = row;
        return rest;
      });
      onChange(cleanedRows);
    }
  };

  const handleClearAll = () => {
    const clearedRows = rows.map(row => {
      const newRow = {
        id: row.id,
        Timestamp: '',
        Operator: operatorName || ''
      };
      fields.forEach(field => {
        newRow[field] = '';
      });
      return newRow;
    });
    setRows(clearedRows);
    onChange([]);
  };

  if (!fields || fields.length === 0) {
    return null;
  }

  return (
    <div className="data-table-container">
      <div className="table-controls">
        <button
          type="button"
          className="btn btn-secondary"
          onClick={handleAddRow}
        >
          + Add Row
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={handleRemoveRow}
          disabled={rows.length === 0}
        >
          - Remove Last Row
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={handleClearAll}
        >
          Clear All
        </button>
        <span className="table-info">
          {rows.length} rows | Copy/paste from Excel or Google Sheets supported
        </span>
      </div>

      <div className="data-grid-wrapper" onPaste={handlePaste}>
        <DataGrid
          columns={columns}
          rows={rows}
          onRowsChange={handleRowsChange}
          rowKeyGetter={(row) => row.id}
          className="rdg-light"
          style={{ height: '400px' }}
        />
      </div>
    </div>
  );
};

export default DataTable;
