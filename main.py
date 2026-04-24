from datetime import datetime
from pathlib import Path
from typing import Any
import json
import os
import pickle
import shutil
import tempfile

import chromadb
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from groq import Groq
from pydantic import BaseModel
from sentence_transformers import CrossEncoder, SentenceTransformer
from sklearn.feature_extraction.text import HashingVectorizer

from ingestion import ingest

load_dotenv()

app = FastAPI(title="Gen AI Tutor")

BASE_DIR = Path(__file__).resolve().parent
BM25_PATH = BASE_DIR / "bm25.pkl"
METRICS_PATH = BASE_DIR / "runtime_metrics.json"

chat_memory: dict[str, list[dict[str, str]]] = {}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def create_chroma_client() -> Any:
    try:
        return chromadb.PersistentClient(path=str(BASE_DIR / "chroma_store"))
    except Exception:
        return chromadb.EphemeralClient()


class LocalSentenceEmbedder:
    def __init__(self) -> None:
        self.vectorizer = HashingVectorizer(
            n_features=384,
            alternate_sign=False,
            norm="l2",
        )

    def encode(self, texts: list[str]) -> Any:
        return self.vectorizer.transform(texts).toarray()


class LocalCrossEncoder:
    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        scores = []
        for query, chunk in pairs:
            query_terms = set(query.lower().split())
            chunk_terms = set(chunk.lower().split())
            if not query_terms:
                scores.append(0.0)
                continue
            overlap = len(query_terms & chunk_terms) / len(query_terms)
            scores.append(float(overlap))
        return scores


def load_embedder() -> Any:
    try:
        return SentenceTransformer("all-MiniLM-L6-v2")
    except Exception:
        return LocalSentenceEmbedder()


def load_reranker() -> Any:
    try:
        return CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    except Exception:
        return LocalCrossEncoder()


embed_model = load_embedder()
reranker = load_reranker()
db = create_chroma_client()
collection = db.get_or_create_collection("course_material")


class ChatRequest(BaseModel):
    question: str
    session_id: str


class QuizRequest(BaseModel):
    topic: str


class QuizAttemptRequest(BaseModel):
    topic: str
    session_id: str
    score: int
    total: int
    percentage: float
    section_scores: list[dict[str, Any]]


def utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def default_metrics() -> dict[str, Any]:
    return {
        "uploads": [],
        "quiz_attempts": [],
        "chat_interactions": [],
    }


def load_metrics() -> dict[str, Any]:
    if not METRICS_PATH.exists():
        return default_metrics()

    try:
        return json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default_metrics()


def save_metrics(metrics: dict[str, Any]) -> None:
    METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")


def append_metric(key: str, payload: dict[str, Any]) -> None:
    metrics = load_metrics()
    metrics.setdefault(key, []).append(payload)
    save_metrics(metrics)


def load_bm25() -> tuple[Any, list[dict[str, Any]]]:
    if not BM25_PATH.exists():
        return None, []

    with BM25_PATH.open("rb") as file_obj:
        bm25, corpus = pickle.load(file_obj)

    normalized_corpus: list[dict[str, Any]] = []
    for index, item in enumerate(corpus or []):
        if isinstance(item, dict):
            normalized_corpus.append(
                {
                    "document": item.get("document", ""),
                    "source": item.get("source", "Unknown"),
                    "chunk_index": item.get("chunk_index", index),
                }
            )
        elif isinstance(item, str):
            normalized_corpus.append(
                {
                    "document": item,
                    "source": "Unknown",
                    "chunk_index": index,
                }
            )

    return bm25, normalized_corpus


def normalize_terms(text: str) -> list[str]:
    cleaned = "".join(char.lower() if char.isalnum() or char.isspace() else " " for char in text)
    stopwords = {
        "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
        "is", "are", "was", "were", "be", "by", "from", "at", "as", "that",
        "this", "it", "what", "which", "who", "when", "where", "how",
    }
    return [term for term in cleaned.split() if len(term) > 2 and term not in stopwords]


