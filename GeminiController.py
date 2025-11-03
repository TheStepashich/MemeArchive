import os
from typing import List, Union
from google import genai
from google.genai import types
import numpy as np

class GeminiController:
    """
    Контроллер для работы с Google Gemini API (новый клиентский интерфейс).
    Поддерживает генерацию описаний изображений и получение текстовых эмбеддингов.
    """

    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash") -> None:
        """
        Инициализирует клиент Gemini.

        :param api_key: Ключ API от Google AI Studio.
        :param model_name: Имя модели для генерации (например, 'gemini-2.5-flash').
        """
        os.environ["GOOGLE_API_KEY"] = api_key
        self._client = genai.Client()
        self._gen_model = model_name
        self._embedding_model = "models/gemini-embedding-001"

    def get_img_description(
        self,
        image_path: str,
        prompt: str = "Опиши изображение подробно.",
    ) -> str:
        """
        Возвращает текстовое описание изображения с использованием Gemini.

        :param image_path: Путь к файлу изображения.
        :param prompt: Промпт для модели.
        :return: Сгенерированное описание.
        """
        if not os.path.isfile(image_path):
            raise FileNotFoundError(f"Изображение не найдено: {image_path}")

        mime_type = self._get_mime_type(image_path)
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        response = self._client.models.generate_content(
            model=self._gen_model,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                prompt,
            ],
        )
        return response.text.strip()

    def get_embedding(self, text: str) -> List[float]:
        """
        Возвращает эмбеддинг для заданного текста.

        :param text: Входной текст.
        :return: Список float — вектор эмбеддинга.
        """
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Текст должен быть непустой строкой.")

        result = self._client.models.embed_content(
            model=self._embedding_model,
            contents=text,
        )
        # result.embeddings
        
        return result.embeddings[0].values

    @staticmethod
    def _get_mime_type(filepath: str) -> str:
        """Определяет MIME-тип изображения по расширению."""
        ext = filepath.lower().split(".")[-1]
        mime_map = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "webp": "image/webp",
            "bmp": "image/bmp",
            "gif": "image/gif",
        }
        return mime_map.get(ext, "image/jpeg")