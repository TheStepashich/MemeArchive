import os
import uuid
from pathlib import Path
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from typing import List, Optional
import io
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from Config import Config
from ChromaDBController import ChromaDBController
from GeminiController import GeminiController


# Инициализация компонентов (один раз при старте)
config = Config()
db = ChromaDBController(
    collection_name="images",
    persist_directory="./chroma_db"
)
gemini = GeminiController(api_key=config.api_key)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Image Semantic Search API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # или укажи конкретные домены, например: ["http://localhost:8000"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/add")
async def add_image(
    file: UploadFile = File(...),
    source: Optional[str] = Form(None)
):
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Файл должен быть изображением.")

    ext = file.filename.split(".")[-1].lower() if "." in file.filename else "jpg"
    img_id = str(uuid.uuid4())
    img_path = UPLOAD_DIR / f"{img_id}.{ext}"

    # Сохраняем файл
    try:
        content = await file.read()
        with open(img_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения файла: {e}")

    # Генерация описания
    try:
        description = gemini.get_img_description(str(img_path), prompt=config.img2txt_prompt.format(lang=config.lang))
    except Exception as e:
        img_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Ошибка генерации описания: {e}")

    # print(description)
    # Получение эмбеддинга
    try:
        embedding = gemini.get_embedding(description)
    except Exception as e:
        img_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Ошибка получения эмбеддинга: {e}")

    # print(embedding)
    # Сохранение в БД
    try:
        db.add(
            ids=[img_id],
            embeddings=[embedding],
            documents=[description],
            metadatas=[{"source": str(img_path), "filename": file.filename}]
        )
    except Exception as e:
        img_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения в БД: {e}")

    return {
        "id": img_id,
        "description": description,
        "saved_path": str(img_path)
    }


@app.post("/search")
async def search_images(
    query: str = Form(...),
    n_results: int = Form(5)
):
    if not query.strip():
        raise HTTPException(status_code=400, detail="Запрос не может быть пустым.")

    try:
        query_embedding = gemini.get_embedding(query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка эмбеддинга запроса: {e}")

    try:
        results = db.search(query_embedding=query_embedding, n_results=n_results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка поиска: {e}")

    # print(results)
    matches = []
    # print(len(results["ids"]))
    for i in range(len(results["ids"])):
        img_id = results["ids"][i]
        img_path = results["metadatas"][i]["source"]

        # print(results["ids"][i])
        # print("p:",img_path)
        if not os.path.isfile(img_path):
            continue  # пропускаем, если файл отсутствует
        # print("o:",img_path)
        # print("===============================")
        matches.append({
            "id": img_id,
            "description": results["documents"][i],
            "source": results["metadatas"][i]["source"],
            "filename": results["metadatas"][i]["source"].split("/")[1],
            "distance": float(results["distances"][i])
        })

    return {"results": matches}


from fastapi.responses import FileResponse

@app.get("/image/{filename}")
async def get_image(filename: str):
    img = UPLOAD_DIR / filename
    # print(img)
    if not os.path.isfile(img):
        raise HTTPException(status_code=404, detail="Изображение не найдено")
    return FileResponse(img)

from fastapi.staticfiles import StaticFiles

app.mount("/", StaticFiles(directory="static",html = True), name="static")

if __name__ == "__main__":
    import uvicorn
    config = Config()
    uvicorn.run(app, host="0.0.0.0", port=config.port)