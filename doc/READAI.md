# PDFVox — AI Coding Assistant Reference

> **Target audience**: AI coding assistants (Claude, Cursor, Copilot). Precision over prose.
> **Project**: FastAPI web app that converts PDF/PPT slides into AI-narrated speech with synchronized subtitles, using Volcengine (火山引擎) LLM + TTS APIs.

---

## 1. File Map & Role

```
run.py                                  # Entry: uvicorn.run("app.main:app")
app/config.py                           # Settings (reads os.environ, optional .env via python-dotenv)
app/main.py                             # FastAPI app factory, route registration, static/template mounts
app/models/db.py                        # SQLite CRUD (uploads + tasks tables), init_db() on import
app/models/schemas.py                   # Pydantic request/response models
app/routers/upload.py                   # POST /upload/ — PDF upload
app/routers/pdf_view.py                 # GET /pdf/{id} — page listing, page image/text
app/routers/ai_explain.py              # GET /explain/* — SSE streaming explanation, seek, cancel
app/routers/qa.py                       # POST /qa/ask/stream — SSE streaming Q&A with ASR
app/services/explain_service.py         # ExplainService — orchestration: summary cache, LLM+TTS dual-stream
app/services/qa_service.py              # QAService — multi-turn Q&A, prompt building, LLM+TTS stream
app/services/llm_service.py             # LLMService — sync (responses.create) + async streaming (chat.completions)
app/services/tts_service.py             # TTSService — Volcengine WebSocket TTS, per-sentence sessions
app/services/asr_service.py             # ASRService — faster-whisper + Silero VAD speech-to-text
app/services/pdf_service.py             # PDFService — pdfplumber text extraction + 150 DPI image rendering
app/services/protocols.py               # Volcengine TTS binary WebSocket protocol (Message, encode/decode)
app/utils/logging.py                    # get_logger(name) factory, file+console handlers
web/index.html                          # Upload page (drag/drop, POST /upload/)
web/viewer.html                         # Main playback page (left panel + PDF + subtitle overlay)
web/status.html                         # Task status query page
web/static/viewer-state.js              # Shared state object + getQueryParam() (ES module)
web/static/viewer.js                    # Entry: DOM init, loadEntirePDF(), fullscreen, wires controls
web/static/viewer-audio.js              # Web Audio engine: queue, DVR seek, word-level highlighting
web/static/viewer-stream.js             # SSE stream handler: state machine, recording, Q&A pipeline
requirements.txt                        # Python dependencies
.env / .env.example                     # Environment variables
```

---

## 2. Module Dependency Graph

```
                            run.py
                               │
                        app/main.py
                         /    │    \         \
        app/config.py   app/models/db.py   app/routers/*   app/utils/logging.py
                                               │
                                     app/services/explain_service.py ──→ llm_service, tts_service, pdf_service, db
                                     app/services/qa_service.py      ──→ llm_service, tts_service, explain_service, db
                                     app/services/llm_service.py     ──→ config (API_KEY)
                                     app/services/tts_service.py     ──→ config (APP_KEY, TOKEN, VOICE) + protocols
                                     app/services/asr_service.py    ──→ (standalone, no internal deps)
                                     app/services/pdf_service.py    ──→ config (STORAGE_PATH)
                                     app/services/protocols.py      ──→ (standalone, pure protocol impl)

web/static/viewer.js         imports viewer-state.js, viewer-audio.js, viewer-stream.js
web/static/viewer-audio.js   imports viewer-state.js
web/static/viewer-stream.js  imports viewer-state.js, viewer-audio.js
```

### Router → Service instantiation (module-level singletons)

| Router file | Instantiates |
|---|---|
| `ai_explain.py` | `ExplainService()`, `TTSService()` |
| `qa.py` | `ASRService()`, `ExplainService()`, `LLMService()`, `TTSService()`, `QAService(llm, tts, explain)` |

**Note**: `ai_explain.py` and `qa.py` each create their own `ExplainService()` and `TTSService()` instances — they are **not** shared singletons. Each router has independent in-memory caches.

---

## 3. Startup Sequence

