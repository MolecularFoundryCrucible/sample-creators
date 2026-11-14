// Copied from manual-synthesis-ui frontend/src/components/MainForm.jsx at c25ae5c. Project selection is consolidated into the page's top login panel.
import { useState, useEffect, useRef } from 'react';
import DataTable from './DataTable';
import ValidationReview from './ValidationReview';
import { getSynthesisFields, uploadSynthesisData } from '../services/api';

const selectionKey = (row, field) => `${row}::${field}`;

const MainForm = ({ userInfo, onUploadSuccess }) => {
  const [synthesisCategories, setSynthesisCategories] = useState({});
  const selectedProject = userInfo.selectedProject || userInfo.projects?.[0] || '';
  const [selectedCategory, setSelectedCategory] = useState('');
  const [selectedSynthesisType, setSelectedSynthesisType] = useState('');
  const [tableData, setTableData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [validation, setValidation] = useState(null);
  const [parentSelections, setParentSelections] = useState({});
  const [confirmDuplicates, setConfirmDuplicates] = useState(false);

  const prevProject = useRef(selectedProject);
  useEffect(() => {
    if (prevProject.current !== selectedProject) {
      prevProject.current = selectedProject;
      clearValidation();
      setError('');
    }
  }, [selectedProject]);

  useEffect(() => {
    const fetchFields = async () => {
      try {
        const response = await getSynthesisFields();
        setSynthesisCategories(response.categories);
      } catch (err) {
        console.error('Error fetching synthesis fields:', err);
        setError('Failed to load synthesis fields');
      }
    };

    fetchFields();
  }, []);

  const clearValidation = () => {
    setValidation(null);
    setParentSelections({});
    setConfirmDuplicates(false);
  };

  const handleCategoryChange = (e) => {
    setSelectedCategory(e.target.value);
    setSelectedSynthesisType('');
    setTableData([]);
    setError('');
    clearValidation();
  };

  const handleSynthesisTypeChange = (e) => {
    setSelectedSynthesisType(e.target.value);
    setTableData([]);
    setError('');
    clearValidation();
  };

  const handleUpload = async () => {
    setError('');

    if (!selectedProject) {
      setError('Please select a project');
      return;
    }

    if (!selectedCategory) {
      setError('Please select a synthesis category');
      return;
    }

    if (!selectedSynthesisType) {
      setError('Please select a synthesis type');
      return;
    }

    if (!tableData || tableData.length === 0) {
      setError('Please enter at least one row of data');
      return;
    }

    setLoading(true);

    try {
      const uploadData = {
        email: userInfo.email,
        orcid: userInfo.orcid,
        user_name: userInfo.name,
        project: selectedProject,
        category: selectedCategory,
        synthesis_type: selectedSynthesisType,
        data: tableData,
        parent_selections: Object.entries(parentSelections).map(([key, unique_id]) => {
          const [row, field] = key.split('::');
          return { row: Number(row), field, unique_id };
        }),
        confirm_duplicate_names: confirmDuplicates
      };

      const response = await uploadSynthesisData(uploadData);

      if (response.success) {
        clearValidation();
        onUploadSuccess(response.message, response.summary);
        return;
      }

      const needsReview =
        (response.needs_selection?.length || 0) > 0 ||
        (response.duplicate_names?.length || 0) > 0;

      if (needsReview) {
        setValidation({
          message: response.message,
          needsSelection: response.needs_selection || [],
          unresolvedParents: response.unresolved_parents || [],
          duplicateNames: response.duplicate_names || []
        });
      } else {
        setError(response.message || 'Upload failed');
      }
    } catch (err) {
      console.error('Upload error:', err);
      setError(err.response?.data?.detail || 'An error occurred during upload');
    } finally {
      setLoading(false);
    }
  };

  const handleSelectParent = (row, field, uniqueId) => {
    setParentSelections((prev) => ({ ...prev, [selectionKey(row, field)]: uniqueId }));
  };

  const handleCancel = () => {
    setSelectedCategory('');
    setSelectedSynthesisType('');
    setTableData([]);
    setError('');
    clearValidation();
  };

  const currentCategoryFields = selectedCategory ? synthesisCategories[selectedCategory] || {} : {};
  const currentFields = selectedSynthesisType ? currentCategoryFields[selectedSynthesisType] || [] : [];
  const showTable = selectedSynthesisType && currentFields.length > 0;

  return (
    <div className="main-form">
      <div className="form-section">
        {error && !showTable && (
          <div className="error-message">
            {error}
          </div>
        )}

        {!selectedProject ? (
          <p className="muted">Select a project above to enter synthesis data.</p>
        ) : (
          <>
            <div className="form-row">
              <div className="form-group">
                <label htmlFor="category">Synthesis Category *</label>
                <select
                  id="category"
                  value={selectedCategory}
                  onChange={handleCategoryChange}
                  disabled={loading || validation !== null}
                >
                  <option value="">-- Select a category --</option>
                  {Object.keys(synthesisCategories).map((category) => (
                    <option key={category} value={category}>
                      {category}
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label htmlFor="synthesisType">Synthesis Type *</label>
                <select
                  id="synthesisType"
                  value={selectedSynthesisType}
                  onChange={handleSynthesisTypeChange}
                  disabled={loading || validation !== null || !selectedCategory}
                >
                  <option value="">-- Select synthesis type --</option>
                  {Object.keys(currentCategoryFields).map((type) => (
                    <option key={type} value={type}>
                      {type}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {showTable && (
          <>
            {/* Kept mounted while reviewing so the entered rows survive going back. */}
            <div className="table-section" hidden={validation !== null}>
              <h3>Enter Sample Data</h3>
              <DataTable
                fields={currentFields}
                onChange={setTableData}
                operatorName={userInfo.name}
              />
            </div>

            {error && (
              <div className="error-message">
                {error}
              </div>
            )}

            {validation ? (
              <ValidationReview
                message={validation.message}
                needsSelection={validation.needsSelection}
                unresolvedParents={validation.unresolvedParents}
                duplicateNames={validation.duplicateNames}
                selections={parentSelections}
                onSelect={handleSelectParent}
                confirmDuplicates={confirmDuplicates}
                onConfirmDuplicatesChange={setConfirmDuplicates}
                onSubmit={handleUpload}
                onCancel={clearValidation}
                loading={loading}
              />
            ) : (
              <div className="button-group">
                <button
                  className="btn btn-primary btn-large"
                  onClick={handleUpload}
                  disabled={loading}
                >
                  {loading ? 'Uploading...' : 'Upload Data'}
                </button>
                <button
                  className="btn btn-secondary btn-large"
                  onClick={handleCancel}
                  disabled={loading}
                >
                  Cancel
                </button>
              </div>
            )}
          </>
        )}
          </>
        )}
      </div>
    </div>
  );
};

export default MainForm;