def topic_supported(topic: str, ranked_chunks: list[tuple[str, float]]) -> bool:
    topic_terms = set(normalize_terms(topic))
    if not topic_terms or not ranked_chunks:
        return False

    strongest_score = ranked_chunks[0][1]
    joined_top_chunks = " ".join(chunk for chunk, _ in ranked_chunks[:3])
    chunk_terms = set(normalize_terms(joined_top_chunks))
    overlap = len(topic_terms & chunk_terms) / max(len(topic_terms), 1)

    return strongest_score >= 0.45 and overlap >= 0.5


def is_follow_up_question(question: str) -> bool:
    follow_up_starters = (
        "it", "its", "they", "them", "that", "those", "this", "these",
        "he", "she", "his", "her", "their", "also", "and", "what about",
        "explain more", "tell me more", "continue", "why", "how about",
    )
    lowered = question.lower().strip()
    return lowered.startswith(follow_up_starters)


def build_effective_question(question: str, history: list[dict[str, str]]) -> str:
    if not history or not is_follow_up_question(question):
        return question

    recent_questions = [item["q"] for item in history[-2:]]
    return " ".join(recent_questions + [question])


def hybrid_retrieve(query: str, n_results: int = 5) -> list[tuple[str, float]]:
    q_emb = embed_model.encode([query])[0].tolist()
    results = collection.query(
        query_embeddings=[q_emb],
        n_results=max(n_results * 2, 8),
        include=["documents", "metadatas"],
    )
    embed_chunks = results["documents"][0] if results["documents"] else []

    bm25_chunks: list[str] = []
    bm25, corpus = load_bm25()
    if bm25 and corpus:
        scores = bm25.get_scores(query.split())
        top_idx = sorted(
            range(len(scores)),
            key=lambda idx: scores[idx],
            reverse=True,
        )[: max(n_results * 2, 8)]
        bm25_chunks = [corpus[idx]["document"] for idx in top_idx if corpus[idx].get("document")]

    all_chunks = list(dict.fromkeys(embed_chunks + bm25_chunks))
    if not all_chunks:
        return []

    pairs = [(query, chunk) for chunk in all_chunks]
    scores = reranker.predict(pairs)
    ranked = sorted(zip(all_chunks, scores), key=lambda item: item[1], reverse=True)
    return [(chunk, float(score)) for chunk, score in ranked]


def evaluate_with_ragas(question: str, answer: str, contexts: list[str]) -> dict[str, Any]:
    evaluation = {
        "framework": "ragas",
        "available": False,
        "score": None,
        "metrics": {},
    }

    if not question or not answer or not contexts:
        evaluation["note"] = "Insufficient data for evaluation."
        return evaluation

    try:
        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import answer_relevancy, faithfulness

        dataset = Dataset.from_dict(
            {
                "question": [question],
                "answer": [answer],
                "contexts": [contexts],
            }
        )

        result = evaluate(dataset=dataset, metrics=[faithfulness, answer_relevancy])
        if hasattr(result, "to_pandas"):
            row = result.to_pandas().iloc[0].to_dict()
        else:
            row = dict(result)

        metrics = {
            "faithfulness": round(float(row.get("faithfulness", 0.0)), 4),
            "answer_relevancy": round(float(row.get("answer_relevancy", 0.0)), 4),
        }
        evaluation["available"] = True
        evaluation["metrics"] = metrics
        evaluation["score"] = round(sum(metrics.values()) / len(metrics), 4)
        return evaluation
    except Exception as exc:
        # Keep the app working even when RAGAS or its providers are not configured.
        grounded_overlap = 0.0
        answer_terms = set(answer.lower().split())
        context_terms = set(" ".join(contexts).lower().split())
        if answer_terms:
            grounded_overlap = len(answer_terms & context_terms) / len(answer_terms)

        evaluation["note"] = f"RAGAS fallback used: {exc}"
        evaluation["metrics"] = {
            "grounded_overlap": round(grounded_overlap, 4),
        }
        evaluation["score"] = round(grounded_overlap, 4)
        return evaluation


