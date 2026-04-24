import React, { useEffect, useState } from "react";
import axios from "axios";
import { API } from "../config";

const defaultData = {
  summary: {
    uploaded_documents: 0,
    total_chunks: 0,
    questions_answered: 0,
    average_confidence: 0,
    average_ragas_score: 0,
    quiz_attempts: 0,
    average_quiz_score: 0,
  },
  recent_uploads: [],
  recent_chats: [],
  recent_quiz_attempts: [],
};

function Dashboard({ refreshKey }) {
  const [data, setData] = useState(defaultData);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadDashboard = async () => {
      setLoading(true);
      try {
        const response = await axios.get(`${API}/dashboard`);
        setData(response.data);
      } catch (err) {
        setData(defaultData);
      } finally {
        setLoading(false);
      }
    };

    loadDashboard();
  }, [refreshKey]);

  const cards = [
    { label: "Documents", value: data.summary.uploaded_documents },
    { label: "Indexed Chunks", value: data.summary.total_chunks },
    { label: "Questions Answered", value: data.summary.questions_answered },
    { label: "Avg Confidence", value: `${data.summary.average_confidence}%` },
    { label: "Avg RAGAS Score", value: data.summary.average_ragas_score },
    { label: "Avg Quiz Score", value: `${data.summary.average_quiz_score}%` },
  ];

  return (
    <section className="dashboard-panel">
      <div className="dashboard-heading">
        <div>
          <p className="section-tag">Dashboard</p>
          <h2>Workspace overview</h2>
        </div>
        {loading && <div className="dashboard-loading">Refreshing data...</div>}
      </div>

      <div className="metric-grid">
        {cards.map((card) => (
          <div className="metric-card" key={card.label}>
            <span>{card.label}</span>
            <strong>{card.value}</strong>
          </div>
        ))}
      </div>

      <div className="dashboard-grid">
        <div className="panel">
          <div className="panel-header compact">
            <div>
              <p className="section-tag">Uploads</p>
              <h3>Uploaded materials</h3>
            </div>
          </div>
          {data.recent_uploads.length === 0 && <p className="muted-text">No uploads yet.</p>}
          {data.recent_uploads.map((item, index) => (
            <div className="dashboard-list-item" key={`${item.filename}-${index}`}>
              <strong>{item.filename}</strong>
              <span>{item.chunks} chunks indexed</span>
            </div>
          ))}
        </div>

        <div className="panel">
          <div className="panel-header compact">
            <div>
              <p className="section-tag">Quiz Scores</p>
              <h3>Quiz performance</h3>
            </div>
          </div>
          {data.recent_quiz_attempts.length === 0 && (
            <p className="muted-text">No quiz attempts yet.</p>
          )}
          {data.recent_quiz_attempts.map((attempt, index) => (
            <div className="dashboard-list-item" key={`${attempt.topic}-${index}`}>
              <strong>{attempt.topic}</strong>
              <span>
                {attempt.score}/{attempt.total} ({attempt.percentage}%)
              </span>
            </div>
          ))}
        </div>

        <div className="panel span-two">
          <div className="panel-header compact">
            <div>
              <p className="section-tag">Answer Quality</p>
              <h3>Recent tutor answers</h3>
            </div>
          </div>
          {data.recent_chats.length === 0 && (
            <p className="muted-text">No chat activity yet.</p>
          )}
          {data.recent_chats.map((chat, index) => (
            <div className="dashboard-list-item wide" key={`${chat.question}-${index}`}>
              <div>
                <strong>{chat.question}</strong>
                <p>{chat.answer_preview}</p>
              </div>
              <div className="chat-stats">
                <span>Confidence: {chat.confidence}%</span>
                <span>RAGAS: {chat.evaluation?.score ?? 0}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export default Dashboard;
