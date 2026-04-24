import React, { useState } from "react";
import axios from "axios";
import { API } from "../config";

function Upload({ onUploaded }) {
  const [loading, setLoading] = useState(false);
  const [file, setFile] = useState(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const uploadFile = async () => {
    if (!file) {
      setError("Please choose a PDF before uploading.");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);

    setLoading(true);
    setMessage("");
    setError("");

    try {
      const response = await axios.post(`${API}/upload`, formData);
      setMessage(
        `${file.name} uploaded successfully. ${response.data.chunks || 0} new chunks indexed, ${response.data.total_chunks || 0} total searchable chunks across all PDFs.`
      );
      setFile(null);
      onUploaded?.();
    } catch (err) {
      setError(err.response?.data?.detail || "Upload failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="section-tag">Upload</p>
          <h2>Index new study material</h2>
        </div>
        <p className="panel-copy">
          Upload course PDFs to keep your existing retrieval pipeline updated.
        </p>
      </div>

      <div className="upload-grid">
        <label className="upload-dropzone">
          <span>Choose a PDF file</span>
          <input
            type="file"
            accept=".pdf,application/pdf"
            onChange={(event) => setFile(event.target.files?.[0] || null)}
          />
          <strong>{file ? file.name : "No file selected yet"}</strong>
        </label>

        <div className="upload-actions">
          <button className="primary-button" onClick={uploadFile} disabled={loading}>
            {loading ? "Uploading..." : "Upload Material"}
          </button>
          {message && <p className="success-text">{message}</p>}
          {error && <p className="error-text">{error}</p>}
        </div>
      </div>
    </section>
  );
}

export default Upload;
