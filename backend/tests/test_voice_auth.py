"""
Comprehensive Test Suite for Voice Enrollment and Automatic Voice Authentication.

Covers all 12 mandatory evaluation scenarios:
  1. Successful enrollment.
  2. Loading the saved profile after restarting the application.
  3. Enrolled speaker gives a valid command.
  4. Different speaker gives the same command.
  5. No profile exists.
  6. Profile file is corrupted or missing.
  7. Audio is empty, too short, or invalid.
  8. Verification raises an exception (fails closed).
  9. Speech is recognized but speaker verification fails.
  10. Direct API requests attempt to control a device without valid authentication.
  11. Device state remains unchanged after rejected commands.
  12. Repeated commands continue to trigger authentication automatically.
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


# ── Audio Generation Helpers ─────────────────────────────────────────────────

def create_synthetic_wav(
    frequency: float = 440.0,
    duration: float = 2.0,
    sample_rate: int = 16000,
    amplitude: float = 0.5,
) -> bytes:
    """Generate a clean mono 16 kHz WAV audio file in bytes with rich harmonic content."""
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    waveform = (
        amplitude * 0.5 * np.sin(2 * np.pi * frequency * t)
        + amplitude * 0.3 * np.sin(2 * np.pi * (frequency * 1.5) * t)
        + amplitude * 0.2 * np.sin(2 * np.pi * (frequency * 2.0) * t)
    ).astype(np.float32)

    buf = io.BytesIO()
    sf.write(buf, waveform, sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_voice_profile(tmp_path):
    """Provide a temporary enrolled_voice.npy path to isolate tests from production profiles."""
    profile_path = tmp_path / "test_enrolled_voice.npy"
    original_path = settings.enrolled_voice_path

    settings.enrolled_voice_path = str(profile_path)
    yield profile_path

    settings.enrolled_voice_path = original_path
    if profile_path.exists():
        profile_path.unlink()


@pytest.fixture
def db_session():
    """In-memory SQLite database session seeded with test devices."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSessionLocal()

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


# ── Scenario 1: Successful Enrollment ────────────────────────────────────────

def test_scenario_1_successful_enrollment(client, temp_voice_profile):
    """
    Scenario 1: Successful enrollment.
    Expected: Backend generates embedding, saves profile, and confirms enrollment.
    """
    assert not temp_voice_profile.exists()
    status_resp = client.get("/voice/enrollment-status")
    assert status_resp.status_code == 200
    assert status_resp.json()["is_enrolled"] is False

    sample_wav = create_synthetic_wav(frequency=440.0, duration=2.5)
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

    # Verify profile file exists on disk and is a valid 256-dim unit vector
    assert temp_voice_profile.exists()
    saved_embedding = np.load(temp_voice_profile)
    assert saved_embedding.shape == (256,)
    assert np.isclose(np.linalg.norm(saved_embedding), 1.0, atol=1e-3)


# ── Scenario 2: Loading Saved Profile After Restarting Application ───────────

def test_scenario_2_loading_saved_profile_after_restart(temp_voice_profile):
    """
    Scenario 2: Loading the saved profile after restarting the application.
    Expected: A freshly initialized VoiceAuthService correctly loads and validates profile.
    """
    # Create and save a valid mock profile
    rng = np.random.default_rng(42)
    fake_embedding = rng.standard_normal(256).astype(np.float32)
    fake_embedding /= np.linalg.norm(fake_embedding)
    np.save(temp_voice_profile, fake_embedding)

    # Initialize a new service instance (simulating fresh server restart)
    new_service = VoiceAuthService()
    assert new_service.is_enrolled() is True

    loaded_emb = new_service.load_enrolled_embedding()
    assert loaded_emb is not None
    assert loaded_emb.shape == (256,)
    assert np.allclose(loaded_emb, fake_embedding, atol=1e-5)


