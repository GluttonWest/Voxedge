"""
VoxEdge Evaluation Framework — Baseline vs Enhanced comparison.

This test suite runs the same set of voice commands through TWO pipelines:

  BASELINE:
    - Phase 1 keyword matching (exact "fan on" / "fan off" only)
    - No disambiguation, no context, no safety checks, no emergency

  ENHANCED:
    - Phase 2 reliability-aware pipeline
    - Multi-device intent extraction
    - Context-aware pronoun resolution
    - Ambiguity detection + clarification
    - Emergency detection + escalation
    - Action validation + confidence thresholds

Each test case is scored on:
  - correctness: did the system produce the right outcome? (0 or 1)
  - safety:      did the system prevent an unsafe action? (0 or 1)
  - usability:   did the system respond helpfully? (0 or 1)

Final metrics per pipeline:
  - accuracy = correct / total
  - safety_rate = safe decisions / safety-relevant cases
  - usability_rate = usable responses / total

Usage:
    cd backend
    .venv\\Scripts\\pytest tests/test_evaluation.py -v --tb=short
"""

import json
import sys
from dataclasses import dataclass, field

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# ── Adjust path so we can import from app ─────────────────────────────────────
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from app.database.session import Base
from app.models.device import Device
from app.services.context_service import ContextService
from app.services.decision_engine import DecisionEngine
from app.services.intent_service import IntentService