```
1. python run.py
2. uvicorn imports app.main:app
3. app/main.py executes at module level:
   a. from app.models.db import init_db → triggers init_db() on import (creates tables)
   b. init_db() called again explicitly
   c. Imports 4 router modules (upload, pdf_view, ai_explain, qa)
   d. Registers routers with prefixes: /upload, /pdf, /explain, /qa
   e. Creates output/ and STORAGE_PATH directories
   f. Mounts /static → web/static/
   g. Defines Jinja2Templates for /, /viewer.html, /status.html
   h. Defines /api/health
4. uvicorn starts listening on HOST:PORT
```

---

## 4. Configuration Matrix

All from `app/config.py` → `settings` singleton. Source: `os.environ` + optional `.env` (python-dotenv).

| Variable | Type | Default | Consumed by | Effect |
|---|---|---|---|---|
| `API_KEY` | str | `""` | `LLMService.__init__()` | Volcengine API key for both sync+async clients |
| `ACCESS_TOKEN` | str | `""` | `TTSService.__init__()` | Volcengine WebSocket auth header `X-Api-Access-Key` |
| `API_APP_KEY` | str | `""` | `TTSService.__init__()` | Volcengine WebSocket auth header `X-Api-App-Key` |
| `TTS_VOICE` | str | `""` | `TTSService.__init__()` | TTS speaker ID (e.g. `zh_female_yingyujiaoxue_uranus_bigtts`) |
| `STORAGE_PATH` | str | `<project>/output` | `PDFService._resolve_path()`, `upload.py` | PDF upload directory |
| `ALLOWED_EXTENSIONS` | tuple | `(".pdf",)` | `upload.py` | File type whitelist |
| `MODEL_ENDPOINT` | str | `""` | (unused in current code) | Reserved |
| `HOST` | str | `0.0.0.0` | `run.py` | uvicorn bind address |
| `PORT` | int | `8000` | `run.py` | uvicorn port |
| `AUTO_RELOAD` | bool | `False` | `run.py` | uvicorn hot reload |
| `LOG_LEVEL` | str | `INFO` | `app/utils/logging.py` | Root logger level |
| `LOG_TO_CONSOLE` | bool | `True` | `app/utils/logging.py` | Enable StreamHandler |

---

## 5. API Endpoints

### 5.1 Upload

**`POST /upload/`**
- Input: `multipart/form-data` with `file` field (PDF)
- Output: `{file_id, filename, url}`
- Side effects: writes PDF to `STORAGE_PATH/{uuid}.pdf`, inserts into SQLite `uploads`
- Error: 400 on non-PDF extension

### 5.2 PDF View

**`GET /pdf/{file_id}`**
- Output: `{file_id, filename, pages: [1, 2, ..., N]}`
- Calls: `PDFService.list_pages()`

**`GET /pdf/{file_id}/page/{page}`**
- Output: `{page, text, image_url}` (image_url is `data:image/png;base64,...`)
- Calls: `PDFService.get_page_text()` + `PDFService.get_page_image()` (150 DPI PNG)

### 5.3 Explanation (SSE)

All return `text/event-stream` with headers: `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no`, CORS `*`.

**`GET /explain/all-stream-v3/{file_id}?course_name=&from_page=`**
- Full-book streaming. Iterates pages sequentially, yields SSE events per page.
- Calls: `ExplainService.explain_page_realtime_stream()` per page
- Prefetch: `asyncio.create_task(service.prefetch_summary())` for page+2

**`GET /explain/stream-v3/{file_id}/page/{page_num}?course_name=`**
- Single-page streaming. Same core pipeline as all-stream-v3 but one page only.

**`GET /explain/playback/seek/{file_id}/page/{page_num}?time_offset=&ahead=`**
- DVR seek: looks up cached full script. If missing, calls `get_full_script()`.
- Calls: `get_or_generate_page_sentences()` → skips sentences up to `time_offset` → yields cached audio SSE events
- Background: `asyncio.create_task(get_full_script())` for next `ahead` pages

**`DELETE /explain/cancel/{file_id}`**
- Sets `_cancel_tokens[file_id] = True` on the router's ExplainService instance

**`GET /explain/status/{task_id}`**
- Queries SQLite `tasks` table, returns `{task_id, status, detail}`

