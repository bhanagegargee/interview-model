"""
AI Voice + Video Interview Backend v4.2
- Audio transcription + tone analysis
-- Video body language analysis (MediaPipe + OpenAI)
-- Dual scoring: OpenAI for both speech and video analysis
 - Audio transcription + tone analysis
 -- Video body language analysis (MediaPipe + Groq)
 -- Dual scoring: Groq for both speech and video analysis
- /generate-questions: AI-generated, candidate-specific interview questions
- NEW: per-question dynamic recording timings returned by /get-question
"""
from fastapi import FastAPI, UploadFile, File, Query, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
import base64
from pydantic import BaseModel
import whisper
import os, re, shutil, uuid, logging
from pathlib import Path
from tone_analyzer import ToneAnalyzer
from interview_scorer import InterviewScorer
from video_analyzer import VideoAnalyzer
from question_generator import questionGenerator
from mongo_store import MongoStore

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==========================================================
# FORCE GROQ CONFIG (VERY IMPORTANT)
# ==========================================================
os.environ.setdefault("GROQ_MODEL", "llama-3.1-8b-instant")
os.environ.setdefault("GROQ_API_BASE", "https://api.groq.com")

# ══════════════════════════════════════════════════════════════════
# GROQ API Key — use empty string default so .strip() never crashes
# ══════════════════════════════════════════════════════════════════
# Read GROQ API key from environment; modules will create their own Groq client
groq_key = (os.getenv("GROQ_API_KEY") or "").strip()

# ══════════════════════════════════════════════════════════════════
# FastAPI App
# ══════════════════════════════════════════════════════════════════
app = FastAPI(title="AI Voice + Video Interview Backend", version="4.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ══════════════════════════════════════════════════════════════════
# Load Models
# ══════════════════════════════════════════════════════════════════
logger.info("Loading Whisper model…")
model = whisper.load_model("base")
logger.info("✅ Whisper ready")

# FIX: pass None when key is empty so modules use their own env-var lookup
_key_or_none = groq_key if groq_key else None

tone_analyzer      = ToneAnalyzer()
interview_scorer   = InterviewScorer(api_key=_key_or_none)
video_analyzer     = VideoAnalyzer(api_key=_key_or_none)
question_generator = questionGenerator(api_key=_key_or_none)
mongo_store = MongoStore()

# ══════════════════════════════════════════════════════════════════
# Default Question Set  (fallback when no candidate email given)
# ══════════════════════════════════════════════════════════════════
DEFAULT_HR_QUESTIONS = [
    "Tell me about yourself and your professional background.",
    "What would you say are your top three strengths, and can you give a specific example for at least one?",
    "Describe a challenging situation you faced at work or school and explain how you handled it.",
]

# Default timings for the standard HR questions (milliseconds)
DEFAULT_HR_TIMINGS_MS = [
    90_000,   # Tell me about yourself          → 90 s
    75_000,   # Top three strengths             → 75 s
    90_000,   # Challenging situation (STAR)    → 90 s
]

# ── Per-candidate stores (keyed by email) ──────────────────────────
# In production replace with a DB (SQLite / Redis / Postgres)
candidate_question_store: dict[str, list[str]] = {}
candidate_timing_store:   dict[str, list[int]] = {}   # milliseconds per question

TEMP_DIR = Path("temp_media")
TEMP_DIR.mkdir(exist_ok=True)


# ══════════════════════════════════════════════════════════════════
# Pydantic Models
# ══════════════════════════════════════════════════════════════════
class CandidateRegistration(BaseModel):
    name:            str
    email:           str
    qualification:   str
    job_description: str
    question_count:  int = 3


# ══════════════════════════════════════════════════════════════════
# Startup / Shutdown
# ══════════════════════════════════════════════════════════════════
@app.on_event("startup")
async def startup_event():
    print("\n" + "="*70)
    print("  AI VOICE + VIDEO INTERVIEW BACKEND  v4.2")
    print("="*70)
    print(f"  Ollama model: {question_generator.model}")
    print(f"  Ollama API  : {question_generator.endpoint}")
    print("  Questions and timings: generated per candidate")
    print("="*70 + "\n")


@app.on_event("shutdown")
async def shutdown_event():
    try:
        shutil.rmtree(TEMP_DIR)
        TEMP_DIR.mkdir(exist_ok=True)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════
# Routes — Info
# ══════════════════════════════════════════════════════════════════
@app.get("/")
def home():
    return {
        "status":  "healthy",
        "version": "4.2.0",
        "features": [
            "audio_transcription",
            "tone_analysis",
            "video_body_language",
            "ai_question_generation",
            "ai_predicted_timings",
        ],
        "groq_key_loaded": bool(groq_key),
    }


@app.get("/check-api-keys")
def check_api_keys():
    if not groq_key:
        return {"groq": {"status": "❌ NOT FOUND",
                           "fix": "set GROQ_API_KEY=... (Windows) or export GROQ_API_KEY=... (Mac/Linux)",
                           "get_key": "https://www.groq.ai/docs/getting-started"}}
    else:
        return {"groq": {"status": "✅ LOADED",
                           "preview": groq_key[:12] + "..."}}


# Serve a tiny 1x1 PNG favicon to prevent browser 404s for /favicon.ico
FAVICON_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
)