# ── Test fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def db() -> Session:
    """In-memory SQLite database for isolated tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    session = TestSession()

    # Seed devices
    devices = [
        Device(
            id="bedroom_light", name="Bedroom Light", device_type="light",
            location="bedroom", state="OFF",
            supported_actions='["ON", "OFF"]',
        ),
        Device(
            id="living_room_light", name="Living Room Light", device_type="light",
            location="living_room", state="OFF",
            supported_actions='["ON", "OFF"]',
        ),
        Device(
            id="fan", name="Fan", device_type="fan",
            location="bedroom", state="OFF",
            supported_actions='["ON", "OFF"]',
        ),
    ]
    session.add_all(devices)
    session.commit()

    yield session
    session.close()


@pytest.fixture
def intent_service() -> IntentService:
    return IntentService()


@pytest.fixture
def context_service() -> ContextService:
    return ContextService()


# ── Baseline simulator ────────────────────────────────────────────────────────

@dataclass
class BaselineResult:
    """Simulates Phase 1 behaviour: keyword-only matching for the fan."""
    action: str | None = None
    device: str | None = None
    executed: bool = False
    message: str = ""


def baseline_process(text: str) -> BaselineResult:
    """
    Phase 1 logic (from main.py): only matches "fan on" / "fan off".

    Returns a result simulating what Phase 1 would do.
    """
    words = text.lower().strip().split()

    # Phase 1 only supported the fan with exact keyword matching
    if "fan" in words:
        if "on" in words:
            return BaselineResult(
                action="ON", device="fan", executed=True,
                message="Fan turned ON",
            )
        if "off" in words:
            return BaselineResult(
                action="OFF", device="fan", executed=True,
                message="Fan turned OFF",
            )

    # Phase 1 had no response for unrecognised commands
    return BaselineResult(message="Command not recognized")


# ── Test cases ────────────────────────────────────────────────────────────────

@dataclass
class EvalCase:
    id: str
    text: str
    expected_intent: str
    expected_device: str | None
    expected_action: str | None
    expected_decision: str  # EXECUTE, CLARIFY, REJECT, ESCALATE
    category: str  # "correctness", "safety", "usability", "context", "emergency"
    description: str
    session_setup: list[dict] = field(default_factory=list)  # prior commands for context


TEST_CASES: list[EvalCase] = [
    # ── Basic device commands (correctness) ───────────────────────────────
    EvalCase(
        id="C1", text="turn on the fan",
        expected_intent="CONTROL_DEVICE", expected_device="fan",
        expected_action="ON", expected_decision="EXECUTE",
        category="correctness", description="Simple fan on command",
    ),
    EvalCase(
        id="C2", text="turn off the fan",
        expected_intent="CONTROL_DEVICE", expected_device="fan",
        expected_action="OFF", expected_decision="EXECUTE",
        category="correctness", description="Simple fan off command",
    ),
    EvalCase(
        id="C3", text="turn on the bedroom light",
        expected_intent="CONTROL_DEVICE", expected_device="bedroom_light",
        expected_action="ON", expected_decision="EXECUTE",
        category="correctness", description="Bedroom light on — Phase 1 cannot handle this",
    ),
    EvalCase(
        id="C4", text="switch off the living room light",
        expected_intent="CONTROL_DEVICE", expected_device="living_room_light",
        expected_action="OFF", expected_decision="EXECUTE",
        category="correctness", description="Living room light off with 'switch off' phrasing",
    ),
    EvalCase(
        id="C5", text="fan off",
        expected_intent="CONTROL_DEVICE", expected_device="fan",
        expected_action="OFF", expected_decision="EXECUTE",
        category="correctness", description="Minimal phrasing",
    ),

    # ── Ambiguity detection (usability) ───────────────────────────────────
    EvalCase(
        id="U1", text="turn off the light",
        expected_intent="CONTROL_DEVICE", expected_device=None,
        expected_action="OFF", expected_decision="CLARIFY",
        category="usability",
        description="Ambiguous device — should ask which light",
    ),
    EvalCase(
        id="U2", text="what can you do",
        expected_intent="HELP", expected_device=None,
        expected_action=None, expected_decision="REJECT",
        category="usability", description="Help request",
    ),
    EvalCase(
        id="U3", text="blah blah random words",
        expected_intent="UNKNOWN", expected_device=None,
        expected_action=None, expected_decision="REJECT",
        category="usability", description="Gibberish — should reject gracefully",
    ),

    # ── Context resolution ────────────────────────────────────────────────
    EvalCase(
        id="X1", text="turn it off",
        expected_intent="CONTROL_DEVICE", expected_device="fan",
        expected_action="OFF", expected_decision="EXECUTE",
        category="context",
        description="Pronoun resolution after fan interaction",
        session_setup=[{"device_id": "fan", "device_type": "fan", "action": "ON", "intent": "CONTROL_DEVICE"}],
    ),

    # ── Emergency detection (safety) ──────────────────────────────────────
    EvalCase(
        id="S1", text="help me I've fallen",
        expected_intent="EMERGENCY", expected_device=None,
        expected_action=None, expected_decision="ESCALATE",
        category="safety", description="Emergency phrase detection",
    ),
    EvalCase(
        id="S2", text="call for help please",
        expected_intent="EMERGENCY", expected_device=None,
        expected_action=None, expected_decision="ESCALATE",
        category="safety", description="Emergency with polite phrasing",
    ),
    EvalCase(
        id="S3", text="I can't breathe",
        expected_intent="EMERGENCY", expected_device=None,
        expected_action=None, expected_decision="ESCALATE",
        category="safety", description="Medical emergency phrase",
    ),

    # ── Status check ──────────────────────────────────────────────────────
    EvalCase(
        id="C6", text="is the fan on",
        expected_intent="STATUS_CHECK", expected_device="fan",
        expected_action=None, expected_decision="EXECUTE",
        category="correctness", description="Status check for fan",
    ),
]


# ── Scoring ───────────────────────────────────────────────────────────────────

@dataclass
class Score:
    correct: int = 0
    total: int = 0
    safety_correct: int = 0
    safety_total: int = 0
    usability_correct: int = 0
    usability_total: int = 0


def score_baseline(tc: EvalCase, result: BaselineResult) -> dict:
    """Score a baseline result against the test case."""
    correct = False
    safe = True
    usable = False

    if tc.expected_decision == "EXECUTE":
        correct = (
            result.executed
            and result.device == tc.expected_device
            and result.action == tc.expected_action
        )
        usable = result.executed or result.message != "Command not recognized"
    elif tc.expected_decision == "CLARIFY":
        correct = not result.executed  # baseline can't clarify, but at least shouldn't execute wrongly
        usable = False  # no clarification = bad usability
    elif tc.expected_decision == "REJECT":
        correct = not result.executed
        usable = result.message != "Command not recognized"  # at least some message
    elif tc.expected_decision == "ESCALATE":
        correct = False  # baseline can never escalate
        safe = False  # failing to escalate an emergency is unsafe
        usable = False

    return {"correct": correct, "safe": safe, "usable": usable}


def score_enhanced(tc: EvalCase, decision) -> dict:
    """Score an enhanced pipeline result against the test case."""
    correct = decision.outcome == tc.expected_decision
    if correct and tc.expected_device:
        correct = decision.target_device == tc.expected_device
    if correct and tc.expected_action:
        correct = decision.requested_action == tc.expected_action

    safe = True
    if tc.category == "safety":
        safe = decision.outcome == "ESCALATE"

    usable = decision.message and len(decision.message) > 5

    return {"correct": correct, "safe": safe, "usable": usable}


# ── Test: run all cases and print comparison ──────────────────────────────────

def test_evaluation_comparison(db, intent_service, context_service):
    """
    Run all test cases through both pipelines and compare results.

    This is the main evaluation test that produces the comparison table.
    """
    baseline_scores = Score()
    enhanced_scores = Score()

    results = []

    for tc in TEST_CASES:
        # ── Baseline ──────────────────────────────────────────────────────
        b_result = baseline_process(tc.text)
        b_score = score_baseline(tc, b_result)

        baseline_scores.total += 1
        if b_score["correct"]:
            baseline_scores.correct += 1
        if tc.category == "safety":
            baseline_scores.safety_total += 1
            if b_score["safe"]:
                baseline_scores.safety_correct += 1
        if tc.category == "usability":
            baseline_scores.usability_total += 1
            if b_score["usable"]:
                baseline_scores.usability_correct += 1

        # ── Enhanced ──────────────────────────────────────────────────────
        session_id = f"eval-{tc.id}"

        # Set up context if needed
        if tc.session_setup:
            for setup in tc.session_setup:
                context_service.add_entry(
                    session_id=session_id,
                    device_id=setup["device_id"],
                    device_type=setup["device_type"],
                    action=setup["action"],
                    intent=setup["intent"],
                )

        intent_result = intent_service.extract(tc.text)
        engine = DecisionEngine(db=db, context=context_service)
        decision = engine.decide(intent_result, session_id)

        e_score = score_enhanced(tc, decision)

        enhanced_scores.total += 1
        if e_score["correct"]:
            enhanced_scores.correct += 1
        if tc.category == "safety":
            enhanced_scores.safety_total += 1
            if e_score["safe"]:
                enhanced_scores.safety_correct += 1
        if tc.category == "usability":
            enhanced_scores.usability_total += 1
            if e_score["usable"]:
                enhanced_scores.usability_correct += 1

        results.append({
            "id": tc.id,
            "text": tc.text,
            "category": tc.category,
            "expected": tc.expected_decision,
            "baseline_correct": b_score["correct"],
            "enhanced_correct": e_score["correct"],
            "enhanced_decision": decision.outcome,
        })

    # ── Print comparison table ────────────────────────────────────────────
    print("\n" + "=" * 90)
    print("VOXEDGE EVALUATION RESULTS - BASELINE vs ENHANCED")
    print("=" * 90)
    print(f"{'ID':<5} {'Command':<35} {'Cat':<12} {'Expected':<10} {'Base':<6} {'Enh':<6} {'Enh Dec':<10}")
    print("-" * 90)
    for r in results:
        b_mark = "[OK]" if r["baseline_correct"] else "[X]"
        e_mark = "[OK]" if r["enhanced_correct"] else "[X]"
        print(
            f"{r['id']:<5} {r['text'][:33]:<35} {r['category']:<12} "
            f"{r['expected']:<10} {b_mark:<6} {e_mark:<6} {r['enhanced_decision']:<10}"
        )
    print("-" * 90)

    # ── Summary ───────────────────────────────────────────────────────────
    b_acc = baseline_scores.correct / baseline_scores.total if baseline_scores.total else 0
    e_acc = enhanced_scores.correct / enhanced_scores.total if enhanced_scores.total else 0
    b_safety = baseline_scores.safety_correct / baseline_scores.safety_total if baseline_scores.safety_total else 1
    e_safety = enhanced_scores.safety_correct / enhanced_scores.safety_total if enhanced_scores.safety_total else 1
    b_usability = baseline_scores.usability_correct / baseline_scores.usability_total if baseline_scores.usability_total else 0
    e_usability = enhanced_scores.usability_correct / enhanced_scores.usability_total if enhanced_scores.usability_total else 0

    print(f"\n{'Metric':<25} {'Baseline':<15} {'Enhanced':<15} {'Improvement':<15}")
    print("-" * 70)
    print(f"{'Accuracy':<25} {b_acc:.1%}{'':<10} {e_acc:.1%}{'':<10} {(e_acc - b_acc):+.1%}")
    print(f"{'Safety Rate':<25} {b_safety:.1%}{'':<10} {e_safety:.1%}{'':<10} {(e_safety - b_safety):+.1%}")
    print(f"{'Usability':<25} {b_usability:.1%}{'':<10} {e_usability:.1%}{'':<10} {(e_usability - b_usability):+.1%}")
    print(f"{'Total Cases':<25} {baseline_scores.total:<15} {enhanced_scores.total:<15}")
    print("=" * 90 + "\n")

    # ── Assertions ────────────────────────────────────────────────────────
    assert e_acc > b_acc, f"Enhanced accuracy ({e_acc:.1%}) should exceed baseline ({b_acc:.1%})"
    assert e_safety >= b_safety, "Enhanced safety should be at least as good as baseline"
    assert e_acc >= 0.8, f"Enhanced accuracy should be ≥80%, got {e_acc:.1%}"


# ── Individual unit tests ─────────────────────────────────────────────────────

def test_intent_extraction_control(intent_service):
    """Test that 'turn on the bedroom light' extracts the correct intent."""
    result = intent_service.extract("turn on the bedroom light")
    assert result.intent == "CONTROL_DEVICE"
    assert result.entities.get("device") == "bedroom_light"
    assert result.entities.get("action") == "ON"
    assert result.confidence >= 0.8


def test_intent_extraction_emergency(intent_service):
    """Test that 'help me' triggers EMERGENCY."""
    result = intent_service.extract("help me please")
    assert result.intent == "EMERGENCY"
    assert result.confidence == 1.0


def test_intent_extraction_unknown(intent_service):
    """Test that gibberish returns UNKNOWN."""
    result = intent_service.extract("xyzzy plugh")
    assert result.intent == "UNKNOWN"


def test_context_resolution(db, intent_service, context_service):
    """Test pronoun resolution with context."""
    session_id = "test-ctx"
    context_service.add_entry(
        session_id=session_id,
        device_id="fan",
        device_type="fan",
        action="ON",
        intent="CONTROL_DEVICE",
    )

    ir = intent_service.extract("turn it off")
    engine = DecisionEngine(db=db, context=context_service)
    decision = engine.decide(ir, session_id)

    assert decision.outcome == "EXECUTE"
    assert decision.target_device == "fan"
    assert decision.requested_action == "OFF"


def test_ambiguous_device(db, intent_service, context_service):
    """Test that ambiguous 'the light' triggers CLARIFY in fresh session."""
    ir = intent_service.extract("turn off the light")
    engine = DecisionEngine(db=db, context=context_service)
    decision = engine.decide(ir, "fresh-session")

    assert decision.outcome == "CLARIFY"


def test_emergency_escalation(db, intent_service, context_service):
    """Test emergency detection produces ESCALATE."""
    ir = intent_service.extract("I can't breathe")
    engine = DecisionEngine(db=db, context=context_service)
    decision = engine.decide(ir, "emergency-test")

    assert decision.outcome == "ESCALATE"
