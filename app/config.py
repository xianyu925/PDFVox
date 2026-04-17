import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


class Settings:
    API_KEY: str = os.getenv("API_KEY", "")
    ACCESS_TOKEN: str = os.getenv("ACCESS_TOKEN", "")
    API_APP_KEY: str = os.getenv("API_APP_KEY", "")
    TTS_VOICE: str = os.getenv("TTS_VOICE", "")
    STORAGE_PATH: str = "output"
    ALLOWED_EXTENSIONS: tuple = (".pdf",)
    MODEL_ENDPOINT: str = os.getenv("MODEL_ENDPOINT", "")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", 8000))
    AUTO_RELOAD: bool = os.getenv("AUTO_RELOAD", "False").lower() in (
        "1",
        "true",
        "yes",
    )
    ENABLE_LOGGING: bool = False


settings = Settings()