### 5.4 Q&A (SSE)

**`POST /qa/ask/stream`**
- Input: `multipart/form-data` — `file` (audio/wav, optional), `question` (text, optional), `file_id`, `page_num`
- Flow: if audio → `ASRService.transcribe_pcm_to_text()` → text; background `asyncio.create_task(get_full_script())`; then `QAService.stream_qa_response()`
- Returns: SSE stream with `audio`, `text`, `error` events, terminated by `[DONE]`

### 5.5 Pages & Health

**`GET /`** → index.html (Jinja2)
**`GET /viewer.html`** → viewer.html (Jinja2)
**`GET /status.html`** → status.html (Jinja2)
**`GET /api/health`** → `{status: "ok"}`

---

## 6. Data Flow Diagrams

### 6.1 Full-Book Streaming (`/explain/all-stream-v3`)

```
Browser clicks "一键生成"
  → EventSource connects to /explain/all-stream-v3/{file_id}?course_name=X
  
Server-side (per page P):
  1. pdfplumber: render page P → 150 DPI PNG → base64
  2. asyncio.gather(prev_summary, next_summary) with 3s timeout
     → if cached: instant; else: LLMService.generate_explanation() (sync, doubao-seed-2-0-pro)
  3. LLMService.stream_explanation() (async, doubao-seed-1-8-251228, chat.completions.create)
     → yields {"type":"text","data":"..."} chunks → text_queue (asyncio.Queue)
  4. Concurrent TTS task reads text_queue:
     → text_splitter: accumulates text, splits by delimiters (。！？，；\n!?,;) + 60-char max
     → per sentence: _synthesize_sentence() → WebSocket session → PCM + word_boundary
     → yields {"type":"audio","data":"<base64>","sentence":"...","duration":N,"word_timestamps":[...]}
     → out_queue (asyncio.Queue)
  5. Main loop reads out_queue → yields to SSE response
  6. Background: prefetch summary for page P+2 (asyncio.create_task)

SSE events sent:
  global_start → for each page: page_start → audio*N → page_complete → global_end → [DONE]
```

### 6.2 DVR Seek (`/explain/playback/seek`)

```
User drags progress slider → binary search sentenceStartTimes[]
  → fetch /explain/playback/seek/{file_id}/page/{P}?time_offset=X
  → Server: get_or_generate_page_sentences(full_script, file_id, page)
    → if page_audio_cache hit: return cached sentences
    → else: TTSService.stream_tts_input() for entire page text, cache and return
  → skip sentences until cumulative duration ≥ time_offset
  → SSE stream: audio*N → [DONE]
  → Frontend: rebuilds audio queue, resumes playback
```

### 6.3 Q&A (`/qa/ask/stream`)

```
User clicks "Ask" → mic opens → MediaRecorder records
  → silence detection (RMS < 0.02 for 800ms) → auto-stop
  → _convertBlobTo16kWav() → WAV blob
  → POST /qa/ask/stream (multipart: file=WAV, file_id, page_num)
  
Server:
  1. _extract_pcm() from WAV → ASRService.transcribe_pcm_to_text() → text
  2. asyncio.create_task(explain_service.get_full_script(file_id, page_num))  # fire-and-forget
  3. QAService.stream_qa_response():
     a. get_upload(file_id) → get page image (pdfplumber)
     b. _build_prompt(): checks summary_cache[f"script_{file_id}_{page_num}"]
        → if cached: _QA_SYSTEM_WITH_SCRIPT (script + history + image)
        → if not: _QA_SYSTEM_WITHOUT_SCRIPT (history + image)
     c. LLMService.stream_explanation() → text chunks
     d. TTSService.stream_tts_input() → audio chunks (concurrent with LLM via asyncio.Queue)
     e. add_history(file_id, question, answer) — caps at 5 rounds
  4. SSE events: text*, audio*, [DONE]
  
Frontend:
  → Plays answer audio with subtitle
  → Shows "Resume" / "Close" floating panel
```

---

## 7. In-Memory State

All caches are dict-based, per-instance, no TTL, no eviction. Lost on process restart.

### ExplainService