@app.get("/favicon.ico")
def favicon():
    return Response(content=base64.b64decode(FAVICON_PNG_B64), media_type="image/png")


# ══════════════════════════════════════════════════════════════════
# Route — Candidate Registration + Question Generation
# ══════════════════════════════════════════════════════════════════
@app.post("/generate-questions")
def generate_questions(candidate: CandidateRegistration):
    """
    Called by register.html on form submission.

    1. Receives candidate details.
    2. Calls Ollama to generate tailored questions + predicted timings.
    3. Stores both in per-candidate dictionaries keyed by email.
    4. Returns questions + timings to the frontend.
    """
    logger.info(f"📝 Registration: name={candidate.name!r}, email={candidate.email!r}")

    if len(candidate.qualification.strip()) < 5:
        raise HTTPException(400, "Qualification is too short")
    if len(candidate.job_description.strip()) < 10:
        raise HTTPException(400, "Job description is too short")

    result = question_generator.generate(
        qualification=candidate.qualification,
        job_description=candidate.job_description,
        candidate_name=candidate.name,
        question_count=max(3, min(10, candidate.question_count)),
    )

    questions  = result.get("questions", [])
    timings_ms = result.get("timings_ms", [])
    method     = result.get("generation_method", "unknown")
    error      = result.get("error")

    if not questions:
        raise HTTPException(500, "Failed to generate interview questions")

    normalized_email = candidate.email.strip().lower()
    mongo_store.upsert_candidate({
        "name": candidate.name,
        "email": normalized_email,
        "qualification": candidate.qualification,
        "job_description": candidate.job_description,
        "question_count": candidate.question_count,
    })
    session_id = mongo_store.save_session_questions(
        candidate_email=normalized_email,
        candidate_name=candidate.name,
        questions=questions,
        timings_ms=timings_ms,
        generation_method=method,
    )

    # Store both questions and their timings
    candidate_question_store[normalized_email] = questions
    candidate_timing_store[normalized_email]   = timings_ms

    logger.info(
        f"✅ {len(questions)} questions + {len(timings_ms)} timings stored for "
        f"{candidate.email!r} (method={method})"
    )
    logger.info(f"   Timings (ms): {timings_ms}")

    payload = {
        "status":             "success",
        "candidate_email":    normalized_email,
        "candidate_name":     candidate.name,
        "questions":          questions,
        "timings_ms":         timings_ms,
        "question_count":     len(questions),
        "generation_method":  method,
        "session_id":         session_id,
    }
    if error:
        payload["warning"] = error
    return payload


# ══════════════════════════════════════════════════════════════════
# Route — Get Question  (returns timing_ms for that question)
# ══════════════════════════════════════════════════════════════════
@app.post("/get-question")
def get_question(
    question_number:  int = Query(0, ge=0),
    candidate_email:  str = Query(""),
):
    """
    Returns the next interview question for a candidate together with
    the AI-predicted recording time for that question (in milliseconds).
    """
    normalized_email = candidate_email.strip().lower() if candidate_email else ""

    questions = (
        candidate_question_store.get(normalized_email)
        if candidate_email
        else None
    ) or DEFAULT_HR_QUESTIONS

    timings = (
        candidate_timing_store.get(normalized_email)
        if candidate_email
        else None
    ) or DEFAULT_HR_TIMINGS_MS

    if question_number >= len(questions):
        return {"question": "Interview completed. Thank you!", "is_last": True, "timing_ms": 0}

    timing_ms = (
        timings[question_number]
        if question_number < len(timings)
        else 60_000
    )

    return {
        "question":        questions[question_number],
        "is_last":         question_number == len(questions) - 1,
        "question_number": question_number,
        "total_questions": len(questions),
        "timing_ms":       timing_ms,
        "using_custom":    bool(normalized_email and normalized_email in candidate_question_store),
    }


