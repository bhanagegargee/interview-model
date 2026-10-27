"""
Tone Analysis Module - Analyzes speaker's tone, emotion, and speech patterns
Uses librosa for audio feature extraction
"""

import librosa
import numpy as np
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class ToneAnalyzer:
    """Analyzes audio files for tone, emotion, and speech characteristics"""
    
    def __init__(self):
        self.sr = 22050  # Standard sample rate for librosa
    
    def analyze_audio(self, file_path: str) -> dict:
        """
        Analyze audio file and extract tone/emotion features
        
        Args:
            file_path: Path to audio file
            
        Returns:
            dict: Tone analysis results including pitch, energy, speech rate, etc.
        """
        try:
            logger.info(f"📊 Starting tone analysis on: {file_path}")
            
            # Load audio file
            y, sr = librosa.load(file_path, sr=self.sr)
            logger.info(f"Audio loaded: {len(y)} samples at {sr}Hz")
            
            if len(y) == 0:
                logger.warning("⚠️ Audio file is empty")
                return {"error": "Audio file appears to be empty"}
            
            # Extract tone features
            analysis = {
                "pitch_features": self._extract_pitch_features(y, sr),
                "energy_features": self._extract_energy_features(y),
                "speech_rate_estimate": self._estimate_speech_rate(y, sr),
                "tempo": self._extract_tempo(y, sr),
                "mfcc_features": self._extract_mfcc_features(y, sr),
                "spectral_features": self._extract_spectral_features(y, sr),
                "zero_crossing_rate": self._extract_zero_crossing_rate(y),
            }
            
            logger.info("✅ Tone analysis completed successfully")
            return analysis
            
        except Exception as e:
            logger.error(f"❌ Error in tone analysis: {str(e)}")
            return {"error": str(e)}
    
    def _extract_pitch_features(self, y: np.ndarray, sr: int) -> dict:
        """Extract pitch-related features"""
        try:
            # Use librosa's piptrack for pitch tracking
            f0 = librosa.yin(y, fmin=80, fmax=400)  # Human speech range
            
            # Calculate pitch statistics
            f0_valid = f0[f0 > 0]  # Filter out unvoiced frames (pitch = 0)
            
            if len(f0_valid) == 0:
                return {
                    "mean_pitch": 0,
                    "pitch_variance": 0,
                    "pitch_range": (0, 0),
                    "status": "insufficient_voiced_segments"
                }
            
            pitch_stats = {
                "mean_pitch": float(np.mean(f0_valid)),
                "pitch_std": float(np.std(f0_valid)),
                "pitch_min": float(np.min(f0_valid)),
                "pitch_max": float(np.max(f0_valid)),
                "pitch_range": (float(np.min(f0_valid)), float(np.max(f0_valid))),
                "pitch_variance": float(np.var(f0_valid))
            }
            
            logger.info(f"🎵 Pitch stats: Mean={pitch_stats['mean_pitch']:.1f}Hz, Range={pitch_stats['pitch_range']}")
            return pitch_stats
            
        except Exception as e:
            logger.warning(f"⚠️ Could not extract pitch features: {e}")
            return {"error": str(e), "status": "pitch_extraction_failed"}
    
    def _extract_energy_features(self, y: np.ndarray) -> dict:
        """Extract energy/loudness features"""
        try:
            # RMS Energy
            S = librosa.feature.melspectrogram(y=y)
            log_S = librosa.power_to_db(S, ref=np.max)
            
            # Compute energy
            energy = np.var(y)  # Energy as variance
            rms = librosa.feature.rms(y=y)[0]
            
            energy_stats = {
                "mean_energy": float(np.mean(rms)),
                "energy_std": float(np.std(rms)),
                "energy_min": float(np.min(rms)),
                "energy_max": float(np.max(rms)),
                "total_energy": float(energy),
                "energy_consistency": float(1 - (np.std(rms) / (np.mean(rms) + 1e-8)))  # Lower variance = more consistent
            }
            
            logger.info(f"⚡ Energy stats: Mean={energy_stats['mean_energy']:.4f}, Consistency={energy_stats['energy_consistency']:.2f}")
            return energy_stats
            
        except Exception as e:
            logger.warning(f"⚠️ Could not extract energy features: {e}")
            return {"error": str(e)}
    
    def _estimate_speech_rate(self, y: np.ndarray, sr: int) -> dict:
        """Estimate speech rate (words per minute equivalent)"""
        try:
            # Detect onsets (syllable-like events)
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)
            onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, units='time')
            
            # Duration of audio
            duration = len(y) / sr
            
            # Estimate syllables (onsets per second)
            syllable_rate = len(onsets) / duration if duration > 0 else 0
            
            # Rough estimate: ~4-5 syllables per word, speech rate typically 150-160 WPM
            estimated_wpm = (syllable_rate / 4.5) * 60
            
            speech_rate_stats = {
                "detected_onsets": int(len(onsets)),
                "syllable_rate_per_sec": float(syllable_rate),
                "estimated_wpm": float(estimated_wpm),
                "duration_seconds": float(duration),
                "speech_rate_category": self._categorize_speech_rate(estimated_wpm)
            }
            
            logger.info(f"🗣️ Speech rate: {estimated_wpm:.0f} WPM ({speech_rate_stats['speech_rate_category']})")
            return speech_rate_stats
            
        except Exception as e:
            logger.warning(f"⚠️ Could not estimate speech rate: {e}")
            return {"error": str(e)}
    
    def _categorize_speech_rate(self, wpm: float) -> str:
        """Categorize speech rate"""
        if wpm < 120:
            return "slow"
        elif wpm < 150:
            return "normal"
        elif wpm < 180:
            return "fast"
        else:
            return "very_fast"
    
    def _extract_tempo(self, y: np.ndarray, sr: int) -> dict:
        """Extract tempo information"""
        try:
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)
            tempo, beats = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
            
            return {
                "estimated_tempo": float(tempo),
                "beat_count": int(len(beats))
            }
        except Exception as e:
            logger.warning(f"⚠️ Could not extract tempo: {e}")
            return {"error": str(e)}
    
    def _extract_mfcc_features(self, y: np.ndarray, sr: int) -> dict:
        """Extract MFCCs (Mel-Frequency Cepstral Coefficients) - important for voice quality"""
        try:
            mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
            
            mfcc_stats = {
                "mfcc_mean": mfcc.mean(axis=1).tolist(),  # Mean for each coefficient
                "mfcc_std": mfcc.std(axis=1).tolist(),     # Std dev for each coefficient
                "mfcc_overall_mean": float(np.mean(mfcc)),
                "mfcc_overall_std": float(np.std(mfcc))
            }
            
            logger.info(f"🎚️ MFCC extracted: {len(mfcc)} coefficients")
            return mfcc_stats
            
        except Exception as e:
            logger.warning(f"⚠️ Could not extract MFCC features: {e}")
            return {"error": str(e)}
    
    def _extract_spectral_features(self, y: np.ndarray, sr: int) -> dict:
        """Extract spectral features (frequency content)"""
        try:
            # Spectral centroid - weighted mean of frequencies
            spectral_centroid = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
            
            # Spectral rolloff - frequency below which 85% of energy is concentrated
            spectral_rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)[0]
            
            spec_stats = {
                "spectral_centroid_mean": float(np.mean(spectral_centroid)),
                "spectral_centroid_std": float(np.std(spectral_centroid)),
                "spectral_rolloff_mean": float(np.mean(spectral_rolloff)),
                "spectral_rolloff_std": float(np.std(spectral_rolloff))
            }
            
            logger.info(f"📈 Spectral centroid: {spec_stats['spectral_centroid_mean']:.0f}Hz")
            return spec_stats
            
        except Exception as e:
            logger.warning(f"⚠️ Could not extract spectral features: {e}")
            return {"error": str(e)}
    
    def _extract_zero_crossing_rate(self, y: np.ndarray) -> dict:
        """Extract zero crossing rate - indicates noise/fricatives"""
        try:
            zcr = librosa.feature.zero_crossing_rate(y)[0]
            
            zcr_stats = {
                "zcr_mean": float(np.mean(zcr)),
                "zcr_std": float(np.std(zcr)),
                "zcr_min": float(np.min(zcr)),
                "zcr_max": float(np.max(zcr))
            }
            
            return zcr_stats
            
        except Exception as e:
            logger.warning(f"⚠️ Could not extract zero crossing rate: {e}")
            return {"error": str(e)}
    
    def create_tone_summary(self, analysis: dict) -> str:
        """Create a human-readable summary of tone analysis"""
        try:
            pitch = analysis.get("pitch_features", {})
            energy = analysis.get("energy_features", {})
            speech = analysis.get("speech_rate_estimate", {})
            
            summary_parts = []
            
            # Pitch assessment
            if pitch.get("mean_pitch"):
                pitch_val = pitch["mean_pitch"]
                if pitch_val < 150:
                    summary_parts.append("• Deep, low-pitched voice (professional, authoritative)")
                elif pitch_val < 250:
                    summary_parts.append("• Normal pitch range (natural, engaging)")
                else:
                    summary_parts.append("• Higher-pitched voice (enthusiastic, energetic)")
            
            # Energy assessment
            if energy.get("energy_consistency"):
                consistency = energy["energy_consistency"]
                if consistency > 0.8:
                    summary_parts.append("• Consistent volume throughout (composed, controlled)")
                elif consistency > 0.6:
                    summary_parts.append("• Moderate volume variation (natural delivery)")
                else:
                    summary_parts.append("• High volume variation (emotional or uncertain)")
            
            # Speech rate assessment
            if speech.get("estimated_wpm"):
                wpm = speech["estimated_wpm"]
                summary_parts.append(f"• Speech rate: {wpm:.0f} WPM ({speech.get('speech_rate_category', 'unknown')})")
            
            return "\n".join(summary_parts) if summary_parts else "Unable to generate tone summary"
            
        except Exception as e:
            logger.error(f"Error creating tone summary: {e}")
            return "Error generating summary"