| Cache | Key | Value | Populated by | Read by |
|---|---|---|---|---|
| `summary_cache[file_id]` | `page_num` (int) | page summary string (≤100 chars) | `_ensure_single_summary()` → LLM sync | `_get_context_summaries()` |
| `summary_cache[file_id]` | `f"script_{file_id}_{page_num}"` | full script string | `get_full_script()` → LLM sync | `playback_seek()`, `_build_prompt()` (QA) |
| `page_audio_cache[file_id]` | `page_num` (int) | `list[dict]` where dict = `{sentence, audio, duration, word_timestamps}` | `get_or_generate_page_sentences()`, `stream_page_sentences()` | `playback_seek()`, `stream_page_sentences()` |
| `_cancel_tokens` | `file_id` (str) | `bool` | `cancel_stream()` | `_is_cancelled()` in LLM/TTS/main loops |

### QAService

| Cache | Key | Value | Max size |
|---|---|---|---|
| `_history[file_id]` | (implicit list) | `list[dict]` where dict = `{question, answer}` | 5 rounds (FIFO, oldest evicted) |

---

## 8. Constants & Magic Values

### LLM Service (`app/services/llm_service.py`)

| Value | Location | Purpose |
|---|---|---|
| `https://ark.cn-beijing.volces.com/api/v3` | line 14, 19 | Volcengine API base URL |
| `doubao-seed-2-0-pro-260215` | line 73 | Model for sync non-streaming calls (summaries, full scripts) |
| `doubao-seed-1-8-251228` | line 155 | Model for async streaming calls (realtime explanation) |
| `max_tokens=800` | line 24 | Default max_tokens for `generate_explanation()` |
| `max_tokens=800` | line 98 | Default max_tokens for `stream_explanation()` |
| `max_tokens=200` | explain_service.py line 80 | Override for page summaries |

### TTS Service (`app/services/tts_service.py`)

| Value | Location | Purpose |
|---|---|---|
| `wss://openspeech.bytedance.com/api/v3/tts/bidirection` | line 39 | TTS WebSocket endpoint |
| `X-Api-Resource-Id: seed-tts-2.0` | line 63 | TTS resource ID header |
| `24kHz, 16-bit, mono, PCM` | line 193-197 | Audio format in `base_request` |
| `ssl.CERT_NONE` | line 68 | SSL verification disabled |
| TTS sentence delimiters: `。！？，；\n!?,;` | line 206 | Text splitter characters |
| `max sentence length: 60 chars` | line 221 | Force flush threshold |
| `open_timeout=30, ping_interval=15, ping_timeout=15` | line 74-76 | WebSocket connect params |
| `family=socket.AF_INET` | line 78 | Force IPv4 |

### Explain Service (`app/services/explain_service.py`)

| Value | Location | Purpose |
|---|---|---|
| `timeout=3.0` (seconds) | line 144 | Adjacent page summary timeout |
| `timeout=120.0` (seconds) | line 224, 261 | Queue read timeouts (LLM→TTS text, main loop) |
| `asyncio.sleep(0.1)` | line 251 | Delay between launching LLM and TTS tasks (ensures text_queue has consumer) |
| `ahead=60` (pages) | `playback_seek()` param | DVR background prefetch range |

### ASR Service (`app/services/asr_service.py`)

| Value | Location | Purpose |
|---|---|---|
| `faster_whisper.WhisperModel("base", device="cpu", compute_type="int8")` | line 37 | Whisper model config |
| `language="zh", beam_size=5` | line 127 | Whisper transcribe params |
| `DEFAULT_SAMPLE_RATE = 16000` | line 17 | Audio sample rate |
| `RMS threshold > 100` | line 109 | Fallback speech detection (when VAD unavailable) |

### QA Service (`app/services/qa_service.py`)

| Value | Location | Purpose |
|---|---|---|
| Max history rounds: `5` | line 54 | Conversation history cap |
| `asyncio.sleep(0.05)` | line 200 | LLM→TTS launch gap |

### PDF Service (`app/services/pdf_service.py`)

| Value | Location | Purpose |
|---|---|---|
| `resolution=150` (DPI) | line 53 | Page image render resolution |

### Frontend (`web/static/viewer-stream.js`)

