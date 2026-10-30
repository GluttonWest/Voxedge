"""
Test suite for Feature 5: Conversation History, Context Management,
and Small Language Model (SLM) Integration.

Covers all 12 scenarios required:
  SCENARIO 1: User: "Turn on the fan." Then: "Turn it off."
              Expected: Resolves follow-up to fan when context is clear.
  SCENARIO 2: User: "Turn it off." with no prior context or multiple plausible targets.
              Expected: Asks for clarification.
  SCENARIO 3: Assistant asks which device to turn off; User: "The fan."
              Expected: Resolves pending question, executes validated action.
  SCENARIO 4: User gives an unrelated answer to a clarification question.
              Expected: Does not execute pending action incorrectly.
  SCENARIO 5: Conversation history is empty.
              Expected: Does not invent missing context.
  SCENARIO 6: SLM returns malformed data.
              Expected: Rejects malformed output, uses safe fallback.
  SCENARIO 7: SLM is unavailable or times out.
              Expected: Application remains operational, does not execute unvalidated action.
  SCENARIO 8: SLM proposes an unsupported device action.
              Expected: Backend decision engine rejects proposal.
  SCENARIO 9: Voice authentication fails.
              Expected: No normal device-control action occurs.
  SCENARIO 10: Backend device-control endpoint called without valid authorization.
              Expected: Rejects request (HTTP 401).
  SCENARIO 11: Device execution fails.
              Expected: Records failure accurately instead of reporting success.
  SCENARIO 12: Conversation history exceeds configured limit.
              Expected: Applies configured retention policy (trims oldest).
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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
from app.models.interaction import Interaction
from app.schemas.conversation import SLMProposal
from app.services.context_service import ContextService, PendingClarification
from app.services.conversation_service import ConversationService
from app.services.decision_engine import DecisionEngine
from app.services.device_service import DeviceService
from app.services.intent_service import IntentService
from app.services.slm_service import BaseSLMProvider, SLMService
from app.services.voice_auth_service import VoiceAuthService


# ── Helpers ───────────────────────────────────────────────────────────────────

def create_synthetic_wav(frequency: float = 440.0, duration: float = 1.0, sample_rate: int = 16000) -> bytes:
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    waveform = (0.5 * np.sin(2 * np.pi * frequency * t)).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, waveform, sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_voice_profile(tmp_path):
    profile_path = tmp_path / "test_enrolled_voice.npy"
    original_path = settings.enrolled_voice_path
    settings.enrolled_voice_path = str(profile_path)
    yield profile_path
    settings.enrolled_voice_path = original_path
    if profile_path.exists():
        profile_path.unlink()


@pytest.fixture
def db_session():
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
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def enrolled_auth(temp_voice_profile):
    voice_auth = VoiceAuthService()
    dummy_embedding = np.ones(256, dtype=np.float32)
    dummy_embedding = dummy_embedding / np.linalg.norm(dummy_embedding)
    voice_auth.save_enrolled_embedding(dummy_embedding)

    sid = "test-session-feature5"
    token = voice_auth.create_session_token(sid, 0.95)

    def make_auth_headers(session_id: str | None = None):
        target_sid = session_id or sid
        tok = voice_auth.create_session_token(target_sid, 0.95)
        return {"Authorization": f"Bearer {tok}"}

    return {
        "voice_auth": voice_auth,
        "token": token,
        "session_id": sid,
        "headers": {"Authorization": f"Bearer {token}"},
        "make_headers": make_auth_headers,
    }


# ── SCENARIOS ────────────────────────────────────────────────────────────────

def test_scenario_1_pronoun_follow_up_resolved(db_session, client, enrolled_auth):
    """
    SCENARIO 1:
      User: "Turn on the fan."
      Then: "Turn it off."
      Expected: Resolves follow-up to fan when context is clear.
    """
    sid = "sess-scenario-1"
    headers = enrolled_auth["make_headers"](sid)

    # Step 1: "Turn on the fan."
    r1 = client.post("/voice/process", headers=headers, json={"text": "Turn on the fan.", "session_id": sid})
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["decision"] == "EXECUTE"
    assert d1["target_device"] == "fan"
    assert d1["requested_action"] == "ON"
    assert db_session.query(Device).filter_by(id="fan").first().state == "ON"

    # Step 2: "Turn it off." -> resolves to fan
    r2 = client.post("/voice/process", headers=headers, json={"text": "Turn it off.", "session_id": sid})
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["decision"] == "EXECUTE"
    assert d2["target_device"] == "fan"
    assert d2["requested_action"] == "OFF"
    assert db_session.query(Device).filter_by(id="fan").first().state == "OFF"


def test_scenario_2_turn_it_off_ambiguous_no_context(db_session, client, enrolled_auth):
    """
    SCENARIO 2:
      User: "Turn it off."
      Both fan and lights are plausible targets (no prior context).
      Expected: Ask for clarification.
    """
    sid = "sess-scenario-2-empty"
    headers = {"Authorization": f"Bearer {enrolled_auth['token']}"}

    resp = client.post("/voice/process", headers=headers, json={"text": "Turn it off.", "session_id": sid})
    assert resp.status_code == 200
    data = resp.json()
    assert data["decision"] == "CLARIFY"
    assert "clarification_question" in data
    assert "fan or the lights" in data["clarification_question"]
    # No device state changed
    assert db_session.query(Device).filter_by(id="fan").first().state == "OFF"


def test_scenario_3_answer_clarification_question(db_session, client, enrolled_auth):
    """
    SCENARIO 3:
      Assistant asks which device to turn off.
      User: "The fan."
      Expected: Resolve the pending question and validate the action.
    """
    sid = "sess-scenario-3"
    headers = enrolled_auth["make_headers"](sid)

    # First turn on the fan so turning it off is effective
    db_session.query(Device).filter_by(id="fan").update({"state": "ON"})
    db_session.commit()

    # Step 1: Ambiguous command triggers clarification
    r1 = client.post("/voice/process", headers=headers, json={"text": "Turn it off.", "session_id": sid})
    assert r1.status_code == 200
    assert r1.json()["decision"] == "CLARIFY"

    # Step 2: User answers "The fan."
    r2 = client.post("/voice/process", headers=headers, json={"text": "The fan.", "session_id": sid})
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["decision"] == "EXECUTE"
    assert d2["target_device"] == "fan"
    assert d2["requested_action"] == "OFF"
    assert db_session.query(Device).filter_by(id="fan").first().state == "OFF"


def test_scenario_4_unrelated_answer_to_clarification(db_session, client, enrolled_auth):
    """
    SCENARIO 4:
      User gives an unrelated answer to a clarification question.
      Expected: Do not execute the pending action incorrectly.
    """
    sid = "sess-scenario-4"
    headers = enrolled_auth["make_headers"](sid)

    # Turn 1: Trigger clarification
    r1 = client.post("/voice/process", headers=headers, json={"text": "Turn it off.", "session_id": sid})
    assert r1.status_code == 200
    assert r1.json()["decision"] == "CLARIFY"

    # Turn 2: User gives an unrelated response: "What is the weather today?"
    r2 = client.post("/voice/process", headers=headers, json={"text": "What is the weather today?", "session_id": sid})
    assert r2.status_code == 200
    d2 = r2.json()
    # Should not execute pending OFF action on any device!
    assert d2["decision"] != "EXECUTE"
    assert db_session.query(Device).filter_by(id="fan").first().state == "OFF"
    assert db_session.query(Device).filter_by(id="bedroom_light").first().state == "OFF"


def test_scenario_5_empty_conversation_history(db_session, client, enrolled_auth):
    """
    SCENARIO 5:
      Conversation history is empty.
      Expected: Do not invent missing context.
    """
    sid = "sess-scenario-5-fresh"
    headers = {"Authorization": f"Bearer {enrolled_auth['token']}"}

    context_svc = ContextService()
    dev, reason = context_svc.resolve_pronoun(sid, "OFF", db_session)
    assert dev is None
    assert "empty" in reason.lower() or "no prior" in reason.lower()

    # Query context endpoint
    r = client.get(f"/voice/context?session_id={sid}")
    assert r.status_code == 200
    data = r.json()
    assert data["last_device"] is None
    assert data["has_pending_clarification"] is False


def test_scenario_6_slm_malformed_data_handling(db_session):
    """
    SCENARIO 6:
      SLM returns malformed data.
      Expected: Reject malformed output and use safe fallback.
    """
    slm_svc = SLMService()
    mock_bad_provider = MagicMock(spec=BaseSLMProvider)
    mock_bad_provider.generate_proposal.side_effect = ValueError("Corrupt malformed JSON from LLM")

    with patch.object(slm_svc, "get_provider", return_value=mock_bad_provider):
        proposal = slm_svc.propose_intent("Turn on something", {}, [])
        # Should gracefully fallback without crashing
        assert proposal is not None
        assert proposal.requires_clarification is True
        assert "fallback" in proposal.reason.lower() or "unavailable" in proposal.reason.lower()


def test_scenario_7_slm_unavailable_or_timeout(db_session, client, enrolled_auth):
    """
    SCENARIO 7:
      SLM is unavailable or times out.
      Expected: Application remains operational and does not execute an unvalidated action.
    """
    sid = "sess-scenario-7"
    headers = enrolled_auth["make_headers"](sid)

    with patch.object(SLMService, "propose_intent", side_effect=TimeoutError("SLM gateway timeout 3.0s")):
        resp = client.post(
            "/voice/process",
            headers=headers,
            json={"text": "Make it comfortable.", "session_id": sid},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Fallback decision engine handles it safely without crashing
        assert data["decision"] in ("CLARIFY", "REJECT")
        # Devices remain safe
        assert db_session.query(Device).filter_by(id="fan").first().state == "OFF"


def test_scenario_8_slm_unsupported_device_action(db_session, client, enrolled_auth):
    """
    SCENARIO 8:
      SLM proposes an unsupported device action (e.g. DIM on Bedroom Light).
      Expected: Decision engine rejects the proposal.
    """
    slm_svc = SLMService()
    unsupported_proposal = SLMProposal(
        intent="CONTROL_DEVICE",
        target_device="bedroom_light",
        requested_action="DIM",
        confidence=0.99,  # High confidence should NOT override safety rules!
        reason="Model assumed dimmer switch was present",
    )

    devices = db_session.query(Device).all()
    is_valid, reason, _ = slm_svc.validate_proposal(unsupported_proposal, devices)
    assert is_valid is False
    assert "not supported" in reason.lower()

    # Also test via full API pipeline
    sid = "sess-scenario-8"
    headers = enrolled_auth["make_headers"](sid)
    resp = client.post(
        "/voice/process",
        headers=headers,
        json={"text": "Dim the bedroom light.", "session_id": sid},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["decision"] == "REJECT"
    assert "not support" in data["decision_reason"].lower()


def test_scenario_9_voice_auth_fails_no_device_action(db_session, client, enrolled_auth):
    """
    SCENARIO 9:
      Voice authentication fails.
      Expected: No normal device-control action occurs.
    """
    audio_wav = create_synthetic_wav(frequency=220.0, duration=1.0)
    fan_before = db_session.query(Device).filter_by(id="fan").first().state

    with patch.object(
        VoiceAuthService,
        "verify_speaker",
        return_value=(False, 0.35, "Voice not recognized.", "Similarity below threshold"),
    ):
        files = {"file": ("unauth.wav", audio_wav, "audio/wav")}
        resp = client.post("/voice/process-audio", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "REJECT"
        assert data["speaker_verified"] is False
        assert data["execution_status"] == "REJECTED"

    assert db_session.query(Device).filter_by(id="fan").first().state == fan_before


def test_scenario_10_direct_api_without_auth_rejected(db_session, client):
    """
    SCENARIO 10:
      Backend device-control endpoint is called without valid authorization.
      Expected: Reject the request (HTTP 401).
    """
    resp = client.post("/devices/fan/command", json={"action": "ON"})
    assert resp.status_code == 401
    assert "authentication required" in resp.json()["detail"].lower()


def test_scenario_11_device_execution_failure_recorded(db_session, client, enrolled_auth):
    """
    SCENARIO 11:
      Device execution fails (e.g. simulated hardware error).
      Expected: Record the failure accurately instead of reporting success.
    """
    sid = "sess-scenario-11"
    headers = enrolled_auth["make_headers"](sid)

    with patch.object(
        DeviceService,
        "execute_action",
        return_value={
            "success": False,
            "device_id": "fan",
            "action": "ON",
            "previous_state": "OFF",
            "new_state": "OFF",
            "message": "Hardware relay connection failed.",
            "error": "RELAY_TIMEOUT",
        },
    ):
        resp = client.post(
            "/voice/process",
            headers=headers,
            json={"text": "Turn on the fan.", "session_id": sid},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_status"] == "FAILED"
        assert "failed" in data["message"].lower()

        # Verify in database that failure is recorded
        interaction = db_session.query(Interaction).filter_by(session_id=sid).first()
        assert interaction is not None
        assert interaction.execution_status == "FAILED"


def test_scenario_12_conversation_history_retention_policy(db_session):
    """
    SCENARIO 12:
      Conversation history exceeds its configured limit.
      Expected: Apply the configured retention policy (trims oldest).
    """
    conv_svc = ConversationService(db_session)
    sid = "sess-retention-test"

    # Temporarily set limit to 5
    original_limit = settings.max_conversation_history
    settings.max_conversation_history = 5

    try:
        # Insert 8 interactions
        for i in range(8):
            conv_svc.record_turn(
                session_id=sid,
                user_text=f"Command {i}",
                recognized_text=f"Command {i}",
                input_mode="text",
                intent="CONTROL_DEVICE",
                entities={},
                decision_outcome="EXECUTE",
                decision_reason=f"Reason {i}",
            )

        history = conv_svc.get_history(sid)
        assert history.total_turns == 5
        assert len(history.turns) == 5
        # The oldest (Command 0, 1, 2) should have been pruned; oldest remaining is Command 3
        assert history.turns[0].user_text == "Command 3"
        assert history.turns[-1].user_text == "Command 7"
    finally:
        settings.max_conversation_history = original_limit
