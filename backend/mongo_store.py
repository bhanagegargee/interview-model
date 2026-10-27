import logging
import os
from datetime import datetime, timezone
from typing import Any

from pymongo import MongoClient
from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)


class MongoStore:
    """Small data-access layer for local MongoDB persistence."""

    def __init__(self) -> None:
        self.enabled = False
        self.client: MongoClient | None = None
        self.db = None
        self.candidates = None
        self.sessions = None

        uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017").strip()
        db_name = os.getenv("MONGODB_DB", "ai_interview").strip() or "ai_interview"

        try:
            self.client = MongoClient(uri, serverSelectionTimeoutMS=3000)
            self.client.admin.command("ping")
            self.db = self.client[db_name]
            self.candidates = self.db["candidates"]
            self.sessions = self.db["interview_sessions"]
            self._ensure_indexes()
            self.enabled = True
            logger.info("✅ MongoDB connected: %s / %s", uri, db_name)
        except Exception as e:
            logger.warning("⚠️ MongoDB unavailable (%s). Running without DB persistence.", e)

    def _ensure_indexes(self) -> None:
        if not self.enabled:
            return
        self.candidates.create_index("email", unique=True)
        self.sessions.create_index("session_id", unique=True)
        self.sessions.create_index("candidate_email")

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def session_id_from_email(email: str) -> str:
        return email.strip().lower()

    def upsert_candidate(self, candidate_data: dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            email = candidate_data["email"].strip().lower()
            payload = {
                "name": candidate_data["name"].strip(),
                "email": email,
                "qualification": candidate_data["qualification"].strip(),
                "job_description": candidate_data["job_description"].strip(),
                "question_count": int(candidate_data.get("question_count", 5)),
                "updated_at": self._now(),
            }
            self.candidates.update_one(
                {"email": email},
                {"$set": payload, "$setOnInsert": {"created_at": self._now()}},
                upsert=True,
            )
        except (KeyError, ValueError, PyMongoError) as e:
            logger.warning("Candidate upsert failed: %s", e)

    def save_session_questions(
        self,
        candidate_email: str,
        candidate_name: str,
        questions: list[str],
        timings_ms: list[int],
        generation_method: str,
    ) -> str:
        session_id = self.session_id_from_email(candidate_email)
        if not self.enabled:
            return session_id

        try:
            self.sessions.update_one(
                {"session_id": session_id},
                {
                    "$set": {
                        "session_id": session_id,
                        "candidate_email": candidate_email.strip().lower(),
                        "candidate_name": candidate_name.strip(),
                        "questions": questions,
                        "timings_ms": timings_ms,
                        "generation_method": generation_method,
                        "updated_at": self._now(),
                    },
                    "$setOnInsert": {
                        "created_at": self._now(),
                        "answers": [],
                    },
                },
                upsert=True,
            )
        except PyMongoError as e:
            logger.warning("Session question save failed: %s", e)

        return session_id

    def append_answer(
        self,
        *,
        session_id: str,
        candidate_email: str,
        question_number: int | None,
        question: str,
        transcript: str,
        tone_analysis: dict[str, Any] | None,
        ai_score: dict[str, Any] | None,
        video_analysis: dict[str, Any] | None,
    ) -> None:
        if not self.enabled:
            return

        answer_doc = {
            "question_number": question_number,
            "question": question,
            "transcript": transcript,
            "tone_analysis": tone_analysis or {},
            "ai_score": ai_score or {},
            "video_analysis": video_analysis or {},
            "created_at": self._now(),
        }

        try:
            self.sessions.update_one(
                {"session_id": session_id},
                {
                    "$setOnInsert": {
                        "session_id": session_id,
                        "candidate_email": candidate_email.strip().lower(),
                        "created_at": self._now(),
                        "questions": [],
                        "timings_ms": [],
                        "answers": [],
                    },
                    "$set": {"updated_at": self._now()},
                    "$push": {"answers": answer_doc},
                },
                upsert=True,
            )
        except PyMongoError as e:
            logger.warning("Answer append failed: %s", e)