| Value | Location | Purpose |
|---|---|---|
| Silence threshold: `RMS < 0.02` for `800ms` | setupAskButton() | Auto-stop recording |
| Audio resample: `16000 Hz` | _convertBlobTo16kWav() | WAV output for ASR |
| Progress update interval: `100ms` | viewer-audio.js | updateProgressUI() setInterval |

---

## 9. SSE Event Protocol (Complete Catalog)

### Events sent by server → client

| `type` | Direction | Fields | When |
|---|---|---|---|
| `global_start` | S→C | `total_pages, ts` | Start of all-stream-v3 |
| `page_start` | S→C | `page, ts` | Before each page's LLM+TTS pipeline |
| `start` | S→C | `page, ts` | explain_page_realtime_stream start |
| `text` | S→C | `data, page, ts` | Each LLM text chunk (streaming) |
| `audio` | S→C | `data` (base64 PCM), `page`, `sentence`, `duration`, `word_timestamps[{char,start,end}]` | Each synthesized sentence |
| `end` | S→C | `page, page_duration?, ts` | Page pipeline completed |
| `page_complete` | S→C | `page, total_pages, ts` | End of one page in all-stream |
| `global_end` | S→C | `ts` | End of all-stream-v3 |
| `error` | S→C | `message, page?, ts` | Any error in pipeline |
| `cancelled` | S→C | `ts` | Stream cancelled by user |
| `[DONE]` | S→C | (literal string `data: [DONE]\n\n`) | SSE stream terminator |

### Events used internally (LLMService → caller)

| `type` | Fields | Purpose |
|---|---|---|
| `start` | `data: {page, stage:"llm"}`, `page`, `ts` | LLM stream starting |
| `text` | `data: "<chunk>"`, `page`, `ts` | LLM text chunk |
| `end` | `data: {page, stage:"llm", length}`, `page`, `ts` | LLM stream finished |
| `error` | `data: {error, stage:"llm"}`, `page`, `ts` | LLM stream error |

### Events used internally (TTSService → caller)

| `type` | Fields | Purpose |
|---|---|---|
| `audio` | `data` (base64 PCM), `page`, `sentence`, `duration`, `word_timestamps`, `ts` | Synthesized sentence audio |
| `error` | `message` | TTS synthesis error |

---

## 10. External API Reference

### 10.1 Volcengine LLM (doubao)

**Sync path** — `LLMService.generate_explanation()`:
- Client: `openai.OpenAI`
- Endpoint: `https://ark.cn-beijing.volces.com/api/v3`
- Method: `client.responses.create(model="doubao-seed-2-0-pro-260215", input=[...])`
- Auth: `api_key=settings.API_KEY`
- Input format: `[{role:"system"/"user", content:[{type:"input_text"/"input_image", ...}]}]`
- Output: `response.output[1].content[].text`
- Used for: page summaries, full scripts (non-streaming, quality-first)

**Async streaming path** — `LLMService.stream_explanation()`:
- Client: `openai.AsyncOpenAI`
- Endpoint: `https://ark.cn-beijing.volces.com/api/v3`
- Method: `async_client.chat.completions.create(model="doubao-seed-1-8-251228", messages=[...], stream=True)`
- Auth: `api_key=settings.API_KEY`
- Input format: OpenAI standard `[{role, content}]` (not Volcengine-specific)
- Output: `async for chunk in response` → `chunk.choices[0].delta.content`
- Used for: realtime streaming explanation, Q&A answers (speed-first)

**Prompt format conversion** (sync path only): `type:"text"` → `type:"input_text"`, `type:"image_url"` → `type:"input_image"`. The async path uses standard OpenAI format.

### 10.2 Volcengine TTS (Bidirectional WebSocket)

- Endpoint: `wss://openspeech.bytedance.com/api/v3/tts/bidirection`
- Auth headers:
  - `X-Api-App-Key: {settings.API_APP_KEY}`
  - `X-Api-Access-Key: {settings.ACCESS_TOKEN}`
  - `X-Api-Resource-Id: seed-tts-2.0`
  - `X-Api-Connect-Id: {uuid4}`
