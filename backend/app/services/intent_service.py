"""
Intent service — rule-based natural-language understanding for VoxEdge.

Extracts structured intents from transcribed text.  This replaces the
Phase 1 two-keyword matcher with a multi-device, multi-intent system
while keeping everything offline (no cloud LLM needed).

Supported intents:
    CONTROL_DEVICE  — turn on/off a device
    STATUS_CHECK    — ask about a device's state
    EMERGENCY       — request emergency assistance
    CANCEL          — cancel a pending action
    CONFIRM         — confirm a pending action
    HELP            — ask for help / list capabilities
    UNKNOWN         — unrecognised input
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ── Intent names (constants) ──────────────────────────────────────────────────
CONTROL_DEVICE = "CONTROL_DEVICE"
STATUS_CHECK = "STATUS_CHECK"
EMERGENCY = "EMERGENCY"
CANCEL = "CANCEL"
CONFIRM = "CONFIRM"
HELP = "HELP"
UNKNOWN = "UNKNOWN"

# ── Device vocabulary ─────────────────────────────────────────────────────────
# Maps spoken phrases → (device_id, device_type, location | None)
DEVICE_ALIASES: dict[str, tuple[str, str, str | None]] = {
    # Bedroom light
    "bedroom light": ("bedroom_light", "light", "bedroom"),
    "bedroom lamp": ("bedroom_light", "light", "bedroom"),
    "bed light": ("bedroom_light", "light", "bedroom"),
    "bedside light": ("bedroom_light", "light", "bedroom"),
    "bedside lamp": ("bedroom_light", "light", "bedroom"),
    # Living room light
    "living room light": ("living_room_light", "light", "living_room"),
    "living room lamp": ("living_room_light", "light", "living_room"),
    "hall light": ("living_room_light", "light", "living_room"),
    "lounge light": ("living_room_light", "light", "living_room"),
    # Fan
    "fan": ("fan", "fan", None),
    "bedroom fan": ("fan", "fan", "bedroom"),
    "ceiling fan": ("fan", "fan", None),
    # Generic — resolved later via context or clarification
    "light": (None, "light", None),  # ambiguous — which light?
    "lamp": (None, "light", None),
    "the light": (None, "light", None),
    "the lamp": (None, "light", None),
}

# ── Action vocabulary ─────────────────────────────────────────────────────────
ON_WORDS = {"on", "start", "enable", "activate", "switch on", "power on", "open"}
OFF_WORDS = {"off", "stop", "disable", "deactivate", "switch off", "power off", "close", "shut"}

# ── Emergency triggers ────────────────────────────────────────────────────────
EMERGENCY_PHRASES = [
    "help me", "emergency", "call for help", "i need help",
    "i've fallen", "i fell", "call ambulance", "call doctor",
    "i can't breathe", "chest pain", "i'm hurt", "sos",
    "someone help", "please help", "need assistance",
]

# ── Confirmation / cancellation ───────────────────────────────────────────────
CONFIRM_WORDS = {"yes", "yeah", "yep", "confirm", "sure", "okay", "ok", "do it", "go ahead", "proceed"}
CANCEL_WORDS = {"no", "nope", "cancel", "stop", "never mind", "nevermind", "forget it", "abort"}

# ── Status-check triggers ────────────────────────────────────────────────────
STATUS_PATTERNS = [
    r"\b(?:is|are)\b.*\b(?:on|off|running|working)\b",
    r"\bstatus\b",
    r"\bwhat.*state\b",
    r"\bhow.*(?:light|fan|lamp)\b",
    r"\bcheck\b.*\b(?:light|fan|lamp)\b",
]

# ── Help triggers ─────────────────────────────────────────────────────────────
HELP_PATTERNS = [
    r"\bwhat can you do\b",
    r"\bhelp\b",
    r"\bcommands\b",
    r"\bwhat.*commands\b",
    r"\blist.*(?:device|action)\b",
]


@dataclass
class IntentResult:
    """Structured output of intent extraction."""
    intent: str = UNKNOWN
    confidence: float = 0.0
    entities: dict = field(default_factory=dict)
    raw_text: str = ""


class IntentService:
    """
    Rule-based intent extractor.

    Confidence scoring rationale:
    - 1.0 = exact pattern match with fully resolved device + action
    - 0.8 = good match but device or action partially ambiguous
    - 0.6 = weak match requiring context resolution
    - 0.3 = very uncertain, likely needs clarification
    - 0.0 = no match
    """

    def extract(self, text: str) -> IntentResult:
        """Extract intent and entities from raw text."""
        if not text or not text.strip():
            return IntentResult(
                intent=UNKNOWN,
                confidence=0.0,
                raw_text=text or "",
                entities={"reason": "empty_input"},
            )

        cleaned = text.lower().strip()

        # ── Priority 1: Emergency ─────────────────────────────────────────
        result = self._check_emergency(cleaned)
        if result:
            return result

        # ── Priority 2: Cancel / Confirm ──────────────────────────────────
        result = self._check_cancel_confirm(cleaned)
        if result:
            return result

        # ── Priority 3: Help ──────────────────────────────────────────────
        result = self._check_help(cleaned)
        if result:
            return result

        # ── Priority 4: Status check ──────────────────────────────────────
        result = self._check_status(cleaned)
        if result:
            return result

        # ── Priority 5: Device control ────────────────────────────────────
        result = self._check_control(cleaned)
        if result:
            return result

        # ── Fallback ──────────────────────────────────────────────────────
        return IntentResult(
            intent=UNKNOWN,
            confidence=0.0,
            raw_text=text,
            entities={"reason": "no_matching_pattern"},
        )

    # ── Private matchers ──────────────────────────────────────────────────

    def _check_emergency(self, text: str) -> IntentResult | None:
        for phrase in EMERGENCY_PHRASES:
            if phrase in text:
                return IntentResult(
                    intent=EMERGENCY,
                    confidence=1.0,
                    raw_text=text,
                    entities={"trigger_phrase": phrase},
                )
        return None

    def _check_cancel_confirm(self, text: str) -> IntentResult | None:
        words = set(text.split())
        # Check multi-word phrases first
        for phrase in CANCEL_WORDS:
            if " " in phrase and phrase in text:
                return IntentResult(
                    intent=CANCEL, confidence=0.9, raw_text=text, entities={}
                )
        for phrase in CONFIRM_WORDS:
            if " " in phrase and phrase in text:
                return IntentResult(
                    intent=CONFIRM, confidence=0.9, raw_text=text, entities={}
                )
        # Then single words
        if words & CANCEL_WORDS:
            return IntentResult(
                intent=CANCEL, confidence=0.8, raw_text=text, entities={}
            )
        if words & CONFIRM_WORDS:
            return IntentResult(
                intent=CONFIRM, confidence=0.8, raw_text=text, entities={}
            )
        return None

    def _check_help(self, text: str) -> IntentResult | None:
        for pattern in HELP_PATTERNS:
            if re.search(pattern, text):
                return IntentResult(
                    intent=HELP, confidence=0.9, raw_text=text, entities={}
                )
        return None

    def _check_status(self, text: str) -> IntentResult | None:
        for pattern in STATUS_PATTERNS:
            if re.search(pattern, text):
                device_info = self._extract_device(text)
                entities = {}
                confidence = 0.7
                if device_info:
                    entities["device"] = device_info["device_id"]
                    entities["device_type"] = device_info["device_type"]
                    if device_info.get("location"):
                        entities["location"] = device_info["location"]
                    if device_info["device_id"] is not None:
                        confidence = 0.9
                return IntentResult(
                    intent=STATUS_CHECK,
                    confidence=confidence,
                    raw_text=text,
                    entities=entities,
                )
        return None

    def _check_control(self, text: str) -> IntentResult | None:
        """Extract CONTROL_DEVICE intent with device + action entities."""
        action = self._extract_action(text)
        device_info = self._extract_device(text)

        if action is None and device_info is None:
            return None  # no signal at all

        entities: dict = {}
        confidence = 0.0

        # ── Action ────────────────────────────────────────────────────────
        if action:
            entities["action"] = action
            confidence += 0.4
        else:
            entities["action"] = None
            entities["action_missing"] = True

        # ── Device ────────────────────────────────────────────────────────
        if device_info:
            entities["device"] = device_info["device_id"]
            entities["device_type"] = device_info["device_type"]
            if device_info.get("location"):
                entities["location"] = device_info["location"]
            if device_info["device_id"] is not None:
                confidence += 0.5  # fully resolved device
            else:
                confidence += 0.2  # ambiguous device (e.g. just "light")
                entities["device_ambiguous"] = True
        else:
            # Check for pronoun references ("turn it off")
            if re.search(r"\b(it|that|this|the same)\b", text):
                entities["pronoun_reference"] = True
                confidence += 0.2
            else:
                entities["device_missing"] = True

        # Need at least some signal to classify as CONTROL_DEVICE
        if confidence < 0.3:
            return None

        # Cap confidence
        confidence = min(confidence, 1.0)

        return IntentResult(
            intent=CONTROL_DEVICE,
            confidence=round(confidence, 2),
            raw_text=text,
            entities=entities,
        )

    def _extract_action(self, text: str) -> str | None:
        """Determine ON or OFF from the text."""
        words = text.split()
        word_set = set(words)

        # Check multi-word actions first ("switch on", "turn off", etc.)
        for phrase in sorted(ON_WORDS, key=len, reverse=True):
            if " " in phrase and phrase in text:
                return "ON"
        for phrase in sorted(OFF_WORDS, key=len, reverse=True):
            if " " in phrase and phrase in text:
                return "OFF"

        # Common patterns: "turn on the...", "turn the ... on"
        if re.search(r"\bturn\s+on\b", text):
            return "ON"
        if re.search(r"\bturn\s+off\b", text):
            return "OFF"
        if re.search(r"\bturn\b.*\bon\b", text):
            return "ON"
        if re.search(r"\bturn\b.*\boff\b", text):
            return "OFF"

        # Single-word actions
        if word_set & ON_WORDS:
            return "ON"
        if word_set & OFF_WORDS:
            return "OFF"

        # Vosk mishears "off" as "of" frequently
        if "of" in word_set and ("fan" in word_set or "light" in word_set or "lamp" in word_set):
            return "OFF"

        return None

    def _extract_device(self, text: str) -> dict | None:
        """
        Find the best device match in the text.

        Returns dict with device_id, device_type, location, or None.
        Tries longest alias first to prefer "bedroom light" over just "light".
        """
        # Sort aliases by length (longest first) for greedy matching
        for alias in sorted(DEVICE_ALIASES.keys(), key=len, reverse=True):
            if alias in text:
                device_id, device_type, location = DEVICE_ALIASES[alias]
                return {
                    "device_id": device_id,
                    "device_type": device_type,
                    "location": location,
                    "matched_alias": alias,
                }
        return None
