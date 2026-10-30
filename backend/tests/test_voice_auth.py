"""
Test suite covering Voice Enrollment and Automatic Voice Authentication.

Covers the 8 core test cases required by VoxEdge:
  TEST 1: First-time enrollment.
          Expected: Backend creates voice profile and confirms enrollment.
  TEST 2: Enrolled speaker gives a command.
          Expected: If verification passes, command proceeds to intent processing.
  TEST 3: Unregistered speaker gives a command.
          Expected: Command is rejected, and no device state changes.
  TEST 4: Enrolled speaker fails the similarity threshold.
          Expected: Command is rejected, and no device state changes.
  TEST 5: No enrolled profile exists.
          Expected: All ordinary device-control commands are rejected.
  TEST 6: Verification model fails or returns an error.
          Expected: Authentication fails closed; no command executes.
  TEST 7: Direct API request attempts to control a device without authentication.
          Expected: Backend rejects the request (HTTP 401).
  TEST 8: Existing profile is submitted for replacement.
          Expected: Profile is not overwritten without explicit re-enrollment authorization.
"""

from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure backend directory is in python path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.database.session import Base, get_db
from app.main import app
from app.models.device import Device
from app.services.voice_auth_service import VoiceAuthService


# ── Helpers for generating audio ─────────────────────────────────────────────

