from dotenv import load_dotenv
import os

load_dotenv()

API_KEY: str = os.getenv("API_KEY")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL")
RECOGNIZING_MODEL = os.getenv("RECOGNIZING_MODEL")

PORT: int = int(os.getenv("PORT"))
LANG: str = os.getenv("LANG")
I2T_PROMPT_FILE: str = os.getenv("I2T_PROMPT_FILE")
CHROMA_DIR: str = os.getenv("CHROMA_DIR")
MEME_IN_DIR: str = os.getenv("MEME_IN_DIR")
UPLOADS_DIR: str = os.getenv("UPLOADS_DIR")
LOG_FILE: str = os.getenv("LOG_FILE")

with open(I2T_PROMPT_FILE, "r") as fd:
    I2T_PROMPT = fd.read().format(lang = LANG) 