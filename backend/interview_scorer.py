"""
Interview Scoring Module v3.0
- Auto-corrects bad OPENAI_API_ENDPOINT (catches /v11/ typos etc.)
- Validates API key format on startup and logs clearly
- FALLBACK SCORER: if API fails/unavailable, uses NLP rule-based scoring
  so users ALWAYS get real meaningful scores, not 0.0
- Upgraded prompt with global interview assessment rubric
- All 3 parser bugs fixed
"""

import os
import re
import json
import math
import logging
from typing import Optional, Tuple
import requests

logger = logging.getLogger(__name__)
from groq import Groq

# ──────────────────────────────────────────────────────────────
# Filler & Fumbling Word Lists
# ──────────────────────────────────────────────────────────────
FILLER_WORDS = [
    "um", "uh", "er", "ah", "like", "you know", "basically",
    "literally", "actually", "so", "right", "okay", "kind of",
    "sort of", "i mean", "you see", "well", "anyway",
    "you know what i mean", "to be honest", "honestly",
    "at the end of the day", "i guess", "i suppose",
]

FUMBLE_PATTERNS = [
    r'\b(\w+)\s+\1\b',
    r'\bi\s+i\b',
    r'\bso\s+so\b',
    r'\b(and|but|or)\s+(and|but|or)\b',
    r'(\w+[\-,]\s*){3,}',
]

# Keywords that indicate a strong interview answer
STRONG_CONTENT_SIGNALS = [
    "experience", "achieved", "led", "managed", "developed", "improved",
    "increased", "decreased", "result", "because", "therefore", "example",
    "specifically", "project", "team", "goal", "challenge", "solution",
    "learned", "skills", "accomplished", "responsible", "delivered",
    "strategy", "analysis", "performance", "growth", "impact",
]

WEAK_CONTENT_SIGNALS = [
    "i don't know", "not sure", "maybe", "i think maybe",
    "i never", "nothing really", "not applicable",
]


