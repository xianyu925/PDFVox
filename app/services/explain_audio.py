"""Page-level TTS generation and audio-cache policy for explanations."""

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.utils.logging import get_logger


logger = get_logger(__name__)

CacheGet = Callable[[Any, str], Awaitable[Any]]
CacheSet = Callable[[Any, str, str, Any], Awaitable[None]]
IsCancelled = Callable[[str, str], bool]


async def get_or_generate_page_sentences(
    *,
    text: str,
    file_id: str,
    page_num: int,
    course_name: str,
    tts_service,
    cache,
    cache_key: str,
    cache_get: CacheGet,
    cache_set: CacheSet,
) -> tuple[list[dict], bool]:
    cached = await cache_get(cache, cache_key)
    if cached is not None:
        logger.info("Page %s audio cache hit", page_num)
        return cached, True

    logger.info("Page %s audio cache miss; synthesizing", page_num)
    sentences = []

    async def text_stream():
        yield {"type": "text", "data": text}
        yield {"type": "end"}

    async for event in tts_service.stream_tts_input(text_stream(), page_num):
        if event.get("type") == "error":
            raise RuntimeError(event.get("message", "TTS synthesis failed"))
        if event.get("type") == "audio" and event.get("data"):
            sentences.append(
                {
                    "sentence": event.get("sentence", ""),
                    "audio": event.get("data", ""),
                    "duration": event.get("duration", 0),
                    "word_timestamps": event.get("word_timestamps", []),
                }
            )

    if not sentences:
        raise RuntimeError("TTS returned no playable sentences")
    await cache_set(cache, cache_key, "audio", sentences)
    logger.info("Cached %s synthesized sentences for page %s", len(sentences), page_num)
    return sentences, False


async def stream_page_sentences(
    *,
    file_id: str,
    page_num: int,
    tts_text_stream,
    course_name: str,
    tts_service,
    cache,
    cache_key: str,
    cache_get: CacheGet,
    cache_set: CacheSet,
    is_cancelled: IsCancelled,
    use_cache: bool = True,
    session_id: str | None = None,
) -> AsyncIterator[dict]:
    cached = await cache_get(cache, cache_key) if use_cache else None
    if cached is not None:
        logger.info("Page %s streaming audio cache hit", page_num)
        for index, item in enumerate(cached, start=1):
            yield {
                "type": "audio",
                "data": item["audio"],
                "index": item.get("index", index),
                "sentence": item["sentence"],
                "duration": item.get("duration", 0),
                "word_timestamps": item.get("word_timestamps", []),
                "page": page_num,
            }
        return

    sentences = []
    had_error = False
    async for event in tts_service.stream_tts_input(tts_text_stream, page_num):
        if event.get("type") == "error":
            had_error = True
        if event.get("type") == "audio" and event.get("data"):
            sentences.append(
                {
                    "sentence": event.get("sentence", ""),
                    "audio": event.get("data", ""),
                    "index": event.get("index", len(sentences) + 1),
                    "duration": event.get("duration", 0),
                    "word_timestamps": event.get("word_timestamps", []),
                }
            )
        yield event

    was_cancelled = bool(session_id and is_cancelled(file_id, session_id))
    if sentences and not had_error and not was_cancelled:
        await cache_set(cache, cache_key, "audio", sentences)
        logger.info("Cached %s streamed sentences for page %s", len(sentences), page_num)
