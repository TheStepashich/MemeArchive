import os

os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_MODEL", "test-embedding")
os.environ.setdefault("RECOGNIZING_MODEL", "test-recognizing")
os.environ.setdefault("CHROMA_DIR", "/tmp/meme-archive-test-chroma")
os.environ.setdefault("UPLOADS_DIR", "/tmp/meme-archive-test-uploads")
os.environ.setdefault("MEME_IN_DIR", "/tmp/meme-archive-test-memes")
os.environ.setdefault("STATS_FILE", "/tmp/meme-archive-test-stats.json")
os.environ.setdefault("EMBED_CACHE_FILE", "/tmp/meme-archive-test-embed-cache.db")
os.environ.setdefault("CAPTCHA_ENABLED", "0")
os.environ.setdefault("PENDING_TTL_SECONDS", "0")
os.environ.setdefault("ADMIN_TOKEN", "test-admin")
os.environ.setdefault("MAX_PENDING_ITEMS", "100")