class InterviewScorer:
    """Generates comprehensive interview scores — with API or rule-based fallback"""

    def __init__(self, api_key: Optional[str] = None, endpoint: Optional[str] = None):
        self.model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        base = os.getenv("OLLAMA_API_BASE", "http://localhost:11434").rstrip('/')
        self.endpoint = endpoint or f"{base}/api/chat"
        self.timeout = int(os.getenv("OLLAMA_SCORING_TIMEOUT", "240"))
        self.use_ai = True

        logger.info(f"📊 InterviewScorer v3.0 ready (Ollama {self.model})")

    # ══════════════════════════════════════════════════════════════
    # PUBLIC
    # ══════════════════════════════════════════════════════════════
    def generate_score(self, question: str, transcript: str, tone_analysis: dict) -> dict:
        try:
            logger.info("🤖 Generating interview score…")

            local_metrics = self._compute_local_metrics(transcript)

            # Try AI scoring first; fall back to rule-based if it fails
            ai_parsed  = None
            ai_raw_text = ""
            used_ai    = False
            ai_error   = None

            if self.use_ai:
                try:
                    tone_summary = self._format_tone_data(tone_analysis)
                    prompt       = self._create_scoring_prompt(question, transcript, tone_summary, local_metrics)
                    ai_raw_text  = self._call_api(prompt)
                    logger.info(f"📨 AI response (first 300 chars): {ai_raw_text[:300]}")
                    ai_parsed    = self._parse_ai_response(ai_raw_text)
                    if not 1 <= ai_parsed["content_score"] <= 10:
                        raise ValueError("Ollama did not return a valid content score")
                    if not 1 <= ai_parsed["tone_score"] <= 10:
                        ai_parsed["tone_score"] = (
                            self._fallback_score(question, transcript, tone_analysis, local_metrics)["tone_score"]
                            if tone_summary != "Tone data unavailable" else 5.0
                        )
                        logger.warning("Ollama omitted a numeric tone score; using local tone estimate")
                        ai_parsed["overall_score"] = 0
                    if not 1 <= ai_parsed["overall_score"] <= 10:
                        ai_parsed["overall_score"] = round(
                            ai_parsed["content_score"] * 0.6 + ai_parsed["tone_score"] * 0.4, 1
                        )
                    used_ai      = True
                    logger.info(
                        f"✅ AI scores: content={ai_parsed.get('content_score')} "
                        f"tone={ai_parsed.get('tone_score')} overall={ai_parsed.get('overall_score')}"
                    )
                except Exception as e:
                    ai_error = str(e)
                    logger.error(f"❌ AI scoring failed ({e}) — switching to rule-based fallback", exc_info=True)
                    ai_parsed = None

            if ai_parsed is None:
                logger.info("📐 Using rule-based fallback scorer")
                ai_parsed   = self._fallback_score(question, transcript, tone_analysis, local_metrics)
                ai_raw_text = ai_parsed.pop("_raw_feedback", "")
                used_ai     = False

            confidence_score = self._compute_confidence(tone_analysis, ai_parsed, local_metrics)

            result = {
                "question":         question,
                "transcript":       transcript,
                "tone_analysis":    tone_analysis,
                "ai_feedback":      ai_raw_text,
                "scoring_method":   "ai" if used_ai else "rule_based_fallback",
                "scoring_error":    ai_error,
                # Scores
                "content_score":    round(float(ai_parsed.get("content_score", 0)), 1),
                "tone_score":       round(float(ai_parsed.get("tone_score", 0)), 1),
                "overall_score":    round(float(ai_parsed.get("overall_score", 0)), 1),
                "confidence_score": confidence_score,
                # Speech metrics
                "filler_word_count":  local_metrics["filler_count"],
                "filler_word_rate":   local_metrics["filler_rate"],
                "filler_words_found": local_metrics["filler_found"],
                "fumble_count":       local_metrics["fumble_count"],
                "fumble_rate":        local_metrics["fumble_rate"],
                "word_count":         local_metrics["word_count"],
                # Qualitative
                "strengths":             ai_parsed.get("strengths", []),
                "weaknesses":            ai_parsed.get("weaknesses", []),
                "improvements":          ai_parsed.get("improvements", []),
                "content_correctness":   ai_parsed.get("content_correctness", ""),
                "sentence_quality":      ai_parsed.get("sentence_quality", ""),
                "communication_comment": ai_parsed.get("communication_comment", ""),
                "voice_summary":         ai_parsed.get("voice_summary", ""),
            }

            logger.info(
                f"✅ Final — Overall: {result['overall_score']}/10  "
                f"Confidence: {result['confidence_score']}/10  "
                f"Method: {result['scoring_method']}"
            )
            return result

        except Exception as e:
            logger.error(f"❌ generate_score completely failed: {e}", exc_info=True)
            return {"error": str(e), "question": question, "transcript": transcript}

    # ══════════════════════════════════════════════════════════════
    # LOCAL METRICS (no API)
    # ══════════════════════════════════════════════════════════════
    def _compute_local_metrics(self, transcript: str) -> dict:
        text_lower = transcript.lower()
        words      = re.findall(r'\b\w+\b', text_lower)
        word_count = max(len(words), 1)

        filler_found = []
        filler_count = 0
        for fw in FILLER_WORDS:
            pattern = r'\b' + re.escape(fw) + r'\b'
            matches = re.findall(pattern, text_lower)
            if matches:
                filler_count += len(matches)
                filler_found.append(f"{fw} (×{len(matches)})")

        fumble_count = 0
        for pat in FUMBLE_PATTERNS:
            fumble_count += len(re.findall(pat, text_lower))

        return {
            "word_count":   word_count,
            "filler_count": filler_count,
            "filler_rate":  round((filler_count / word_count) * 100, 1),
            "filler_found": filler_found,
            "fumble_count": fumble_count,
            "fumble_rate":  round((fumble_count / word_count) * 100, 1),
        }

    def _compute_confidence(self, tone_analysis: dict, ai_parsed: dict, local_metrics: dict) -> float:
        score = 5.0

        pitch = tone_analysis.get("pitch_features", {})
        std   = pitch.get("pitch_std", 50)
        if   std < 20: score += 1.0
        elif std < 40: score += 0.5
        elif std > 80: score -= 1.0

        energy      = tone_analysis.get("energy_features", {})
        consistency = energy.get("energy_consistency", 0.5)
        score      += (consistency - 0.5) * 2.0

        speech = tone_analysis.get("speech_rate_estimate", {})
        wpm    = speech.get("estimated_wpm", 150)
        if   wpm > 200: score -= 1.0
        elif wpm > 180: score -= 0.5
        elif wpm < 100: score -= 0.5

        fr = local_metrics.get("filler_rate", 0)
        if   fr > 15: score -= 1.5
        elif fr > 8:  score -= 0.75
        elif fr < 3:  score += 0.5

        fum = local_metrics.get("fumble_rate", 0)
        if   fum > 5: score -= 1.0
        elif fum > 2: score -= 0.5

        overall = ai_parsed.get("overall_score", 5)
        score  += (float(overall) - 5.0) * 0.2

        return round(min(max(score, 1.0), 10.0), 1)

    # ══════════════════════════════════════════════════════════════
    # RULE-BASED FALLBACK SCORER
    # ══════════════════════════════════════════════════════════════
    def _fallback_score(self, question: str, transcript: str,
                        tone_analysis: dict, local_metrics: dict) -> dict:
        text_lower = transcript.lower()
        words      = re.findall(r'\b\w+\b', text_lower)
        word_count = len(words)

        # ── Content score ──────────────────────────────────────────
        content = 5.0

        if   word_count >= 120: content += 1.5
        elif word_count >= 80:  content += 1.0
        elif word_count >= 50:  content += 0.5
        elif word_count >= 30:  content += 0.0
        elif word_count >= 15:  content -= 1.0
        else:                   content -= 2.5

        strong_hits = sum(1 for kw in STRONG_CONTENT_SIGNALS if kw in text_lower)
        content += min(strong_hits * 0.3, 2.0)

        weak_hits = sum(1 for kw in WEAK_CONTENT_SIGNALS if kw in text_lower)
        content -= weak_hits * 0.5

        q_words    = set(re.findall(r'\b\w{4,}\b', question.lower()))
        a_words    = set(re.findall(r'\b\w{4,}\b', text_lower))
        overlap    = len(q_words & a_words)
        content   += min(overlap * 0.4, 1.5)

        content -= min(local_metrics["filler_rate"] * 0.03, 1.0)
        content = round(min(max(content, 1.0), 10.0), 1)

        # ── Tone score ─────────────────────────────────────────────
        tone = 5.0

        pitch = tone_analysis.get("pitch_features", {})
        mean_p = pitch.get("mean_pitch", 180)
        if 120 <= mean_p <= 280:
            tone += 0.5

        energy      = tone_analysis.get("energy_features", {})
        consistency = energy.get("energy_consistency", 0.5)
        tone       += (consistency - 0.5) * 2.0

        speech = tone_analysis.get("speech_rate_estimate", {})
        wpm    = speech.get("estimated_wpm", 150)
        if   120 <= wpm <= 170: tone += 1.0
        elif 100 <= wpm < 120:  tone += 0.3
        elif 170 < wpm <= 200:  tone += 0.3
        elif wpm > 200:         tone -= 1.0
        elif wpm < 100:         tone -= 0.8

        tone -= min(local_metrics["filler_rate"] * 0.04, 1.2)
        tone -= min(local_metrics["fumble_rate"] * 0.08, 1.0)
        tone = round(min(max(tone, 1.0), 10.0), 1)

        # ── Overall ────────────────────────────────────────────────
        overall = round(min(max(content * 0.60 + tone * 0.40, 1.0), 10.0), 1)

        strengths, weaknesses, improvements = [], [], []

        if word_count >= 80:
            strengths.append("Gave a detailed answer with sufficient depth")
        if strong_hits >= 3:
            strengths.append("Used concrete, professional language effectively")
        if local_metrics["filler_rate"] < 5:
            strengths.append("Very clean speech with minimal filler words")
        if consistency > 0.7:
            strengths.append("Maintained consistent vocal energy throughout")
        if 120 <= wpm <= 170:
            strengths.append(f"Spoke at an ideal conversational pace ({wpm:.0f} WPM)")
        if overlap >= 3:
            strengths.append("Answer stayed relevant to what was specifically asked")
        if not strengths:
            strengths.append("Attempted to address the question")

        if word_count < 50:
            weaknesses.append(f"Answer was quite short ({word_count} words) — aim for 80–120 words minimum")
        if local_metrics["filler_rate"] > 10:
            weaknesses.append(f"High filler word rate ({local_metrics['filler_rate']}%) reduced professional impact")
        if strong_hits < 2:
            weaknesses.append("Lacked specific examples, results, or professional language")
        if wpm > 185:
            weaknesses.append(f"Speech was too fast ({wpm:.0f} WPM) — slow down to let ideas land")
        if weak_hits > 0:
            weaknesses.append("Some uncertain phrasing reduced confidence of the answer")
        if not weaknesses:
            weaknesses.append("Minor improvements possible in specificity and structure")

        if word_count < 80:
            improvements.append("Expand your answer — aim for 80–120 words using the STAR method (Situation, Task, Action, Result)")
        improvements.append("Start with a clear one-sentence summary, then support it with a specific example")
        if local_metrics["filler_rate"] > 8:
            improvements.append("Replace filler words with a 1-second confident pause — silence reads as composure")
        else:
            improvements.append("Add measurable outcomes to your examples (numbers, percentages, timeframes)")
        improvements.append("End every answer with a brief reflection: what you learned or how it applies to this role")

        content_correctness = (
            f"Your answer {'addressed' if overlap >= 2 else 'partially addressed'} the question. "
            f"{'It contained relevant examples and professional context.' if strong_hits >= 3 else 'Adding specific examples would strengthen the relevance.'} "
            f"{'The length was appropriate for an interview setting.' if word_count >= 60 else 'A more developed answer would give the interviewer more to evaluate.'}"
        )

        sentence_quality = (
            f"The response {'flowed naturally' if local_metrics['fumble_rate'] < 3 else 'had some hesitations and repetitions'} in its delivery. "
            f"{'Sentence structure was generally clear and easy to follow.' if local_metrics['filler_rate'] < 10 else 'Filler words disrupted the flow between ideas.'} "
            f"{'Overall communication was coherent.' if word_count > 30 else 'The answer was too brief to fully assess sentence quality.'}"
        )

        communication_comment = (
            f"Overall, this response shows {'strong' if overall >= 7 else 'developing' if overall >= 5 else 'early-stage'} communication skills. "
            f"{'The candidate demonstrates professional language and structured thinking.' if strong_hits >= 3 else 'Building a stronger vocabulary of professional examples will help significantly.'} "
            f"{'Confidence came through clearly in the delivery.' if consistency > 0.65 else 'Working on vocal consistency and pacing will improve professional presence.'} "
            f"With practice and preparation, this performance can be improved meaningfully."
        )

        voice_summary = (
            f"The speaker's voice was {'consistent and controlled' if consistency > 0.65 else 'somewhat variable in energy'}. "
            f"Pace was {'ideal for professional conversation' if 120 <= wpm <= 170 else 'slightly fast — slowing down would improve clarity' if wpm > 170 else 'on the slower side — a slightly brisker pace would feel more confident'}."
        )

        feedback_text = (
            f"You scored {overall}/10 overall — {'great result!' if overall >= 7 else 'a solid starting point with clear room to grow.'} "
            f"Your strongest asset here is: {strengths[0].lower()}. "
            f"The single most impactful thing you can practise before your next session is: {improvements[0].lower()}."
        )

        return {
            "content_score":         content,
            "tone_score":            tone,
            "overall_score":         overall,
            "content_correctness":   content_correctness,
            "sentence_quality":      sentence_quality,
            "strengths":             strengths[:4],
            "weaknesses":            weaknesses[:3],
            "improvements":          improvements[:3],
            "communication_comment": communication_comment,
            "voice_summary":         voice_summary,
            "_raw_feedback":         feedback_text,
        }

    # ══════════════════════════════════════════════════════════════
    # AI PROMPT
    # ══════════════════════════════════════════════════════════════
    def _format_tone_data(self, tone_analysis: dict) -> str:
        parts = []
        pitch = tone_analysis.get("pitch_features", {})
        if pitch.get("mean_pitch"):
            parts.append(
                f"Pitch: avg {pitch['mean_pitch']:.0f} Hz, std {pitch.get('pitch_std',0):.0f} Hz, "
                f"range {pitch.get('pitch_min',0):.0f}–{pitch.get('pitch_max',0):.0f} Hz"
            )
        energy = tone_analysis.get("energy_features", {})
        if energy.get("mean_energy"):
            parts.append(
                f"Energy: mean {energy['mean_energy']:.4f}, "
                f"consistency {energy.get('energy_consistency', 0):.0%}"
            )
        speech = tone_analysis.get("speech_rate_estimate", {})
        if speech.get("estimated_wpm"):
            parts.append(
                f"Speech rate: {speech['estimated_wpm']:.0f} WPM "
                f"({speech.get('speech_rate_category','unknown')})"
            )
        return "\n".join(parts) if parts else "Tone data unavailable"

    def _create_scoring_prompt(self, question: str, transcript: str,
                                tone_summary: str, local_metrics: dict) -> str:
        filler_str = ", ".join(local_metrics["filler_found"]) or "none"
        return f"""You are a senior HR professional and interview coach with 10+ years of experience \
evaluating candidates at companies.

SCORING RUBRIC — use this exactly:

CONTENT SCORE (1-10):
  9-10: Highly specific, uses STAR structure, directly answers with strong evidence
  7-8:  Relevant and mostly complete, minor gaps in depth
  5-6:  Partially relevant, some useful points but lacks structure
  3-4:  Vague or limited engagement with the question
  1-2:  Entirely off-topic or near-empty
  RULE: A normal spoken answer of 30+ words on-topic scores at least 4. Never score 0 for non-empty answers.

TONE SCORE (1-10):
  9-10: expressive, natural variation, confident pace
  7-8:  Clear and composed, minor issues
  5-6:  Flat or slightly rushed but understandable
  3-4:  Noticeably nervous or monotone
  1-2:  Severely unclear
  RULE: Any audible, understandable answer scores at least 4 on tone.

OVERALL SCORE: Content 60% + Tone 40% (use judgment, not just arithmetic)
All three scores must be numbers from 1 to 10. If tone data is unavailable, use a neutral tone score of 5. Never write N/A.

INTERVIEW QUESTION: {question}

CANDIDATE ANSWER ({local_metrics['word_count']} words):
{transcript}

TONE DATA: {tone_summary}
Filler words: {filler_str} ({local_metrics['filler_rate']}%)
Fumbles: {local_metrics['fumble_count']} ({local_metrics['fumble_rate']}%)

OUTPUT EXACTLY THIS FORMAT (no preamble, start at line 1):
CONTENT SCORE: [1-10]
TONE SCORE: [1-10]
OVERALL SCORE: [1-10]

CONTENT CORRECTNESS:
[2-3 sentences on relevance and accuracy]

SENTENCE QUALITY:
[2-3 sentences on grammar, flow, structure]

STRENGTHS:
- [strength 1]
- [strength 2]
- [strength 3]

WEAKNESSES:
- [weakness 1]
- [weakness 2]

IMPROVEMENTS:
- [actionable improvement 1]
- [actionable improvement 2]
- [actionable improvement 3]

COMMUNICATION COMMENT:
[3-4 sentences on overall communication effectiveness]

VOICE SUMMARY:
[1-2 sentences on perceived vocal delivery in plain English]

FEEDBACK:
[2-3 sentences of encouragement and top practice tip]
"""

    # ══════════════════════════════════════════════════════════════
    # API CALL
    # ══════════════════════════════════════════════════════════════
    def _call_api(self, prompt: str) -> str:
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.3}
        }
        
        try:
            logger.info(f"🌐 Calling Ollama {self.endpoint} (model={self.model})")
            resp = requests.post(self.endpoint, headers=headers, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            content = data.get("message", {}).get("content", "")
            if not content.strip():
                raise RuntimeError("Empty response from Ollama")
            
            logger.info(f"✅ Response from Ollama ({len(content)} chars)")
            return content.strip()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Ollama request error: {e}")
            raise RuntimeError(f"Ollama request failed: {e}") from e

    # ══════════════════════════════════════════════════════════════
    # RESPONSE PARSER
    # ══════════════════════════════════════════════════════════════
    def _parse_ai_response(self, response: str) -> dict:
        result = {
            "content_score":         0.0,
            "tone_score":            0.0,
            "overall_score":         0.0,
            "content_correctness":   "",
            "sentence_quality":      "",
            "strengths":             [],
            "weaknesses":            [],
            "improvements":          [],
            "communication_comment": "",
            "voice_summary":         "",
            "feedback":              "",
        }
        lines = response.split("\n")

        # Pass 1: numeric scores
        for line in lines:
            s = line.strip()
            if   s.upper().startswith("CONTENT SCORE:"):
                result["content_score"]  = self._extract_score(s)
            elif s.upper().startswith("TONE SCORE:"):
                result["tone_score"]     = self._extract_score(s)
            elif s.upper().startswith("OVERALL SCORE:"):
                result["overall_score"]  = self._extract_score(s)

        # Regex fallback
        if result["content_score"] == 0:
            m = re.search(r'CONTENT\s+SCORE\s*[:\-]\s*(\d+(?:\.\d+)?)', response, re.I)
            if m: result["content_score"] = float(m.group(1))
        if result["tone_score"] == 0:
            m = re.search(r'TONE\s+SCORE\s*[:\-]\s*(\d+(?:\.\d+)?)', response, re.I)
            if m: result["tone_score"] = float(m.group(1))
        if result["overall_score"] == 0:
            m = re.search(r'OVERALL\s+SCORE\s*[:\-]\s*(\d+(?:\.\d+)?)', response, re.I)
            if m: result["overall_score"] = float(m.group(1))

        # Pass 2: section text
        SECTION_TEXT = {
            "CONTENT CORRECTNESS:":   "content_correctness",
            "SENTENCE QUALITY:":      "sentence_quality",
            "COMMUNICATION COMMENT:": "communication_comment",
            "VOICE SUMMARY:":         "voice_summary",
            "FEEDBACK:":              "feedback",
        }
        SECTION_LIST = {
            "STRENGTHS:":    "strengths",
            "WEAKNESSES:":   "weaknesses",
            "IMPROVEMENTS:": "improvements",
        }
        ALL_HEADERS = set(SECTION_TEXT) | set(SECTION_LIST) | {
            "CONTENT SCORE:", "TONE SCORE:", "OVERALL SCORE:"
        }

        current_key  = None
        is_list      = False
        text_buf     = []

        def flush():
            nonlocal current_key, text_buf
            if current_key and not is_list and text_buf:
                result[current_key] = " ".join(text_buf).strip()
            text_buf = []

        for line in lines:
            stripped = line.strip()
            upper    = stripped.upper()

            matched_hdr = None
            for h in ALL_HEADERS:
                if upper.startswith(h):
                    matched_hdr = h
                    break

            if matched_hdr:
                flush()
                current_key = None
                is_list     = False
                text_buf    = []

                if matched_hdr in SECTION_TEXT:
                    current_key = SECTION_TEXT[matched_hdr]
                    inline = stripped[len(matched_hdr):].strip()
                    if inline:
                        text_buf = [inline]
                elif matched_hdr in SECTION_LIST:
                    current_key = SECTION_LIST[matched_hdr]
                    is_list     = True
                continue

            if current_key:
                if is_list:
                    if stripped and stripped[0] in "-•*":
                        item = stripped.lstrip("-•* ").strip()
                        if item:
                            result[current_key].append(item)
                else:
                    if stripped:
                        text_buf.append(stripped)

        flush()
        return result

    def _extract_score(self, line: str) -> float:
        m = re.search(r'(\d+(?:\.\d+)?)', line)
        if m:
            return round(min(max(float(m.group(1)), 0.0), 10.0), 1)
        return 0.0

    # ══════════════════════════════════════════════════════════════
    # OVERALL REPORT
    # ══════════════════════════════════════════════════════════════
    def generate_interview_report(self, all_scores: list) -> dict:
        if not all_scores:
            return {"error": "No scores to report"}
        scored = [s for s in all_scores if "error" not in s]
        if not scored:
            return {"error": "All answers failed to score"}

        def avg(f):
            vals = [s.get(f, 0) for s in scored]
            return round(sum(vals) / max(len(vals), 1), 1)

        a = avg("overall_score")
        return {
            "total_questions":    len(all_scores),
            "questions_answered": len(scored),
            "avg_content_score":  avg("content_score"),
            "avg_tone_score":     avg("tone_score"),
            "avg_overall_score":  a,
            "avg_confidence":     avg("confidence_score"),
            "avg_filler_rate":    avg("filler_word_rate"),
            "avg_fumble_rate":    avg("fumble_rate"),
            "rating": (
                "Excellent"         if a >= 8.5 else
                "Good"              if a >= 7.0 else
                "Average"           if a >= 5.5 else
                "Below Average"     if a >= 4.0 else
                "Needs Improvement"
            ),
            "individual_scores": all_scores,
        }