# ══════════════════════════════════════════════════════════════════
# Route — Analyse Answer
# ══════════════════════════════════════════════════════════════════
@app.post("/analyze-answer")
async def analyze_answer(
    audio:    UploadFile = File(...),
    video:    UploadFile = File(None),
    question: str        = Form(""),
    candidate_email: str = Form(""),
    question_number: int = Form(-1),
):
    logger.info(f"📦 Analyze: audio={audio.filename}, video={video.filename if video else 'none'}")

    audio_path = None
    video_path = None

    try:
        audio_content = await audio.read()
        if len(audio_content) == 0:
            raise HTTPException(400, "Audio file is empty")

        audio_ext  = Path(audio.filename or "a.webm").suffix or ".webm"
        audio_path = TEMP_DIR / f"{uuid.uuid4()}{audio_ext}"
        audio_path.write_bytes(audio_content)
        logger.info(f"💾 Audio saved: {audio_path.name} ({audio_path.stat().st_size} bytes)")

        video_analysis_result = None
        if video:
            video_content = await video.read()
            if len(video_content) > 0:
                video_ext  = Path(video.filename or "v.webm").suffix or ".webm"
                video_path = TEMP_DIR / f"{uuid.uuid4()}{video_ext}"
                video_path.write_bytes(video_content)
                logger.info(f"🎥 Video saved: {video_path.name} ({video_path.stat().st_size} bytes)")
            else:
                logger.warning("⚠️  Video file empty")

        try:
            result = model.transcribe(str(audio_path), fp16=False, language="en", task="transcribe")
        except FileNotFoundError:
            raise HTTPException(500, "ffmpeg not found — install from https://ffmpeg.org")

        transcript    = result.get("text", "").strip()
        tone_analysis = tone_analyzer.analyze_audio(str(audio_path))

        ai_score = {}
        if question and transcript:
            ai_score = interview_scorer.generate_score(
                question=question,
                transcript=transcript,
                tone_analysis=tone_analysis,
            )

        if video_path and video_path.exists():
            video_analysis_result = video_analyzer.analyze_video(str(video_path))
            logger.info(f"🎥 Video analysis result: {video_analysis_result}")

        normalized_email = candidate_email.strip().lower()
        if normalized_email:
            mongo_store.append_answer(
                session_id=MongoStore.session_id_from_email(normalized_email),
                candidate_email=normalized_email,
                question_number=question_number if question_number >= 0 else None,
                question=question,
                transcript=transcript,
                tone_analysis=tone_analysis,
                ai_score=ai_score,
                video_analysis=video_analysis_result,
            )

        return {
            "transcript":     transcript,
            "language":       result.get("language", "en"),
            "duration":       round(result.get("duration", 0), 2),
            "tone_analysis":  tone_analysis,
            "ai_score":       ai_score,
            "video_analysis": video_analysis_result,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Pipeline error: {e}", exc_info=True)
        raise HTTPException(500, f"Processing failed: {e}")
    finally:
        try:
            if audio_path and audio_path.exists(): audio_path.unlink()
            if video_path and video_path.exists(): video_path.unlink()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════
# Exception Handlers
# ══════════════════════════════════════════════════════════════════
@app.exception_handler(HTTPException)
async def http_handler(req, exc):
    return JSONResponse(content={"error": exc.detail}, status_code=exc.status_code)

@app.exception_handler(Exception)
async def general_handler(req, exc):
    logger.error(f"Unhandled: {exc}", exc_info=True)
    return JSONResponse(content={"error": "Internal server error"}, status_code=500)


# ══════════════════════════════════════════════════════════════════
# Entry Point
# ══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True, log_level="info")