- Protocol: Custom binary protocol (see Section 11)
- Audio: 24kHz, 16-bit, mono, PCM
- Session model: per-sentence (StartSession → TaskRequest → receive PCM → SessionFinished)
- Voice: `settings.TTS_VOICE`
- SSL: verification disabled (`ssl.CERT_NONE`), proxy env vars stripped

### 10.3 ASR (local)

- Model: `Systran/faster-whisper-base` (via HuggingFace)
- Config: CPU, int8 quantization
- VAD: `silero-vad` (optional, falls back to RMS energy)
- Transcribe params: `language="zh"`, `beam_size=5`
- Input: 16kHz, 16-bit, mono PCM converted to temp WAV
- Output: transcribed Chinese text

---

## 11. TTS Binary Protocol (Key Values)

Custom binary WebSocket protocol implemented in `app/services/protocols.py`.

### Wire Format (1-byte header row + optional extensions + payload)

```
Byte 0: [Version(4b) | HeaderSize(4b)]
Byte 1: [MsgType(4b) | Flags(4b)]
Byte 2: [Serialization(4b) | Compression(4b)]
Bytes 3..(4*HeaderSize-1): padding
Extensions: event(int32), session_id(string), connect_id(string), sequence(int32), error_code(uint32)
Payload: [size(uint32) | data(bytes)]
```

### MsgType values used by this project

| Constant | Value | Usage |
|---|---|---|
| `FullClientRequest` | `0b0001` (1) | All client→server messages (connect, session, task) |
| `FullServerResponse` | `0b1001` (9) | Server responses with event + payload (ConnectionStarted, SessionStarted, TTSResponse, etc.) |
| `AudioOnlyServer` | `0b1011` (11) | PCM audio data from server |

### EventType values used

| Constant | Value | Direction | Purpose |
|---|---|---|---|
| `StartConnection` | 1 | C→S | Initiate connection |
| `FinishConnection` | 2 | C→S | Close connection |
| `ConnectionStarted` | 50 | S→C | Connection accepted |
| `StartSession` | 100 | C→S | Begin synthesis session |
| `FinishSession` | 102 | C→S | End synthesis session (sent before receiving data) |
| `SessionStarted` | 150 | S→C | Session created |
| `SessionFinished` | 152 | S→C | Session ended (marks end of AudioOnlyServer stream) |
| `TaskRequest` | 200 | C→S | Submit text for synthesis |
| `TTSResponse` | 352 | S→C | Contains `word_boundary` timestamps in JSON payload |

### TTS Session Lifecycle (per sentence)

```
Client                          Server
  |                               |
  |-- StartConnection (event=1) ->|
  |<- ConnectionStarted (event=50)|
  |                               |
  |-- StartSession (event=100) -->|
  |<- SessionStarted (event=150) -|
  |-- TaskRequest (event=200) --->|
  |-- FinishSession (event=102) ->|
  |<- AudioOnlyServer (PCM) ------|  (multiple messages)
  |<- SessionFinished (event=152) |
  |                               |
  |-- FinishConnection (event=2) >|
```

---

## 12. Database Schema

Database: `output/pdfvox.db` (SQLite, `check_same_thread=False`, `row_factory=sqlite3.Row`)

### Table: `uploads`

```sql
CREATE TABLE IF NOT EXISTS uploads (
    file_id TEXT PRIMARY KEY,
    filename TEXT,
    path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Table: `tasks`

```sql
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    file_id TEXT,
    page INTEGER,
    status TEXT,
    detail TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Key functions (all in `app/models/db.py`)

Each opens and closes its own connection. Returns `dict` (converted from `sqlite3.Row`).

| Function | SQL |
|---|---|
| `save_upload(file_id, data)` | `INSERT OR REPLACE INTO uploads` |
| `get_upload(file_id)` | `SELECT * FROM uploads WHERE file_id = ?` |
| `list_uploads()` | `SELECT * FROM uploads ORDER BY created_at DESC` |
| `save_task(task_id, data)` | `INSERT OR REPLACE INTO tasks` |
| `get_task(task_id)` | `SELECT * FROM tasks WHERE task_id = ?` |
| `update_task_status(task_id, status, detail)` | `UPDATE tasks SET status=?, detail=?, updated_at=CURRENT_TIMESTAMP` |
| `list_tasks()` | `SELECT * FROM tasks ORDER BY updated_at DESC` |

