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
    STORAGE_PATH: str = os.getenv(
        "STORAGE_PATH",
        str(Path(__file__).resolve().parent.parent / "output")
    )
    ALLOWED_EXTENSIONS: tuple = (".pdf",)
    MODEL_ENDPOINT: str = os.getenv("MODEL_ENDPOINT", "")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", 8000))
    AUTO_RELOAD: bool = os.getenv("AUTO_RELOAD", "False").lower() in (
        "1",
        "true",
        "yes",
    )
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_TO_CONSOLE: bool = os.getenv("LOG_TO_CONSOLE", "True").lower() in (
        "1",
        "true",
        "yes",
    )


settings = Settings()
