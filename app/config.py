import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


class Settings:
    API_KEY: str = os.getenv("API_KEY", "")
    STORAGE_PATH: str = os.getenv("STORAGE_PATH", "output")
    ALLOWED_EXTENSIONS: tuple = (".pdf",)
    MODEL_ENDPOINT: str = os.getenv("MODEL_ENDPOINT", "")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", 8000))
    AUTO_RELOAD: bool = os.getenv("AUTO_RELOAD", "False").lower() in (
        "1",
        "true",
        "yes",
    )


settings = Settings()