---

## 13. Frontend Architecture

### 13.1 Module Dependencies (ES modules, no bundler)

```
viewer.js
  ├── imports: viewer-state.js (state, dom, getQueryParam)
  ├── imports: viewer-audio.js (initAudioContext, queueAudioChunk, setupPlayerControls, seekToTime)
  ├── imports: viewer-stream.js (setupExplainAllButton, setupAskButton, resumeExplanation)
  └── on DOMContentLoaded:
      ├── fills dom object with element refs
      ├── loadEntirePDF() → GET /pdf/{id} → lazy-load pages
      ├── detectCurrentPage() → scroll-based
      └── calls setupPlayerControls(), setupExplainAllButton(), setupAskButton()

viewer-audio.js
  └── imports: viewer-state.js (state)

viewer-stream.js
  ├── imports: viewer-state.js (state)
  └── imports: viewer-audio.js (queueAudioChunk) — only for SSE audio events
```

### 13.2 Shared State (`viewer-state.js` — `state` object)

| Field | Type | Set by | Used by |
|---|---|---|---|
| `totalPages` | int | viewer.js (loadEntirePDF) | audio.js, stream.js |
| `currentPage` | int | viewer.js (detectCurrentPage) | audio.js, stream.js |
| `audioCtx` | AudioContext | audio.js (initAudioContext) | audio.js |
| `nextPlayTime` | float | audio.js (queueAudioChunk) | audio.js |
| `audioQueue` | array | audio.js (queueAudioChunk, seekToTime) | audio.js |
| `isProcessingQueue` | bool | audio.js (processAudioQueue) | audio.js |
| `currentPlayingPage` | int | audio.js (processAudioQueue) | audio.js, viewer.js |
| `resumePage` | int | stream.js (_startExplainStream) | stream.js |
| `currentEventSource` | EventSource | stream.js (_startExplainStream) | stream.js |
| `currentStreamAbort` | function | stream.js | stream.js |
| `isQaActive` | bool | stream.js | stream.js |
| `playedTime` | float | audio.js (processAudioQueue) | audio.js, stream.js |
| `liveWindowEnd` | float | audio.js (queueAudioChunk) | audio.js |
| `pageTimeMap` | array | audio.js | audio.js |
| `sentenceStartTimes` | array[dict] | audio.js (queueAudioChunk) | audio.js (seekToTime) |
| `playbackStartTime` | float | audio.js | audio.js |
| `progressInterval` | intervalID | audio.js (setupPlayerControls) | audio.js |
| `seekAbortController` | AbortController | audio.js (seekToTime) | audio.js |
| `isSeeking` | bool | audio.js | audio.js |
| `isDragging` | bool | audio.js | audio.js |
| `currentWordTimestamps` | array | audio.js (queueAudioChunk) | audio.js (updateProgressUI) |
| `currentSentenceStartTime` | float | audio.js (queueAudioChunk) | audio.js (updateProgressUI) |

### 13.3 Key Frontend Functions

**viewer-audio.js**:
- `initAudioContext()` — creates AudioContext + GainNode
- `queueAudioChunk(base64, page, sentence, duration, wordTimestamps)` — base64→ArrayBuffer→Int16Array→AudioBuffer→schedule BufferSource, records sentenceStartTimes
- `processAudioQueue()` — queue consumer: sets active page, renders subtitle with `<span class="sc">`, plays, waits for `onended`
- `seekToTime(targetSeconds)` — binary search sentenceStartTimes, fetch `/explain/playback/seek`, rebuild queue
- `updateProgressUI()` — setInterval(100ms): progress slider, time label, `_highlightActiveWord()` via matching currentTime to word_timestamp index
- `setupPlayerControls()` — play/pause, progress slider drag, volume, keyboard arrows (±5s)

