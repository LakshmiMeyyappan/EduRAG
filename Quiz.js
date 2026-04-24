import React, { useState } from "react";
import axios from "axios";
import { API } from "../config";

function Quiz({ sessionId, onQuizSubmitted }) {
  const [quizLoading, setQuizLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [topic, setTopic] = useState("");
  const [quizSections, setQuizSections] = useState([]);
  const [answers, setAnswers] = useState({});
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  const generateQuiz = async () => {
    if (!topic.trim()) return;

    setQuizLoading(true);
    setQuizSections([]);
    setAnswers({});
    setResult(null);
    setError("");

    try {
      const res = await axios.post(`${API}/quiz`, { topic: topic.trim() });

      if (res.data.error) {
        setError(res.data.error);
      } else {
        setQuizSections(res.data.quiz || []);
      }
    } catch (err) {
      setError("Error generating quiz");
    } finally {
      setQuizLoading(false);
    }
  };

  const updateAnswer = (key, option) => {
    setAnswers((prev) => ({ ...prev, [key]: option }));
  };

  const submitQuiz = async () => {
    if (!quizSections.length) return;

    let total = 0;
    let score = 0;
    const sectionScores = quizSections.map((section, sectionIndex) => {
      const questions = section.questions || [];
      let sectionCorrect = 0;

      questions.forEach((question, questionIndex) => {
        const key = `${sectionIndex}-${questionIndex}`;
        total += 1;
        if (answers[key] === question.answer) {
          score += 1;
          sectionCorrect += 1;
        }
      });

      const sectionTotal = questions.length;
      const percentage = sectionTotal
        ? Math.round((sectionCorrect / sectionTotal) * 100)
        : 0;

      return {
        section: section.section,
        score: sectionCorrect,
        total: sectionTotal,
        percentage,
      };
    });

    const percentage = total ? Number(((score / total) * 100).toFixed(2)) : 0;
    const nextResult = { score, total, percentage, sectionScores };
    setResult(nextResult);

    setSubmitting(true);
    try {
      await axios.post(`${API}/quiz/submit`, {
        topic: topic.trim(),
        session_id: sessionId,
        score,
        total,
        percentage,
        section_scores: sectionScores,
      });
      onQuizSubmitted?.();
    } catch (err) {
      setError("Quiz scored locally, but saving the score failed.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="section-tag">Quiz</p>
          <h2>Generate section-based quizzes</h2>
        </div>
        <p className="panel-copy">Create clean topic-wise assessments from uploaded study material.</p>
      </div>

      <div className="quiz-toolbar">
        <input
          placeholder="Enter quiz topic..."
          value={topic}
          onChange={(event) => setTopic(event.target.value)}
        />
        <button className="primary-button" onClick={generateQuiz} disabled={quizLoading}>
          {quizLoading ? "Generating..." : "Generate Quiz"}
        </button>
      </div>

      {error && <p className="error-text">{error}</p>}

      {quizSections.map((section, sectionIndex) => (
        <div className="quiz-section" key={`${section.section}-${sectionIndex}`}>
          <div className="quiz-section-header">
            <h3>{section.section}</h3>
            <span className="quiz-section-count">{(section.questions || []).length} questions</span>
          </div>

          {(section.questions || []).map((q, questionIndex) => {
            const key = `${sectionIndex}-${questionIndex}`;
            return (
              <div className="quiz-card" key={key}>
                <div className="quiz-card-header">
                  <span className="question-index">Q{questionIndex + 1}</span>
                  <h4>{q.question}</h4>
                </div>

                <div className="options-grid">
                  {q.options.map((opt, optionIndex) => (
                    <label
                      key={optionIndex}
                      className={`option-card ${answers[key] === opt ? "selected" : ""}`}
                    >
                      <input
                        type="radio"
                        name={`q-${key}`}
                        checked={answers[key] === opt}
                        onChange={() => updateAnswer(key, opt)}
                      />
                      <span className="option-badge">
                        {String.fromCharCode(65 + optionIndex)}
                      </span>
                      <span className="option-text">{opt}</span>
                    </label>
                  ))}
                </div>

                {result && (
                  <p className={answers[key] === q.answer ? "answer correct" : "answer incorrect"}>
                    Correct answer: {q.answer}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      ))}

      {quizSections.length > 0 && (
        <div className="quiz-submit-row">
          <button className="primary-button" onClick={submitQuiz} disabled={submitting}>
            {submitting ? "Saving Score..." : "Submit Quiz"}
          </button>
        </div>
      )}

      {result && (
        <div className="result-card">
          <div>
            <p className="section-tag">Score</p>
            <h3>
              {result.score}/{result.total} ({result.percentage}%)
            </h3>
          </div>

          <div className="score-grid">
            {result.sectionScores.map((section) => (
              <div key={section.section} className="score-chip">
                <strong>{section.section}</strong>
                <span>
                  {section.score}/{section.total} ({section.percentage}%)
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

export default Quiz;
