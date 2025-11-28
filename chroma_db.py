import chromadb
from chromadb.config import Settings
from typing import List, Optional, Dict, Any
import os

from config import CHROMA_DIR

os.makedirs(CHROMA_DIR, exist_ok=True)

chroma_client = chromadb.PersistentClient(
        path=CHROMA_DIR,
        settings=Settings(anonymized_telemetry=False)
    )

chroma_collection = chroma_client.get_or_create_collection(
        name="images",
        metadata={"hnsw:space": "cosine"}
    )

def db_add(ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None):
    if not (len(ids) == len(embeddings) == len(documents)):
        raise ValueError("Длины ids, embeddings и documents должны совпадать.")
    
    chroma_collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas or [{} for _ in ids],
        )
    

def db_search(query_embedding: List[float],
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        results = chroma_collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where,
        )
        return {
            "ids": results["ids"][0],
            "distances": results["distances"][0],
            "metadatas": results["metadatas"][0],
            "documents": results["documents"][0],
        }