from pathlib import Path
import os
import pickle

import chromadb
import PyPDF2
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import HashingVectorizer
from sentence_transformers import SentenceTransformer

BASE_DIR = Path(__file__).resolve().parent
BM25_PATH = BASE_DIR / "bm25.pkl"


def create_chroma_client():
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

    def encode(self, texts: list[str]):
        return self.vectorizer.transform(texts).toarray()


def load_embedder():
    try:
        return SentenceTransformer("all-MiniLM-L6-v2")
    except Exception:
        return LocalSentenceEmbedder()


model = load_embedder()
db = create_chroma_client()
collection = db.get_or_create_collection("course_material")


def rebuild_bm25_index() -> int:
    data = collection.get(include=["documents", "metadatas"])
    documents = data.get("documents", []) or []
    metadatas = data.get("metadatas", []) or []

    if not documents:
        with BM25_PATH.open("wb") as file_obj:
            pickle.dump((None, []), file_obj)
        return 0

    tokenized = [document.split() for document in documents]
    bm25 = BM25Okapi(tokenized)
    corpus = []
    for index, document in enumerate(documents):
        raw_metadata = metadatas[index] if index < len(metadatas) else {}
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        corpus.append(
            {
                "document": document,
                "source": metadata.get("source", "Unknown"),
                "chunk_index": metadata.get("chunk_index", index),
            }
        )

    with BM25_PATH.open("wb") as file_obj:
        pickle.dump((bm25, corpus), file_obj)

    return len(documents)


def ingest(file_path: str, original_filename: str | None = None) -> dict[str, int]:
    text = ""

    with open(file_path, "rb") as file_obj:
        reader = PyPDF2.PdfReader(file_obj)
        for page in reader.pages:
            page_text = page.extract_text() or ""
            text += page_text + "\n"

    splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=50)
    chunks = [chunk.strip() for chunk in splitter.split_text(text) if chunk.strip()]

    if not chunks:
        return {"chunks": 0}

    embeddings = model.encode(chunks).tolist()
    source_name = original_filename or os.path.basename(file_path)
    ids = [f"{source_name}_{index}" for index in range(len(chunks))]
    metadatas = [{"source": source_name, "chunk_index": index} for index in range(len(chunks))]

    collection.upsert(
        ids=ids,
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    total_chunks = rebuild_bm25_index()

    return {"chunks": len(chunks), "total_chunks": total_chunks}
