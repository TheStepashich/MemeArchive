import requests
import os
import mimetypes
from tqdm import tqdm

from config import LOG_FILE, MEME_IN_DIR, PORT

def read_processed_files():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            return set(line.strip() for line in f)
    return set()

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'bmp'}

def get_image_files(folder):
    image_files = []
    for file in os.listdir(folder):
        ext = file.split(".")[-1].lower()
                    
        if (ext in ALLOWED_EXTENSIONS):
            image_files.append(file)
        else:
            print(f"Пропуск файла {file}: неподдерживаемый тип (расширение: {ext})")
    
    return image_files

def write_processed_file(filename):
    with open(LOG_FILE, "a") as f:
        f.write(f"{filename}\n")


def add_dir():
    processed = read_processed_files()
    images = get_image_files(MEME_IN_DIR)
    
    todo = [img for img in images if img not in processed]
    
    if not todo:
        print("Все файлы уже обработаны!")
        return

    print(f"Найдено {len(todo)} файлов для обработки")
    lfd = open("log", "a")

    with requests.Session() as session:
        for filename in tqdm(todo, desc="Отправка файлов"):
            file_path = os.path.join(MEME_IN_DIR, filename)
            
            try:
                # Определяем MIME-тип для отправки
                mime_type, _ = mimetypes.guess_type(file_path)
                if not mime_type:
                    print(f"\nОшибка при обработке {filename}: неизвестный mime_type")

                with open(file_path, 'rb') as f:
                    files = {'file': (filename, f, mime_type)}
                    response = session.post(f"http://localhost:{PORT}/add", files=files)
                    lfd.write(response.text+"\n")
                
                if response.status_code != 200:
                    print(f"\nОшибка при обработке {filename}: {response.status_code}")
                    print(f"Ответ сервера: {response.text}")
                    break
                    
                write_processed_file(filename)
                
            except Exception as e:
                print(f"\nКритическая ошибка при обработке {filename}: {e}")
                break
        else:
            print("\nВсе файлы успешно обработаны!")
    
    lfd.close()

    pass