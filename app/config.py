import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass


def _resolve_project_path(value: str) -> Path:
    """Resolve relative configuration paths from the repository root."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


class Settings:
    # Current names, with backward-compatible fallbacks for older .env files.
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", os.getenv("API_KEY", ""))
    TTS_API_KEY: str = os.getenv("TTS_API_KEY", os.getenv("API_APP_KEY", ""))
    TTS_API_RESOURCE_ID: str = os.getenv(
        "TTS_API_RESOURCE_ID", "seed-tts-2.0"
    )
    LLM_MODEL: str = os.getenv(
        "LLM_MODEL", "doubao-seed-2-0-mini-260428"
    )
    LLM_BASE_URL: str = os.getenv(
        "LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"
    )

    TTS_VOICE: str = os.getenv("TTS_VOICE", "")
    PROJECT_ROOT: Path = PROJECT_ROOT
    WEB_PATH: Path = PROJECT_ROOT / "web"
    STORAGE_PATH: str = str(
        _resolve_project_path(os.getenv("STORAGE_PATH", "output"))
    )
    MAX_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))
    MAX_AUDIO_SIZE_MB: int = int(os.getenv("MAX_AUDIO_SIZE_MB", "10"))
    CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "21600"))
    SUMMARY_CACHE_MAX_ENTRIES: int = int(
        os.getenv("SUMMARY_CACHE_MAX_ENTRIES", "256")
    )
    AUDIO_CACHE_MAX_ENTRIES: int = int(
        os.getenv("AUDIO_CACHE_MAX_ENTRIES", "32")
    )
    GENERATED_CACHE_MAX_ENTRIES: int = int(
        os.getenv("GENERATED_CACHE_MAX_ENTRIES", "128")
    )
    QA_HISTORY_MAX_DOCUMENTS: int = int(
        os.getenv("QA_HISTORY_MAX_DOCUMENTS", "100")
    )
    ALLOWED_EXTENSIONS: tuple = (".pdf",)
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