def create_synthetic_wav(
    frequency: float = 440.0,
    duration: float = 1.5,
    sample_rate: int = 16000,
) -> bytes:
    """Generate a clean mono 16 kHz WAV audio file in bytes."""
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    # Generate multi-tone waveform to simulate complex sound
    waveform = (
        0.5 * np.sin(2 * np.pi * frequency * t)
        + 0.3 * np.sin(2 * np.pi * (frequency * 1.5) * t)
        + 0.2 * np.sin(2 * np.pi * (frequency * 2.0) * t)
    ).astype(np.float32)

    buf = io.BytesIO()
    sf.write(buf, waveform, sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def load_real_wav(file_path: Path) -> bytes:
    """Load an existing WAV file from disk into bytes."""
    with open(file_path, "rb") as f:
        return f.read()


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_voice_profile(tmp_path):
    """Provide a temporary enrolled_voice.npy path to isolate tests from real profile."""
    profile_path = tmp_path / "test_enrolled_voice.npy"
    original_path = settings.enrolled_voice_path

    # Point settings to temporary file
    settings.enrolled_voice_path = str(profile_path)
    yield profile_path

    # Teardown: restore original path
    settings.enrolled_voice_path = original_path
    if profile_path.exists():
        profile_path.unlink()


@pytest.fixture
def db_session():
    """In-memory SQLite database session with seeded devices."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSessionLocal()

    # Seed initial test devices
    devices = [
        Device(
            id="bedroom_light",
            name="Bedroom Light",
            device_type="light",
            location="bedroom",
            state="OFF",
            supported_actions='["ON", "OFF"]',
        ),
        Device(
            id="living_room_light",
            name="Living Room Light",
            device_type="light",
            location="living_room",
            state="OFF",
            supported_actions='["ON", "OFF"]',
        ),
        Device(
            id="fan",
            name="Fan",
            device_type="fan",
            location="bedroom",
            state="OFF",
            supported_actions='["ON", "OFF"]',
        ),
    ]
    session.add_all(devices)
    session.commit()

    yield session
    session.close()


@pytest.fixture
def client(db_session):
    """FastAPI test client with database dependency override."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ── TEST 1: First-time enrollment ───────────────────────────────────────────

def test_1_first_time_enrollment(client, temp_voice_profile):
    """
    TEST 1: First-time enrollment.
    Expected: The backend creates the voice profile and confirms enrollment.
    """
    # Verify not enrolled initially
    assert not temp_voice_profile.exists()
    status_resp = client.get("/voice/enrollment-status")
    assert status_resp.status_code == 200
    assert status_resp.json()["is_enrolled"] is False

    # Perform enrollment with sample audio
    sample_wav = create_synthetic_wav(frequency=440.0, duration=2.0)
    response = client.post(
        "/voice/enroll",
        files={"file": ("enrollment.wav", sample_wav, "audio/wav")},
        data={"force": False},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["is_enrolled"] is True
    assert "Voice enrolled successfully" in data["message"]
    assert data["dimensions"] == 256

    # Verify profile file exists on disk and is non-empty
    assert temp_voice_profile.exists()
    saved_embedding = np.load(temp_voice_profile)
    assert saved_embedding.shape == (256,)
    assert np.isclose(np.linalg.norm(saved_embedding), 1.0, atol=1e-3)


# ── TEST 2: Enrolled speaker gives a command ────────────────────────────────

def test_2_enrolled_speaker_gives_command(client, temp_voice_profile, db_session):
    """
    TEST 2: Enrolled speaker gives a command.
    Expected: If verification passes, the command proceeds to intent processing.
    """
    # 1. Enroll speaker with voice A
    voice_a_audio = create_synthetic_wav(frequency=400.0, duration=2.0)
    enroll_resp = client.post(
        "/voice/enroll",
        files={"file": ("enroll.wav", voice_a_audio, "audio/wav")},
    )
    assert enroll_resp.status_code == 200

    # 2. Speaker gives command with same voice and speech "turn on the fan"
    with patch.object(VoiceAuthService, "transcribe_audio", return_value="turn on the fan"):
        resp = client.post(
            "/voice/process-audio",
            files={"file": ("cmd.wav", voice_a_audio, "audio/wav")},
        )

    assert resp.status_code == 200
    data = resp.json()

    # Verification passed
    assert data["speaker_verified"] is True
    assert data["speaker_similarity"] >= settings.similarity_threshold
    assert data["decision"] == "EXECUTE"
    assert data["target_device"] == "fan"
    assert data["requested_action"] == "ON"
    assert data["execution_status"] == "SUCCESS"
    assert data["new_device_state"] == "ON"

    # Verify device state changed in database
    fan = db_session.query(Device).filter(Device.id == "fan").first()
    assert fan.state == "ON"


# ── TEST 3: Unregistered speaker gives a command ────────────────────────────

def test_3_unregistered_speaker_gives_command(client, temp_voice_profile, db_session):
    """
    TEST 3: Unregistered speaker gives a command.
    Expected: The command is rejected, and no device state changes.
    """
    # 1. Enroll legitimate speaker
    real_speaker_audio = create_synthetic_wav(frequency=300.0, duration=2.0)
    client.post(
        "/voice/enroll",
        files={"file": ("enroll.wav", real_speaker_audio, "audio/wav")},
    )

    # 2. Unregistered speaker (different voice) attempts a command
    unregistered_audio = create_synthetic_wav(frequency=900.0, duration=2.0)

    # Force verification failure simulating an imposter speaker
    with patch.object(
        VoiceAuthService,
        "verify_speaker",
        return_value=(False, 0.35, "Voice not recognized. Command rejected.", "SIMILARITY_BELOW_THRESHOLD"),
    ):
        resp = client.post(
            "/voice/process-audio",
            files={"file": ("imposter.wav", unregistered_audio, "audio/wav")},
        )

    assert resp.status_code == 200
    data = resp.json()

    # Verification must be rejected
    assert data["speaker_verified"] is False
    assert data["decision"] == "REJECT"
    assert data["execution_status"] == "REJECTED"
    assert "Voice not recognized" in data["message"]

    # Verify NO device state changed
    fan = db_session.query(Device).filter(Device.id == "fan").first()
    assert fan.state == "OFF"


# ── TEST 4: Enrolled speaker fails similarity threshold ─────────────────────

def test_4_enrolled_speaker_fails_similarity_threshold(client, temp_voice_profile, db_session):
    """
    TEST 4: Enrolled speaker fails the similarity threshold.
    Expected: The command is rejected, and no device state changes.
    """
    # 1. Enroll speaker
    speaker_audio = create_synthetic_wav(frequency=440.0, duration=2.0)
    client.post(
        "/voice/enroll",
        files={"file": ("enroll.wav", speaker_audio, "audio/wav")},
    )

    # 2. Speaker speaks but score (e.g. 0.58) is below configured threshold (0.65)
    with patch.object(
        VoiceAuthService,
        "verify_speaker",
        return_value=(
            False,
            0.58,
            "Voice not recognized. Command rejected.",
            "SIMILARITY_BELOW_THRESHOLD: 0.5800 < 0.65",
        ),
    ):
        resp = client.post(
            "/voice/process-audio",
            files={"file": ("noisy_command.wav", speaker_audio, "audio/wav")},
        )

    assert resp.status_code == 200
    data = resp.json()

    assert data["speaker_verified"] is False
    assert data["speaker_similarity"] == 0.58
    assert data["decision"] == "REJECT"
    assert data["execution_status"] == "REJECTED"
    assert "rejected" in data["message"].lower()

    # Device state remains unchanged
    bedroom_light = db_session.query(Device).filter(Device.id == "bedroom_light").first()
    assert bedroom_light.state == "OFF"


# ── TEST 5: No enrolled profile exists ──────────────────────────────────────

def test_5_no_enrolled_profile_exists(client, temp_voice_profile, db_session):
    """
    TEST 5: No enrolled profile exists.
    Expected: All ordinary device-control commands are rejected.
    """
    # Ensure no profile exists
    if temp_voice_profile.exists():
        temp_voice_profile.unlink()

    # Attempt voice audio command
    audio = create_synthetic_wav(frequency=440.0, duration=1.5)
    resp = client.post(
        "/voice/process-audio",
        files={"file": ("cmd.wav", audio, "audio/wav")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["speaker_verified"] is False
    assert data["decision"] == "REJECT"
    assert "not enrolled" in data["message"].lower()

    # Attempt text command without enrollment
    resp_text = client.post(
        "/voice/process",
        json={"text": "turn on the bedroom light", "input_mode": "text"},
    )
    assert resp_text.status_code == 200
    data_text = resp_text.json()
    assert data_text["decision"] == "REJECT"
    assert "not enrolled" in data_text["message"].lower()

    # Verify device state did not change
    light = db_session.query(Device).filter(Device.id == "bedroom_light").first()
    assert light.state == "OFF"


# ── TEST 6: Verification model fails or returns an error ────────────────────

def test_6_verification_model_fails_closed(client, temp_voice_profile, db_session):
    """
    TEST 6: Verification model fails or returns an error.
    Expected: Authentication fails closed; no command executes.
    """
    # 1. Enroll speaker profile
    speaker_audio = create_synthetic_wav(frequency=440.0, duration=2.0)
    client.post(
        "/voice/enroll",
        files={"file": ("enroll.wav", speaker_audio, "audio/wav")},
    )

    # 2. Simulate model failure (e.g. RuntimeError or memory failure in encoder)
    with patch(
        "app.services.voice_auth_service.get_voice_encoder",
        side_effect=RuntimeError("GPU / Resemblyzer internal encoder failure"),
    ):
        resp = client.post(
            "/voice/process-audio",
            files={"file": ("cmd.wav", speaker_audio, "audio/wav")},
        )

    assert resp.status_code == 200
    data = resp.json()

    # Must fail closed: not verified, rejected, no action
    assert data["speaker_verified"] is False
    assert data["decision"] == "REJECT"
    assert data["execution_status"] == "REJECTED"
    assert "technical error" in data["message"].lower()

    # Devices remain untouched
    fan = db_session.query(Device).filter(Device.id == "fan").first()
    assert fan.state == "OFF"


# ── TEST 7: Direct API request attempts to control device ───────────────────

def test_7_direct_api_request_without_auth_rejected(client, db_session):
    """
    TEST 7: Direct API request attempts to control a device without authentication.
    Expected: The backend rejects the request (HTTP 401).
    """
    # Attempt to call POST /devices/bedroom_light/command directly without auth header
    response = client.post(
        "/devices/bedroom_light/command",
        json={"action": "ON"},
    )

    # Must be rejected with 401 Unauthorized
    assert response.status_code == 401
    assert "authentication required" in response.json()["detail"].lower()

    # Device state must NOT have changed
    light = db_session.query(Device).filter(Device.id == "bedroom_light").first()
    assert light.state == "OFF"


# ── TEST 8: Existing profile submitted for replacement ──────────────────────

def test_8_existing_profile_replacement_protection(client, temp_voice_profile):
    """
    TEST 8: Existing profile is submitted for replacement.
    Expected: The profile is not overwritten without the authorized re-enrollment process.
    """
    # 1. Initial enrollment
    orig_audio = create_synthetic_wav(frequency=400.0, duration=2.0)
    resp1 = client.post(
        "/voice/enroll",
        files={"file": ("sample1.wav", orig_audio, "audio/wav")},
    )
    assert resp1.status_code == 200
    orig_embedding = np.load(temp_voice_profile)

    # 2. Attempt replacement WITHOUT explicit force flag
    new_audio = create_synthetic_wav(frequency=600.0, duration=2.0)
    resp_unauth = client.post(
        "/voice/enroll",
        files={"file": ("sample2.wav", new_audio, "audio/wav")},
        data={"force": False},
    )

    # Must be rejected with 409 Conflict
    assert resp_unauth.status_code == 409
    assert "already exists" in resp_unauth.json()["detail"].lower()

    # Verify profile was NOT overwritten
    current_embedding = np.load(temp_voice_profile)
    assert np.array_equal(orig_embedding, current_embedding)

    # 3. Authorized re-enrollment WITH explicit force flag
    resp_auth = client.post(
        "/voice/enroll",
        files={"file": ("sample2.wav", new_audio, "audio/wav")},
        data={"force": True},
    )
    assert resp_auth.status_code == 200
    assert resp_auth.json()["success"] is True

    # Verify profile was updated with authorized process
    updated_embedding = np.load(temp_voice_profile)
    assert not np.array_equal(orig_embedding, updated_embedding)