def build_history_text(history: list[dict[str, str]]) -> str:
    return "\n".join([f"User: {item['q']}\nAI: {item['a']}" for item in history])


def build_dashboard_payload() -> dict[str, Any]:
    metrics = load_metrics()
    uploads = metrics.get("uploads", [])
    chats = metrics.get("chat_interactions", [])
    quiz_attempts = metrics.get("quiz_attempts", [])

    avg_confidence = round(
        sum(item.get("confidence", 0) for item in chats) / len(chats), 2
    ) if chats else 0.0
    avg_ragas = round(
        sum(item.get("evaluation", {}).get("score", 0) or 0 for item in chats) / len(chats), 4
    ) if chats else 0.0
    avg_quiz = round(
        sum(item.get("percentage", 0) for item in quiz_attempts) / len(quiz_attempts), 2
    ) if quiz_attempts else 0.0

    recent_quiz_attempts = list(reversed(quiz_attempts[-5:]))
    recent_chats = list(reversed(chats[-5:]))

    return {
        "summary": {
            "uploaded_documents": len(uploads),
            "total_chunks": int(collection.count()),
            "questions_answered": len(chats),
            "average_confidence": avg_confidence,
            "average_ragas_score": avg_ragas,
            "quiz_attempts": len(quiz_attempts),
            "average_quiz_score": avg_quiz,
        },
        "recent_uploads": list(reversed(uploads[-5:])),
        "recent_chats": recent_chats,
        "recent_quiz_attempts": recent_quiz_attempts,
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/dashboard")
async def dashboard() -> dict[str, Any]:
    return build_dashboard_payload()


@app.post("/upload")
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        shutil.copyfileobj(file.file, tmp)
        temp_path = tmp.name

    try:
        ingestion_result = ingest(temp_path, original_filename=file.filename)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    append_metric(
        "uploads",
        {
            "filename": file.filename,
            "chunks": ingestion_result["chunks"],
            "uploaded_at": utc_now(),
        },
    )

    return {
        "message": "Uploaded successfully",
        "chunks": ingestion_result["chunks"],
        "total_chunks": ingestion_result.get("total_chunks", ingestion_result["chunks"]),
    }


@app.post("/chat")
async def chat(req: ChatRequest) -> dict[str, Any]:
    question = req.question.strip()
    session_id = req.session_id.strip() or "default_user"

    if session_id not in chat_memory:
        chat_memory[session_id] = []

    history = chat_memory[session_id]
    history_text = build_history_text(history)
    effective_question = build_effective_question(question, history)
    ranked = hybrid_retrieve(effective_question, n_results=5)

    if not ranked or not topic_supported(effective_question, ranked):
        return {
            "answer": "This question is not present in the uploaded document.",
            "confidence": 0,
            "sources": [],
            "evaluation": {
                "framework": "ragas",
                "available": False,
                "score": 0,
                "metrics": {},
                "note": "The uploaded PDF does not contain enough support for this question.",
            },
        }

    top_score = ranked[0][1]
    if top_score < 0.3:
        return {
            "answer": "This topic is not covered in your uploaded material.",
            "confidence": 0,
            "sources": [],
            "evaluation": {
                "framework": "ragas",
                "available": False,
                "score": 0,
                "metrics": {},
                "note": "Retrieved content did not pass the relevance threshold.",
            },
        }

    final_chunks = [chunk for chunk, _ in ranked[:3]]
    context = "\n".join(final_chunks)
    prompt = f"""
You are an AI tutor.

Use the conversation history when it is helpful, but answer only from the provided study material.
If the answer is not supported by the context, clearly say that it is not covered.

History:
{history_text}

Context:
{context}

Question:
{question}
"""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )

    answer = response.choices[0].message.content
    confidence = round(max(0.0, min(top_score, 1.0)) * 100, 2)
    evaluation = evaluate_with_ragas(question, answer, final_chunks)

    history.append({"q": question, "a": answer})
    chat_memory[session_id] = history[-5:]

    append_metric(
        "chat_interactions",
        {
            "session_id": session_id,
            "question": question,
            "effective_question": effective_question,
            "answer_preview": answer[:180],
            "confidence": confidence,
            "evaluation": evaluation,
            "asked_at": utc_now(),
        },
    )

    return {
        "answer": answer,
        "confidence": confidence,
        "sources": final_chunks,
        "evaluation": evaluation,
        "session_id": session_id,
    }


