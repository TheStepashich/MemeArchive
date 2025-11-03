import chromadb
from chromadb.config import Settings
from typing import List, Optional, Dict, Any
import os


class ChromaDBController:
    """
    Контроллер для управления коллекцией в ChromaDB.
    Использует get_or_create_collection и upsert для идемпотентности.
    Поддерживает сохранение на диск.
    """

    def __init__(
        self,
        collection_name: str,
        persist_directory: Optional[str] = None,
    ) -> None:
        """
        Инициализирует клиент Chroma и коллекцию.

        :param collection_name: Имя коллекции.
        :param persist_directory: Путь для сохранения БД. Если None — in-memory.
        """
        self.collection_name = collection_name

        settings = Settings(anonymized_telemetry=False)

        if persist_directory:
            os.makedirs(persist_directory, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=persist_directory,
                settings=settings
            )
        else:
            self._client = chromadb.Client(settings=settings)

        # Идемпотентное создание коллекции
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )

    def add(
        self,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """
        Добавляет или обновляет документы в коллекции (upsert).

        :param ids: Уникальные идентификаторы.
        :param embeddings: Эмбеддинги (векторы).
        :param documents: Исходные тексты.
        :param metadatas: Метаданные (опционально).
        """
        if not (len(ids) == len(embeddings) == len(documents)):
            raise ValueError("Длины ids, embeddings и documents должны совпадать.")

        self._collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas or [{} for _ in ids],
        )

    def search(
        self,
        query_embedding: List[float],
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Выполняет поиск по эмбеддингу.

        :param query_embedding: Эмбеддинг запроса.
        :param n_results: Число результатов.
        :param where: Фильтр по метаданным.
        :return: Словарь с ключами: ids, distances, metadatas, documents.
        """
        results = self._collection.query(
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

    def count(self) -> int:
        """Возвращает количество документов в коллекции."""
        return self._collection.count()

    def delete(self, ids: List[str]) -> None:
        """Удаляет документы по ID."""
        self._collection.delete(ids=ids)

    def __repr__(self) -> str:
        return f"ChromaDBController(collection='{self.collection_name}', count={self.count()})"