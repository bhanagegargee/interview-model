"""
Video Analysis Module - Analyzes body language, posture, and eye contact
Uses MediaPipe and OpenCV for feature extraction
Integrates with OpenAI API for professional assessment
"""

import cv2
import mediapipe as mp
import numpy as np
import math
import json
import logging
import os
from typing import Optional
import requests

logger = logging.getLogger(__name__)
from groq import Groq


class InterviewFeatureExtractor:
    """Extracts body language features from interview video"""

    def __init__(self, video_path: str):
        self.video_path = video_path

        self.mp_pose     = mp.solutions.pose
        self.mp_face_mesh = mp.solutions.face_mesh
        self.pose      = self.mp_pose.Pose(static_image_mode=False, min_detection_confidence=0.5)
        self.face_mesh = self.mp_face_mesh.FaceMesh(static_image_mode=False, min_detection_confidence=0.5)

        self.total_frames      = 0
        self.eye_contact_frames = 0
        self.shoulder_angles   = []
        self.spine_angles      = []

    def calculate_angle(self, p1, p2):
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        return math.degrees(math.atan2(dy, dx))

    def process_eye_contact(self, face_landmarks):
        LEFT_EYE  = 33
        RIGHT_EYE = 263
        NOSE      = 1

        left_eye  = face_landmarks.landmark[LEFT_EYE]
        right_eye = face_landmarks.landmark[RIGHT_EYE]
        nose      = face_landmarks.landmark[NOSE]

        eye_center_x = (left_eye.x + right_eye.x) / 2
        nose_x       = nose.x

        eye_offset  = abs(eye_center_x - 0.5)
        nose_offset = abs(nose_x - 0.5)

        return eye_offset < 0.07 and nose_offset < 0.08

    def process_pose(self, pose_landmarks, frame_width, frame_height):
        LEFT_SHOULDER  = self.mp_pose.PoseLandmark.LEFT_SHOULDER.value
        RIGHT_SHOULDER = self.mp_pose.PoseLandmark.RIGHT_SHOULDER.value
        NOSE           = self.mp_pose.PoseLandmark.NOSE.value

        left_shoulder  = pose_landmarks.landmark[LEFT_SHOULDER]
        right_shoulder = pose_landmarks.landmark[RIGHT_SHOULDER]
        nose           = pose_landmarks.landmark[NOSE]

        l_sh   = (int(left_shoulder.x * frame_width),  int(left_shoulder.y * frame_height))
        r_sh   = (int(right_shoulder.x * frame_width), int(right_shoulder.y * frame_height))
        nose_pt = (int(nose.x * frame_width),           int(nose.y * frame_height))

        shoulder_angle = self.calculate_angle(l_sh, r_sh)
        self.shoulder_angles.append(abs(shoulder_angle))

        mid_shoulder = ((l_sh[0] + r_sh[0]) // 2, (l_sh[1] + r_sh[1]) // 2)
        spine_angle  = self.calculate_angle(mid_shoulder, nose_pt)
        self.spine_angles.append(abs(spine_angle))

    def process_video(self):
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            raise Exception(f"Cannot open video file: {self.video_path}")

        logger.info(f"📹 Processing video: {self.video_path}")

        while cap.isOpened():
            success, frame = cap.read()
            if not success:
                break

            self.total_frames += 1
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            pose_results = self.pose.process(rgb)
            face_results = self.face_mesh.process(rgb)
            height, width, _ = frame.shape

            
            if face_results.multi_face_landmarks:
                for face_landmarks in face_results.multi_face_landmarks:
                    if self.process_eye_contact(face_landmarks):
                        self.eye_contact_frames += 1

            if pose_results.pose_landmarks:
                self.process_pose(pose_results.pose_landmarks, width, height)

        cap.release()
        logger.info(f"✅ Video processed: {self.total_frames} frames")
        return self.generate_results()

    def generate_results(self):
        eye_contact_rate = 0
        if self.total_frames > 0:
            eye_contact_rate = self.eye_contact_frames / self.total_frames

        avg_shoulder = np.mean(self.shoulder_angles) if self.shoulder_angles else 0
        avg_spine    = np.mean(self.spine_angles)    if self.spine_angles    else 0

        return {
            "eye_contact_rate":       round(eye_contact_rate, 3),
            "avg_shoulder_alignment": round(avg_shoulder, 2),
            "avg_spine_angle":        round(avg_spine, 2),
            "total_frames":           self.total_frames,
            "eye_contact_frames":     self.eye_contact_frames,
        }


class VideoAnalyzer:
    """High-level interface for video analysis with OpenAI API assessment"""

    def __init__(self, api_key: Optional[str] = None, endpoint: Optional[str] = None):
        self.model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        base = os.getenv("OLLAMA_API_BASE", "http://localhost:11434").rstrip('/')
        self.endpoint = endpoint or f"{base}/api/chat"
        self.timeout = int(os.getenv("OLLAMA_VIDEO_TIMEOUT", "240"))
        self.use_ai = True

        logger.info(f"✅ VideoAnalyzer ready (Ollama {self.model})")

    def analyze_video(self, video_path: str) -> dict:
        try:
            logger.info(f"🎥 Starting video analysis: {video_path}")

            extractor = InterviewFeatureExtractor(video_path)
            metrics   = extractor.process_video()

            logger.info(
                f"📊 Metrics: eye_contact={metrics['eye_contact_rate']:.1%} "
                f"shoulder={metrics['avg_shoulder_alignment']:.1f}° "
                f"spine={metrics['avg_spine_angle']:.1f}°"
            )

            assessment = {}
            if self.use_ai:
                try:
                    assessment = self._generate_ai_assessment(metrics)
                    logger.info("✅ AI assessment complete")
                except Exception as e:
                    logger.error(f"❌ AI assessment failed: {e}")
                    assessment = self._fallback_assessment(metrics)
                    assessment["_ai_error"] = str(e)
            else:
                assessment = self._fallback_assessment(metrics)
                logger.info("📐 Using rule-based assessment (no API key)")

            return {
                "raw_metrics":     metrics,
                "assessment":      assessment,
                "analysis_method": "ai" if (self.use_ai and "_ai_error" not in assessment) else "rule_based",
            }

        except Exception as e:
            logger.error(f"❌ Video analysis failed: {e}", exc_info=True)
            return {"error": str(e)}

    def _generate_ai_assessment(self, metrics: dict) -> dict:
        eye_contact_pct = round(metrics['eye_contact_rate'] * 100, 2)

        prompt = f"""You are a Professional Interview Communication Coach.

Analyze the following body language metrics from a video interview:

- Eye Contact Rate: {eye_contact_pct}%
- Shoulder Alignment Angle: {metrics['avg_shoulder_alignment']}° (closer to 0° = more level)
- Spine Angle: {metrics['avg_spine_angle']}° (90° = upright, <90° = leaning forward)

Return ONLY valid JSON in this exact format (no markdown, no extra text):

{{
  "overall_assessment": "2-3 sentence summary of body language and non-verbal communication",
  "eye_contact_analysis": {{
      "rating": "Strong/Moderate/Needs Improvement",
      "analysis": "Detailed explanation of eye contact patterns and what they convey"
  }},
  "posture_analysis": {{
      "rating": "Good/Moderate/Needs Improvement",
      "analysis": "Detailed explanation of posture, alignment, and physical presence"
  }},
  "strengths": [
      "Specific body language strength 1",
      "Specific body language strength 2"
  ],
  "areas_for_improvement": [
      "Specific area needing work 1",
      "Specific area needing work 2"
  ],
  "improvement_recommendations": [
      "Actionable recommendation 1",
      "Actionable recommendation 2",
      "Actionable recommendation 3"
  ],
  "confidence_projection_score": 7.5
}}

CRITICAL: Return ONLY the JSON object. No markdown code blocks. No explanatory text.
"""

        headers = {"Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.3}
        }

        logger.info(f"🌐 Calling Ollama for video assessment (model={self.model})")
        resp = requests.post(self.endpoint, headers=headers, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()

        content = data.get("message", {}).get("content", "").strip()
        if not content:
            raise RuntimeError("Empty content from Ollama response")

        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content
            content = content.rsplit("```", 1)[0] if "```" in content else content

        result = json.loads(content)
        logger.info("✅ Parsed Ollama JSON successfully")
        return result

    def _fallback_assessment(self, metrics: dict) -> dict:
        """Rule-based assessment when API is unavailable"""
        eye_rate = metrics['eye_contact_rate']
        shoulder = metrics['avg_shoulder_alignment']
        spine    = metrics['avg_spine_angle']

        if eye_rate >= 0.70:
            eye_rating   = "Strong"
            eye_analysis = f"Maintained excellent eye contact ({eye_rate:.0%}) — projects confidence and engagement."
        elif eye_rate >= 0.50:
            eye_rating   = "Moderate"
            eye_analysis = f"Eye contact was present ({eye_rate:.0%}) but inconsistent. Aim for 70%+ to project stronger confidence."
        else:
            eye_rating   = "Needs Improvement"
            eye_analysis = f"Eye contact was infrequent ({eye_rate:.0%}). Practice maintaining gaze to signal engagement."

        shoulder_ok = abs(shoulder) < 5
        spine_ok    = 75 <= spine <= 95

        if shoulder_ok and spine_ok:
            posture_rating   = "Good"
            posture_analysis = f"Posture was upright with level shoulders (shoulder: {shoulder:.1f}°, spine: {spine:.1f}°). Projects professionalism."
        elif shoulder_ok or spine_ok:
            posture_rating   = "Moderate"
            posture_analysis = f"Posture was acceptable but showed some asymmetry (shoulder: {shoulder:.1f}°, spine: {spine:.1f}°)."
        else:
            posture_rating   = "Needs Improvement"
            posture_analysis = f"Posture needs attention (shoulder: {shoulder:.1f}°, spine: {spine:.1f}°). Slouching can reduce professional presence."

        strengths        = []
        improvements     = []
        recommendations  = []

        if eye_rate >= 0.60:
            strengths.append(f"Good eye contact maintained ({eye_rate:.0%})")
        else:
            improvements.append(f"Eye contact was below 60% — currently {eye_rate:.0%}")
            recommendations.append("Look directly at the camera lens for at least 70% of your answer")

        if shoulder_ok:
            strengths.append(f"Shoulders were well-aligned (±{shoulder:.1f}°)")
        else:
            improvements.append(f"Shoulder alignment was off by {shoulder:.1f}°")
            recommendations.append("Sit back in your chair and relax your shoulders so they are level")

        if spine_ok:
            strengths.append(f"Spine was upright at {spine:.1f}°")
        else:
            improvements.append(f"Spine angle suggests slouching or leaning ({spine:.1f}°)")
            recommendations.append("Sit upright at ~85-90° — imagine a string gently pulling you up from the crown")

        if not recommendations:
            recommendations.append("Continue to maintain this strong body language in every interview")

        conf_score = 5.0
        conf_score += (eye_rate - 0.5) * 8.0
        conf_score += 1.0 if shoulder_ok else -0.5
        conf_score += 1.0 if spine_ok    else -0.5
        conf_score = round(min(max(conf_score, 1.0), 10.0), 1)

        overall = (
            f"Body language analysis shows {posture_rating.lower()} posture and {eye_rating.lower()} eye contact. "
            f"{'Strong' if conf_score >= 7 else 'Moderate' if conf_score >= 5 else 'Developing'} "
            f"non-verbal communication presence overall. "
            f"{'Great foundation to build on.' if conf_score >= 6 else 'Targeted practice will significantly improve your professional presence.'}"
        )

        return {
            "overall_assessment":        overall,
            "eye_contact_analysis":      {"rating": eye_rating,     "analysis": eye_analysis},
            "posture_analysis":          {"rating": posture_rating,  "analysis": posture_analysis},
            "strengths":                 strengths,
            "areas_for_improvement":     improvements,
            "improvement_recommendations": recommendations,
            "confidence_projection_score": conf_score,
        }
