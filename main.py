import os
from config import UPLOADS_DIR, PORT
from google_ai import get_embedding, get_img_description

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI(title="Image Semantic Search API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


from fastapi import File, Form, UploadFile, HTTPException
import uuid
from pathlib import Path

from chroma_db import db_add, db_search

@app.post("/add")
async def add_image(file: UploadFile = File(...)):
    if not file.content_type.startswith("image/"):
        print("Файл должен быть изображением.")
        raise HTTPException(status_code=400, detail="Файл должен быть изображением.")
    
    ext = file.filename.split(".")[-1].lower()
    img_id = str(uuid.uuid4())
    img_path = Path(UPLOADS_DIR) / f"{img_id}.{ext}"
    
    try:
        content = await file.read()
        with open(img_path, "wb") as f:
            f.write(content)
    except Exception as e:
        print(f"Ошибка сохранения файла: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения файла: {e}")
    
    try:
        description = get_img_description(img_path)
    except Exception as e:
        img_path.unlink(missing_ok=True)
        print(f"Ошибка генерации описания: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка генерации описания: {e}")
    
    try:
        embedding = get_embedding(description)
    except Exception as e:
        img_path.unlink(missing_ok=True)
        print(f"Ошибка получения эмбеддинга: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка получения эмбеддинга: {e}")

    try:
        db_add(
            ids=[img_id],
            embeddings=[embedding],
            documents=[description],
            metadatas=[{"source": str(img_path), "filename": file.filename}]
        )
    except Exception as e:
        img_path.unlink(missing_ok=True)
        print(f"Ошибка сохранения в БД: {e}")
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
        print("Запрос не может быть пустым.")
        raise HTTPException(status_code=400, detail="Запрос не может быть пустым.")

    try:
        query_embedding = get_embedding(query)
    except Exception as e:
        print(f"Ошибка эмбеддинга запроса: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка эмбеддинга запроса: {e}")

    try:
        results = db_search(query_embedding=query_embedding, n_results=n_results)
    except Exception as e:
        print(f"Ошибка поиска: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка поиска: {e}")
    

    matches = []
    for i in range(len(results["ids"])):
        img_id = results["ids"][i]
        img_path = results["metadatas"][i]["source"]

        if not os.path.isfile(img_path):
            continue  
        matches.append({
            "id": img_id,
            "description": results["documents"][i],
            "source": results["metadatas"][i]["source"],
            "filename": results["metadatas"][i]["source"].split("/")[1],
            "distance": float(results["distances"][i])
        })

    return {"results": matches}

from fastapi.responses import FileResponse, HTMLResponse

@app.get("/image/{filename}")
async def get_image(filename: str):
    img = Path(UPLOADS_DIR) / filename
    if not os.path.isfile(img):
        print(f"Изображение не найдено {filename}")
        raise HTTPException(status_code=404, detail="Изображение не найдено")
    return FileResponse(img)

@app.get("/", response_class=HTMLResponse)
async def chroma_page():
    with open("./index.html") as fd:
        html_content = fd.read()
    return HTMLResponse(content=html_content)


import threading
import time
from add_dir import add_dir

if __name__ == "__main__":

    def periodic_add_dir():
        while True:
            time.sleep(10)
            try:
                add_dir()
            except Exception as e:
                print(f"Ошибка в фоновом потоке: {e}")
                break
            break
    background_thread = threading.Thread(target=periodic_add_dir, daemon=True)
    background_thread.start()

    import uvicorn
    uvicorn.run(app, port=PORT)
