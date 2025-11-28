import os
from google import genai
from typing import List
from google.genai import types
from pathlib import Path

from config import API_KEY, RECOGNIZING_MODEL, I2T_PROMPT, EMBEDDING_MODEL

GOOGLE_AI_CLIENT = genai.Client(api_key=API_KEY)

def get_img_description(image_path: Path) -> str:
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Изображение не найдено: {image_path}")

    ext = str(image_path).lower().split(".")[-1]
    mime_map = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "bmp": "image/bmp",
        "gif": "image/gif",
    }
    mime_type = mime_map.get(ext)
    if mime_type == None:
        raise ValueError(f"mime_type не известен {ext}")

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    return GOOGLE_AI_CLIENT.models.generate_content(
            model=RECOGNIZING_MODEL,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                I2T_PROMPT,
            ],
        ).text.strip()

def get_embedding(text: str) -> List[float]:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Текст должен быть непустой строкой.")
    
    return GOOGLE_AI_CLIENT.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
        ).embeddings[0].values
