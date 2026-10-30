"""
Voice authentication and speaker verification service.

Implements Resemblyzer GE2E voice embedding extraction, cosine similarity
comparison against enrolled profiles, threshold validation, and Vosk offline
speech-to-text transcription.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import logging
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from app.core.config import settings

logger = logging.getLogger(__name__)

# Lazy singleton models and lock
_lock = threading.Lock()
_encoder = None
_vosk_model = None


def get_voice_encoder():
    """Lazy-load the Resemblyzer VoiceEncoder model."""
    global _encoder
    if _encoder is None:
        with _lock:
            if _encoder is None:
                from resemblyzer import VoiceEncoder
                logger.info("Loading Resemblyzer voice encoder...")
                _encoder = VoiceEncoder()
                logger.info("Resemblyzer voice encoder loaded successfully.")
    return _encoder


def get_vosk_model():
    """Lazy-load the Vosk offline speech recognition model."""
    global _vosk_model
    if _vosk_model is None:
        with _lock:
            if _vosk_model is None:
                from vosk import Model
                model_dir = settings.get_vosk_model_path()
                if not model_dir.is_dir():
                    raise FileNotFoundError(
                        f"Vosk model directory not found at {model_dir}"
                    )
                logger.info("Loading Vosk speech recognition model from %s...", model_dir)
                _vosk_model = Model(str(model_dir))
                logger.info("Vosk model loaded successfully.")
    return _vosk_model


class VoiceAuthService:
    """Service handling speaker enrollment, verification, and audio transcription."""

    def __init__(self) -> None:
        pass

    # ── Profile Management ──────────────────────────────────────────────────

    def is_enrolled(self) -> bool:
        """Check whether an enrolled voice profile exists and is non-empty."""
        path = settings.get_enrolled_voice_path()
        return path.is_file() and path.stat().st_size > 0

    def get_enrolled_path(self) -> Path:
        """Return the path to the enrolled voice profile file."""
        return settings.get_enrolled_voice_path()

    def load_enrolled_embedding(self) -> np.ndarray | None:
        """Load and return the enrolled speaker embedding vector."""
        if not self.is_enrolled():
            return None
        try:
            path = self.get_enrolled_path()
            embedding = np.load(path)
            if embedding.ndim != 1 or embedding.shape[0] != 256:
                logger.warning("Enrolled embedding has invalid shape %s", embedding.shape)
                return None
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm
            return embedding
        except Exception as err:
            logger.error("Failed to load enrolled embedding: %s", err)
            return None

    def save_enrolled_embedding(self, embedding: np.ndarray) -> bool:
        """Save normalized embedding to disk atomically."""
        try:
            path = self.get_enrolled_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm

            # Atomic write via temp file in the same directory
            temp_file = tempfile.NamedTemporaryFile(
                dir=str(path.parent), delete=False, suffix=".npy"
            )
            temp_path = Path(temp_file.name)
            temp_file.close()

            np.save(temp_path, embedding)
            temp_path.replace(path)
            return True
        except Exception as err:
            logger.error("Failed to save enrolled embedding: %s", err)
            return False

    def delete_profile(self) -> bool:
        """Delete enrolled profile if it exists."""
        try:
            path = self.get_enrolled_path()
            if path.is_file():
                path.unlink()
            return True
        except Exception as err:
            logger.error("Failed to delete enrolled profile: %s", err)
            return False

    # ── Audio Decoding & Preprocessing ──────────────────────────────────────

    def decode_audio_bytes(self, audio_bytes: bytes) -> tuple[np.ndarray, int]:
        """
        Decode raw audio bytes into a float32 mono waveform and sample rate.
        Raises ValueError or RuntimeError on invalid or unreadable audio.
        """
        if not audio_bytes or len(audio_bytes) < 44:
            raise ValueError("Audio data is empty or too short.")

        buf = io.BytesIO(audio_bytes)
        try:
            data, sr = sf.read(buf, dtype="float32")
        except Exception as sf_err:
            # Fallback: write to a temporary file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                tf.write(audio_bytes)
                temp_wav_path = tf.name
            try:
                data, sr = sf.read(temp_wav_path, dtype="float32")
            finally:
                Path(temp_wav_path).unlink(missing_ok=True)

        if data.ndim > 1:
            data = data.mean(axis=1)

        return data, sr

    def preprocess_audio(self, audio_bytes: bytes) -> np.ndarray:
        """
        Decode audio and apply Resemblyzer's VAD silence trimming and resampling.
        Falls back to direct resampling if VAD trims excessively but energy is present.
        """
        from resemblyzer import preprocess_wav

        data, sr = self.decode_audio_bytes(audio_bytes)

        # Basic energy check: reject pure digital silence
        max_amp = float(np.max(np.abs(data))) if len(data) > 0 else 0.0
        if max_amp < 0.005:
            raise ValueError("Audio sample is silent or has too little energy.")

        try:
            waveform = preprocess_wav(data, source_sr=sr)
        except Exception:
            waveform = np.array([], dtype=np.float32)

        # If VAD trimmed too much or failed, fallback to resampled raw audio if long enough
        if len(waveform) < 1600:
            if len(data) >= 1600:
                import librosa
                if sr != 16000:
                    waveform = librosa.resample(data, orig_sr=sr, target_sr=16000)
                else:
                    waveform = data.astype(np.float32)
                # Normalize amplitude
                peak = np.max(np.abs(waveform))
                if peak > 0:
                    waveform = waveform / peak * 0.9
            else:
                raise ValueError("No recognizable speech detected in audio sample.")

        return waveform

    # ── Voice Enrollment ────────────────────────────────────────────────────

    def enroll_voice(
        self,
        audio_bytes: bytes,
        force: bool = False,
    ) -> tuple[bool, str, dict[str, Any]]:
        """
        Enroll a speaker from an audio sample.

        Security:
          - Does not overwrite an existing profile unless force=True.
          - Confirms enrollment only after successful creation and disk save.
        """
        if self.is_enrolled() and not force:
            return (
                False,
                "Voice profile already exists. Explicit authorized re-enrollment required.",
                {"error_code": "PROFILE_EXISTS", "is_enrolled": True},
            )

        try:
            waveform = self.preprocess_audio(audio_bytes)
        except ValueError as val_err:
            return (
                False,
                f"Enrollment audio invalid: {val_err}",
                {"error_code": "INVALID_AUDIO", "is_enrolled": self.is_enrolled()},
            )
        except Exception as err:
            logger.error("Audio preprocessing error during enrollment: %s", err)
            return (
                False,
                "Authentication failed due to a technical error.",
                {"error_code": "PREPROCESSING_ERROR", "is_enrolled": self.is_enrolled()},
            )

        try:
            encoder = get_voice_encoder()
            embedding = encoder.embed_utterance(waveform)
            saved = self.save_enrolled_embedding(embedding)
            if not saved:
                return (
                    False,
                    "Failed to save voice profile to disk.",
                    {"error_code": "SAVE_FAILED", "is_enrolled": self.is_enrolled()},
                )

            return (
                True,
                "Voice enrolled successfully.",
                {
                    "is_enrolled": True,
                    "dimensions": int(embedding.shape[0]),
                    "threshold": settings.similarity_threshold,
                },
            )
        except Exception as err:
            logger.error("Embedding generation error during enrollment: %s", err)
            return (
                False,
                "Authentication failed due to a technical error.",
                {"error_code": "ENCODER_ERROR", "is_enrolled": self.is_enrolled()},
            )

    # ── Speaker Verification ────────────────────────────────────────────────

    def verify_speaker(
        self,
        audio_bytes: bytes,
    ) -> tuple[bool, float, str, str | None]:
        """
        Verify incoming voice audio against the enrolled voice profile.

        Returns:
            (verified: bool, similarity: float, message: str, failure_code: str | None)

        Security rules:
          - If no profile enrolled: rejects immediately.
          - If audio invalid/empty: rejects immediately.
          - If verification model fails: fails closed (returns verified=False).
          - Compares against settings.similarity_threshold.
        """
        if not self.is_enrolled():
            return (
                False,
                0.0,
                "Voice profile not enrolled. Please enroll your voice first.",
                "NOT_ENROLLED",
            )

        enrolled_embedding = self.load_enrolled_embedding()
        if enrolled_embedding is None:
            return (
                False,
                0.0,
                "Voice profile not enrolled. Please enroll your voice first.",
                "PROFILE_MISSING",
            )

        try:
            waveform = self.preprocess_audio(audio_bytes)
        except ValueError as val_err:
            return (
                False,
                0.0,
                "Audio recording is empty or invalid.",
                f"INVALID_AUDIO: {val_err}",
            )
        except Exception as err:
            logger.error("Preprocessing error during speaker verification: %s", err)
            return (
                False,
                0.0,
                "Authentication failed due to a technical error.",
                "TECHNICAL_ERROR",
            )

        try:
            encoder = get_voice_encoder()
            command_embedding = encoder.embed_utterance(waveform)

            norm_cmd = np.linalg.norm(command_embedding)
            norm_enr = np.linalg.norm(enrolled_embedding)
            if norm_cmd == 0 or norm_enr == 0:
                return (
                    False,
                    0.0,
                    "Authentication failed due to a technical error.",
                    "ZERO_NORM_ERROR",
                )

            similarity = float(np.dot(command_embedding, enrolled_embedding) / (norm_cmd * norm_enr))
            threshold = settings.similarity_threshold

            if similarity >= threshold:
                return (
                    True,
                    similarity,
                    "Voice verified. Processing command.",
                    None,
                )
            else:
                return (
                    False,
                    similarity,
                    "Voice not recognized. Command rejected.",
                    f"SIMILARITY_BELOW_THRESHOLD: {similarity:.4f} < {threshold}",
                )

        except Exception as err:
            logger.error("Error during speaker verification computation: %s", err)
            # Mandatory security: technical verification error must fail closed
            return (
                False,
                0.0,
                "Authentication failed due to a technical error.",
                f"VERIFICATION_ERROR: {err}",
            )

    # ── Speech Recognition (Vosk) ───────────────────────────────────────────

    def transcribe_audio(self, audio_bytes: bytes) -> str:
        """
        Transcribe audio bytes to text using the offline Vosk speech recognizer.
        """
        try:
            from vosk import KaldiRecognizer

            # Vosk expects int16 at 16,000 Hz
            data, sr = sf.read(io.BytesIO(audio_bytes), dtype="int16")
            if data.ndim > 1:
                data = data.mean(axis=1).astype(np.int16)

            # If sample rate is not 16000, resample
            if sr != 16000:
                import librosa
                data_float = data.astype(np.float32) / 32768.0
                resampled = librosa.resample(data_float, orig_sr=sr, target_sr=16000)
                data = (resampled * 32767.0).astype(np.int16)

            model = get_vosk_model()
            recognizer = KaldiRecognizer(model, 16000)
            recognizer.AcceptWaveform(data.tobytes())
            res = json.loads(recognizer.FinalResult())
            return res.get("text", "").lower().strip()
        except Exception as err:
            logger.error("Vosk speech recognition error: %s", err)
            return ""

    # ── Authenticated Session Tokens ────────────────────────────────────────

    def create_session_token(self, session_id: str, similarity: float) -> str:
        """
        Generate a signed authentication token proving speaker verification.
        Valid for 10 minutes (600 seconds).
        """
        expires_at = int(time.time()) + 600
        payload = f"{session_id}:{similarity:.4f}:{expires_at}"
        signature = hmac.new(
            settings.auth_secret_key.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        token_str = f"{payload}:{signature}"
        return base64.urlsafe_b64encode(token_str.encode("utf-8")).decode("utf-8")

    def verify_session_token(self, token: str) -> tuple[bool, str | None]:
        """
        Validate signed session token. Returns (is_valid, session_id).
        """
        if not token:
            return False, None
        try:
            raw = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
            parts = raw.split(":")
            if len(parts) != 4:
                return False, None
            session_id, similarity, expires_at_str, signature = parts
            expires_at = int(expires_at_str)
            if time.time() > expires_at:
                return False, None

            expected_payload = f"{session_id}:{similarity}:{expires_at_str}"
            expected_sig = hmac.new(
                settings.auth_secret_key.encode("utf-8"),
                expected_payload.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()

            if not hmac.compare_digest(signature, expected_sig):
                return False, None

            return True, session_id
        except Exception:
            return False, None
