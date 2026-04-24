import { useEffect, useRef, useState } from "react";
import "./Chat.css";
import { API } from "../config";

export default function Chat({ sessionId, onChatCompleted }) {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const chatEndRef = useRef(null);

  const askQuestion = async () => {
    if (!question.trim() || loading) return;

    const currentQuestion = question.trim();
    const userMsg = { type: "user", text: currentQuestion };
    setMessages((prev) => [...prev, userMsg]);
    setQuestion("");
    setLoading(true);

    try {
      const res = await fetch(`${API}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          question: currentQuestion,
          session_id: sessionId,
        }),
      });

      const data = await res.json();
      const botMsg = {
        type: "bot",
        text: data.answer || "No answer received.",
        confidence: data.confidence || 0,
        sources: data.sources || [],
        evaluation: data.evaluation || null,
      };

      setMessages((prev) => [...prev, botMsg]);
      onChatCompleted?.();
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { type: "bot", text: "Server error. Check whether the backend is running." },
      ]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="section-tag">Ask</p>
          <h2>Ask questions from uploaded material</h2>
        </div>
        <p className="panel-copy">
          Session memory is active for follow-up questions in this chat.
        </p>
      </div>

      <div className="chat-container">
        <div className="chat-box">
          {messages.length === 0 && (
            <div className="empty-chat">
              <h3>Start a tutoring session</h3>
              <p>Ask about definitions, concepts, examples, or exam preparation.</p>
            </div>
          )}

          {messages.map((msg, index) => (
            <div key={index} className={`msg ${msg.type}`}>
              <p>{msg.text}</p>

              {msg.type === "bot" && (
                <div className="message-meta">
                  <small>Confidence: {msg.confidence}%</small>

                  {msg.evaluation && (
                    <div className="eval-card">
                      <span>RAGAS score: {msg.evaluation.score ?? 0}</span>
                      {Object.entries(msg.evaluation.metrics || {}).map(([key, value]) => (
                        <small key={key}>
                          {key.replaceAll("_", " ")}: {value}
                        </small>
                      ))}
                      {msg.evaluation.note && <small>{msg.evaluation.note}</small>}
                    </div>
                  )}

                  {msg.sources?.length > 0 && (
                    <div className="sources">
                      {msg.sources.map((src, i) => (
                        <p key={i}>{src}</p>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}

          {loading && <div className="msg bot loading-pill">Preparing answer...</div>}
          <div ref={chatEndRef} />
        </div>

        <div className="input-box">
          <input
            type="text"
            placeholder="Ask something from your uploaded material..."
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                askQuestion();
              }
            }}
          />
          <button className="primary-button" onClick={askQuestion} disabled={loading}>
            {loading ? "Thinking..." : "Send"}
          </button>
        </div>
      </div>
    </section>
  );
}