**viewer-stream.js**:
- Button state machine: `IDLE → GENERATING → PAUSED` with button text toggle
- `_startExplainStream(courseName)` — creates EventSource, dispatches onmessage to json parse → page_start/audio/end/error/cancelled
- `setupExplainAllButton()` — wires state machine to button
- `setupAskButton()` — getUserMedia → MediaRecorder → silence detection → _convertBlobTo16kWav() → POST /qa/ask/stream → show answer panel
- `_convertBlobTo16kWav(blob)` — OfflineAudioContext resample to 16kHz + WAV header
- `_encodeWAV(samples, sampleRate)` — manual WAV header construction
- `resumeExplanation(fileId, courseName)` — reconnects EventSource from resumePage

---

## 14. Key Architecture Patterns

### 14.1 LLM+TTS Dual-Stream Concurrency

Both `ExplainService.explain_page_realtime_stream()` and `QAService.stream_qa_response()` use the same pattern:

```
asyncio.create_task(run_llm())  → writes text chunks to text_queue
asyncio.sleep(0.1 or 0.05)      → ensures consumer exists before producer
asyncio.create_task(run_tts())  → reads from text_queue, writes audio events to out_queue
Main loop                        → reads out_queue, yields to SSE
```

LLM task puts `"<END>"` sentinel when done. TTS task puts `"<DONE>"` sentinel when done.

### 14.2 TTS Text Splitter

`TTSService.stream_tts_input()` processes text asynchronously:
1. Pre-connects WebSocket while waiting for first text chunk
2. On first text: launches `text_splitter` background task
3. Splitter accumulates text, extracts sentences by delimiter (`。！？，；\n!?,;`), force-flushes at 60 chars or on stream end
4. Sentences queued → `_synthesize_sentence()` per sentence (each creates its own WebSocket session)
5. `None` sentinel marks splitter completion

### 14.3 Cancellation

`ExplainService._cancel_tokens: dict[str, bool]` checked in three places:
- LLM task loop (stops yielding text chunks)
- TTS task's `tts_input_stream()` generator (stops feeding text)
- Main event loop (stops reading from out_queue)

Set via `DELETE /explain/cancel/{file_id}`. Reset at start of `all-stream-v3`.

### 14.4 Caching Strategy (no eviction, no TTL)

1. **Page summaries** (`summary_cache[file_id][page_num]`): generated by LLM sync call, used for adjacent page context. Prefetched 2 pages ahead.
2. **Full scripts** (`summary_cache[f"script_{file_id}_{page_num}"]`): generated by LLM sync call, used for DVR seek and Q&A context.
3. **Page audio** (`page_audio_cache[file_id][page_num]`): list of {sentence, audio b64, duration, word_timestamps}. Hit = instant replay, no TTS call needed.

### 14.5 PDF Thread Safety

`PDFService._locks: dict[str, threading.Lock]` — one lock per file path. All `get_page_text()`, `get_page_image()`, `list_pages()` acquire the lock. Paths are resolved via `_resolve_path()`: relative paths joined with `STORAGE_PATH` using only the filename component.

### 14.6 Logging

`get_logger(name)` in `app/utils/logging.py` is a factory that configures the root logger once (module-level `_configured` flag). Format: `"%(asctime)s - %(name)s - %(levelname)s - %(message)s"`. Output to `log.txt` (UTF-8) + optional console. Level from `settings.LOG_LEVEL`.

---

## 15. Known Issues / Caveats

1. **Two ExplainService instances**: `ai_explain.py` and `qa.py` each instantiate their own `ExplainService()`. The cancel token set by the `/explain` router will NOT affect the `/qa` router's ExplainService, and vice versa. Caches are also not shared between routers.

2. **VAD return value ignored**: In `ASRService.transcribe_pcm_to_text()` (asr_service.py line 114), `_vad_check()` is called but its return value is discarded — transcription proceeds regardless of VAD result. The `detect_speaking_from_pcm()` method correctly uses it.

3. **TTS SSL verification disabled**: `ssl.CERT_NONE` is set in `TTSService._connect()`.

4. **No authentication**: The entire API is unauthenticated. All routes are public.

5. **No concurrency control on caches**: Multiple concurrent requests for the same page may trigger duplicate LLM/TTS calls before the first one caches the result.

6. **`tts_server.py`**: Exists at project root but references a `TTSService.synthesize()` method not in the current codebase. It is dead code and not used by the main app.

7. **`MODEL_ENDPOINT` config**: Defined in `Settings` but never read by any code.