@app.post("/chat-stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    question = req.question.strip()
    session_id = req.session_id.strip() or "default_user"

    if session_id not in chat_memory:
        chat_memory[session_id] = []

    history = chat_memory[session_id]
    history_text = build_history_text(history)
    effective_question = build_effective_question(question, history)
    ranked = hybrid_retrieve(effective_question, n_results=3)

    if not ranked or not topic_supported(effective_question, ranked):
        def unsupported():
            yield "This question is not present in the uploaded document."

        return StreamingResponse(unsupported(), media_type="text/plain")

    final_chunks = [chunk for chunk, _ in ranked[:3]]
    context = "\n".join(final_chunks)

    prompt = f"""
You are an AI tutor.

History:
{history_text}

Context:
{context}

Question:
{question}
"""

    def generate():
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            stream=True,
        )

        full_answer = ""
        for chunk in response:
            if chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
                full_answer += text
                yield text

        history.append({"q": question, "a": full_answer})
        chat_memory[session_id] = history[-5:]

    return StreamingResponse(generate(), media_type="text/plain")


@app.post("/quiz")
async def quiz(req: QuizRequest) -> dict[str, Any]:
    topic = req.topic.strip()
    ranked = hybrid_retrieve(topic, n_results=5)
    chunks = [chunk for chunk, _ in ranked[:5]]

    if not chunks or not topic_supported(topic, ranked):
        return {
            "quiz": [],
            "error": "Topic not found in uploaded material",
        }

    context = "\n".join(chunks[:3])
    prompt = f"""
You are an AI tutor.

STRICT RULES:
- Generate the quiz only from the provided context.
- If the topic is not supported by the context, return EXACTLY: NO_QUIZ
- Return valid JSON only.
- Do not use outside knowledge.
- Do not switch to a related topic such as deep learning, neural networks, transformers, or NLP unless the exact topic is clearly present in the context.

Topic:
{topic}

Context:
{context}

Return this exact structure:
[
  {{
    "section": "Concept Check",
    "questions": [
      {{
        "question": "...",
        "options": ["A", "B", "C", "D"],
        "answer": "A"
      }}
    ]
  }},
  {{
    "section": "Applied Understanding",
    "questions": [
      {{
        "question": "...",
        "options": ["A", "B", "C", "D"],
        "answer": "A"
      }}
    ]
  }},
  {{
    "section": "Challenge Round",
    "questions": [
      {{
        "question": "...",
        "options": ["A", "B", "C", "D"],
        "answer": "A"
      }}
    ]
  }}
]

Each section must contain exactly 2 multiple-choice questions.
Set the answer value to the full correct option text from the options array.
"""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )

    text = response.choices[0].message.content.strip()
    if "NO_QUIZ" in text:
        return {
            "quiz": [],
            "error": "Topic not found in uploaded material",
        }

    try:
        quiz_data = json.loads(text)
    except json.JSONDecodeError:
        return {
            "quiz": [],
            "error": "Failed to generate quiz",
        }

    if isinstance(quiz_data, list) and quiz_data and "questions" not in quiz_data[0]:
        quiz_data = [{"section": "Practice Quiz", "questions": quiz_data}]

    return {
        "quiz": quiz_data,
        "error": None,
    }


@app.post("/quiz/submit")
async def submit_quiz(req: QuizAttemptRequest) -> dict[str, Any]:
    attempt = {
        "topic": req.topic,
        "session_id": req.session_id,
        "score": req.score,
        "total": req.total,
        "percentage": req.percentage,
        "section_scores": req.section_scores,
        "submitted_at": utc_now(),
    }
    append_metric("quiz_attempts", attempt)
    return {"message": "Quiz score saved", "attempt": attempt}