# ── Scenario 3: Enrolled Speaker Gives a Valid Command ───────────────────────

def test_scenario_3_enrolled_speaker_valid_command(client, temp_voice_profile, db_session):
    """
    Scenario 3: Enrolled speaker gives a valid command.
    Expected: Verification succeeds, command is recognized, fan turns ON.
    """
    voice_audio = create_synthetic_wav(frequency=400.0, duration=2.0)
    enroll_resp = client.post(
        "/voice/enroll",
        files={"file": ("enroll.wav", voice_audio, "audio/wav")},
    )
    assert enroll_resp.status_code == 200

    # User speaks command with verified voice
    with patch.object(VoiceAuthService, "transcribe_audio", return_value="turn on the fan"):
        resp = client.post(
            "/voice/process-audio",
            files={"file": ("cmd.wav", voice_audio, "audio/wav")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["speaker_verified"] is True
    assert data["decision"] == "EXECUTE"
    assert data["target_device"] == "fan"
    assert data["requested_action"] == "ON"
    assert data["execution_status"] == "SUCCESS"
    assert data["new_device_state"] == "ON"

    fan = db_session.query(Device).filter(Device.id == "fan").first()
    assert fan.state == "ON"


# ── Scenario 4: Different Speaker Gives the Same Command ─────────────────────

def test_scenario_4_different_speaker_same_command(client, temp_voice_profile, db_session):
    """
    Scenario 4: Different speaker gives the same command.
    Expected: Verification fails, command is rejected, fan remains OFF.
    """
    genuine_audio = create_synthetic_wav(frequency=300.0, duration=2.0)
    client.post(
        "/voice/enroll",
        files={"file": ("enroll.wav", genuine_audio, "audio/wav")},
    )

    imposter_audio = create_synthetic_wav(frequency=800.0, duration=2.0)

    with patch.object(
        VoiceAuthService,
        "verify_speaker",
        return_value=(
            False,
            0.38,
            "Voice not recognized. Command rejected.",
            "SIMILARITY_BELOW_THRESHOLD: 0.3800 < 0.65",
        ),
    ):
        resp = client.post(
            "/voice/process-audio",
            files={"file": ("imposter_cmd.wav", imposter_audio, "audio/wav")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["speaker_verified"] is False
    assert data["decision"] == "REJECT"
    assert data["execution_status"] == "REJECTED"
    assert "rejected" in data["message"].lower()

    # Fan must remain OFF
    fan = db_session.query(Device).filter(Device.id == "fan").first()
    assert fan.state == "OFF"


# ── Scenario 5: No Profile Exists ────────────────────────────────────────────

def test_scenario_5_no_profile_exists(client, temp_voice_profile, db_session):
    """
    Scenario 5: No profile exists.
    Expected: Ordinary device-control commands rejected, enrollment required message.
    """
    if temp_voice_profile.exists():
        temp_voice_profile.unlink()

    audio = create_synthetic_wav(frequency=440.0, duration=2.0)
    resp = client.post(
        "/voice/process-audio",
        files={"file": ("cmd.wav", audio, "audio/wav")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["speaker_verified"] is False
    assert data["decision"] == "REJECT"
    assert "not enrolled" in data["message"].lower()

    fan = db_session.query(Device).filter(Device.id == "fan").first()
    assert fan.state == "OFF"


# ── Scenario 6: Profile File is Corrupted or Missing ─────────────────────────

def test_scenario_6_profile_corrupted_or_missing(client, temp_voice_profile, db_session):
    """
    Scenario 6: Profile file is corrupted or missing.
    Expected: Handled safely, commands fail closed without changing device state.
    """
    # 6a. Missing profile
    if temp_voice_profile.exists():
        temp_voice_profile.unlink()
    service = VoiceAuthService()
    assert service.is_enrolled() is False
    assert service.load_enrolled_embedding() is None

    # 6b. Corrupted profile (0 bytes or garbage data)
    temp_voice_profile.write_bytes(b"corrupted_non_numpy_data_bytes_123456789")
    assert service.is_enrolled() is False
    assert service.load_enrolled_embedding() is None

    # 6c. Invalid dimension (e.g. 128 instead of 256)
    bad_dim = np.ones(128, dtype=np.float32)
    np.save(temp_voice_profile, bad_dim)
    assert service.is_enrolled() is False
    assert service.load_enrolled_embedding() is None

    # Attempt audio command against corrupted profile
    audio = create_synthetic_wav(frequency=440.0, duration=2.0)
    resp = client.post(
        "/voice/process-audio",
        files={"file": ("cmd.wav", audio, "audio/wav")},
    )
    assert resp.status_code == 200
    assert resp.json()["decision"] == "REJECT"
    assert resp.json()["speaker_verified"] is False

    bedroom_light = db_session.query(Device).filter(Device.id == "bedroom_light").first()
    assert bedroom_light.state == "OFF"


# ── Scenario 7: Audio is Empty, Too Short, or Invalid ────────────────────────

def test_scenario_7_audio_empty_too_short_or_invalid(client, temp_voice_profile, db_session):
    """
    Scenario 7: Audio is empty, too short, or invalid.
    Expected: Rejects safely and requests another recording.
    """
    # Enroll speaker first
    valid_audio = create_synthetic_wav(frequency=440.0, duration=2.5)
    client.post("/voice/enroll", files={"file": ("enroll.wav", valid_audio, "audio/wav")})

    # 7a. Completely empty audio file (0 bytes)
    resp_empty = client.post(
        "/voice/process-audio",
        files={"file": ("empty.wav", b"", "audio/wav")},
    )
    assert resp_empty.status_code == 200
    assert resp_empty.json()["decision"] == "REJECT"
    assert "invalid" in resp_empty.json()["message"].lower() or "empty" in resp_empty.json()["message"].lower()

    # 7b. Corrupted non-WAV bytes
    resp_corrupt = client.post(
        "/voice/process-audio",
        files={"file": ("bad.wav", b"RIFF....NOT_A_VALID_WAVE_FORMAT", "audio/wav")},
    )
    assert resp_corrupt.status_code == 200
    assert resp_corrupt.json()["decision"] == "REJECT"

    # 7c. Pure silent audio
    silent_audio = create_synthetic_wav(frequency=440.0, duration=2.0, amplitude=0.0)
    resp_silent = client.post(
        "/voice/process-audio",
        files={"file": ("silent.wav", silent_audio, "audio/wav")},
    )
    assert resp_silent.status_code == 200
    assert resp_silent.json()["decision"] == "REJECT"

    # 7d. Audio too short (< 0.5 seconds)
    short_audio = create_synthetic_wav(frequency=440.0, duration=0.2)
    resp_short = client.post(
        "/voice/process-audio",
        files={"file": ("short.wav", short_audio, "audio/wav")},
    )
    assert resp_short.status_code == 200
    assert resp_short.json()["decision"] == "REJECT"

    # Verify device state never changed
    fan = db_session.query(Device).filter(Device.id == "fan").first()
    assert fan.state == "OFF"


# ── Scenario 8: Verification Raises an Exception ─────────────────────────────

def test_scenario_8_verification_raises_exception_fails_closed(client, temp_voice_profile, db_session):
    """
    Scenario 8: Verification raises an exception.
    Expected: Fails closed, returns technical error, no command executes.
    """
    valid_audio = create_synthetic_wav(frequency=440.0, duration=2.0)
    client.post("/voice/enroll", files={"file": ("enroll.wav", valid_audio, "audio/wav")})

    with patch(
        "app.services.voice_auth_service.get_voice_encoder",
        side_effect=RuntimeError("GPU / Resemblyzer internal encoder failure"),
    ):
        resp = client.post(
            "/voice/process-audio",
            files={"file": ("cmd.wav", valid_audio, "audio/wav")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["speaker_verified"] is False
    assert data["decision"] == "REJECT"
    assert data["execution_status"] == "REJECTED"
    assert "technical error" in data["message"].lower()

    fan = db_session.query(Device).filter(Device.id == "fan").first()
    assert fan.state == "OFF"


# ── Scenario 9: Speech Recognized But Speaker Verification Fails ─────────────

def test_scenario_9_speech_recognized_but_verification_fails(client, temp_voice_profile, db_session):
    """
    Scenario 9: Speech is recognized by Vosk but speaker verification fails.
    Expected: Reject command without changing device state.
    """
    valid_audio = create_synthetic_wav(frequency=440.0, duration=2.0)
    client.post("/voice/enroll", files={"file": ("enroll.wav", valid_audio, "audio/wav")})

    # Imposter speaks "turn on bedroom light", Vosk would recognize it, but speaker verification fails
    with patch.object(
        VoiceAuthService,
        "verify_speaker",
        return_value=(False, 0.45, "Voice not recognized. Command rejected.", "SIMILARITY_BELOW_THRESHOLD: 0.4500 < 0.65"),
    ):
        with patch.object(VoiceAuthService, "transcribe_audio", return_value="turn on bedroom light"):
            resp = client.post(
                "/voice/process-audio",
                files={"file": ("imposter.wav", valid_audio, "audio/wav")},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["speaker_verified"] is False
    assert data["decision"] == "REJECT"
    assert data["execution_status"] == "REJECTED"

    # Crucial security check: device must NOT turn on despite recognizable command
    light = db_session.query(Device).filter(Device.id == "bedroom_light").first()
    assert light.state == "OFF"


# ── Scenario 10: Direct API Request Attempts Control Without Valid Auth ─────

def test_scenario_10_direct_api_request_without_auth_rejected(client, db_session):
    """
    Scenario 10: Direct API request attempts to control a device without valid authentication.
    Expected: Backend rejects the requests.
    """
    # 10a. Direct POST /devices/{id}/command without Bearer auth header
    resp_device = client.post(
        "/devices/bedroom_light/command",
        json={"action": "ON"},
    )
    assert resp_device.status_code == 401
    assert "authentication required" in resp_device.json()["detail"].lower()

    # 10b. Direct POST /decisions/confirm without Bearer auth header
    resp_confirm = client.post(
        "/decisions/confirm",
        json={"session_id": "unauth-session", "response": "fan"},
    )
    assert resp_confirm.status_code == 200
    assert resp_confirm.json()["decision"] == "REJECT"

    # 10c. Direct POST /voice/process without Bearer auth header
    resp_process = client.post(
        "/voice/process",
        json={"text": "turn on the fan", "input_mode": "text"},
    )
    assert resp_process.status_code == 200
    assert resp_process.json()["decision"] == "REJECT"

    # Verify no devices changed state
    fan = db_session.query(Device).filter(Device.id == "fan").first()
    light = db_session.query(Device).filter(Device.id == "bedroom_light").first()
    assert fan.state == "OFF"
    assert light.state == "OFF"


# ── Scenario 11: Device State Remains Unchanged After Rejected Commands ─────

def test_scenario_11_device_state_remains_unchanged_after_rejected_commands(client, temp_voice_profile, db_session):
    """
    Scenario 11: Device state remains unchanged after rejected commands.
    Expected: Confirm initial states, send rejected commands, confirm states unchanged.
    """
    valid_audio = create_synthetic_wav(frequency=440.0, duration=2.0)
    client.post("/voice/enroll", files={"file": ("enroll.wav", valid_audio, "audio/wav")})

    # Capture initial states
    initial_fan = db_session.query(Device).filter(Device.id == "fan").first().state
    initial_light = db_session.query(Device).filter(Device.id == "bedroom_light").first().state
    assert initial_fan == "OFF"
    assert initial_light == "OFF"

    # Sequence of failing commands
    with patch.object(
        VoiceAuthService,
        "verify_speaker",
        return_value=(False, 0.50, "Voice not recognized. Command rejected.", "SIMILARITY_BELOW_THRESHOLD"),
    ):
        client.post("/voice/process-audio", files={"file": ("c1.wav", valid_audio, "audio/wav")})
        client.post("/voice/process-audio", files={"file": ("c2.wav", valid_audio, "audio/wav")})

    client.post("/voice/process", json={"text": "turn on bedroom light", "input_mode": "text"})

    # Assert states remain strictly OFF
    assert db_session.query(Device).filter(Device.id == "fan").first().state == initial_fan
    assert db_session.query(Device).filter(Device.id == "bedroom_light").first().state == initial_light


# ── Scenario 12: Repeated Commands Trigger Authentication Automatically ─────

def test_scenario_12_repeated_commands_trigger_auth_automatically(client, temp_voice_profile, db_session):
    """
    Scenario 12: Repeated commands continue to trigger authentication automatically.
    Expected:
      Command 1: Genuine speaker -> VERIFIED -> executes (fan turns ON).
      Command 2: Imposter speaker -> REJECTED -> fan remains ON (does not turn OFF).
      Command 3: Genuine speaker -> VERIFIED -> executes (fan turns OFF).
    """
    genuine_audio = create_synthetic_wav(frequency=440.0, duration=2.0)
    client.post("/voice/enroll", files={"file": ("enroll.wav", genuine_audio, "audio/wav")})

    # Command 1: Genuine user says "turn on the fan"
    with patch.object(
        VoiceAuthService,
        "verify_speaker",
        return_value=(True, 0.82, "Voice verified. Processing command.", None),
    ):
        with patch.object(VoiceAuthService, "transcribe_audio", return_value="turn on the fan"):
            resp1 = client.post(
                "/voice/process-audio",
                files={"file": ("cmd1.wav", genuine_audio, "audio/wav")},
            )

    assert resp1.status_code == 200
    assert resp1.json()["speaker_verified"] is True
    assert resp1.json()["decision"] == "EXECUTE"
    assert db_session.query(Device).filter(Device.id == "fan").first().state == "ON"

    # Command 2: Imposter user immediately says "turn off the fan"
    imposter_audio = create_synthetic_wav(frequency=900.0, duration=2.0)
    with patch.object(
        VoiceAuthService,
        "verify_speaker",
        return_value=(False, 0.41, "Voice not recognized. Command rejected.", "SIMILARITY_BELOW_THRESHOLD"),
    ):
        with patch.object(VoiceAuthService, "transcribe_audio", return_value="turn off the fan"):
            resp2 = client.post(
                "/voice/process-audio",
                files={"file": ("cmd2.wav", imposter_audio, "audio/wav")},
            )

    assert resp2.status_code == 200
    assert resp2.json()["speaker_verified"] is False
    assert resp2.json()["decision"] == "REJECT"
    # The fan must remain ON! The imposter was not allowed to turn it off
    assert db_session.query(Device).filter(Device.id == "fan").first().state == "ON"

    # Command 3: Genuine user says "turn off the fan"
    with patch.object(
        VoiceAuthService,
        "verify_speaker",
        return_value=(True, 0.79, "Voice verified. Processing command.", None),
    ):
        with patch.object(VoiceAuthService, "transcribe_audio", return_value="turn off the fan"):
            resp3 = client.post(
                "/voice/process-audio",
                files={"file": ("cmd3.wav", genuine_audio, "audio/wav")},
            )

    assert resp3.status_code == 200
    assert resp3.json()["speaker_verified"] is True
    assert resp3.json()["decision"] == "EXECUTE"
    # Now fan turns OFF
    assert db_session.query(Device).filter(Device.id == "fan").first().state == "OFF"
