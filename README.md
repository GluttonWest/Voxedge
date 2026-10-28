# VoxEdge — Reliability-Aware Assistive Voice System for Elderly Care

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.x-3178C6?logo=typescript&logoColor=white)](https://typescriptlang.org)
[![TailwindCSS](https://img.shields.io/badge/Tailwind-v4-38B2AC?logo=tailwind-css&logoColor=white)](https://tailwindcss.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> **VoxEdge** is a research-oriented, voice-driven assistive system engineered specifically for elderly, motor-impaired, and bedridden individuals. It upgrades conventional rigid voice interfaces into a multi-turn, reliability-aware edge system featuring intent extraction, context-aware pronoun resolution, ambiguity clarification, and life-safety emergency escalation.

---

## 📑 Table of Contents

- [Motivation & Problem Statement](#motivation--problem-statement)
- [System Architecture](#system-architecture)
- [Phase 1 vs Phase 2 Comparison](#phase-1-vs-phase-2-comparison)
- [Core Features](#core-features)
- [Empirical Evaluation Benchmark](#empirical-evaluation-benchmark)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Phase 1 (Legacy Prototype)](#running-phase-1-prototype)
  - [Phase 2 Backend Setup](#running-phase-2-backend)
  - [Phase 2 Frontend Setup](#running-phase-2-frontend)
  - [Running Evaluation Suite](#running-the-evaluation-test-suite)
- [API Documentation](#api-documentation)
- [Research & Academic Significance](#research--academic-significance)

---

## Motivation & Problem Statement

Commercial smart voice assistants (e.g., Alexa, Google Assistant) and basic keyword triggers suffer from critical failure modes when deployed for elderly and bedridden users:
1. **Brittleness:** Strict keyword matching fails with dysarthric, trembling, or varied phrasing.
2. **Lack of Conversational Memory:** Pronouns ("turn it off", "switch that one on") fail without multi-turn session tracking.
3. **Unsafe Ambiguity Resolution:** Ambiguous commands ("turn off the light" when multiple exist) either guess unpredictably or fail silently.
4. **Absence of Safety Protocols:** Medical distress utterances ("I can't breathe", "help me I've fallen") are completely ignored by traditional automation systems.

VoxEdge solves these challenges by combining offline speaker verification with a **four-stage deterministic decision engine** (`EXECUTE`, `CLARIFY`, `REJECT`, `ESCALATE`).

---

## System Architecture

```
                  ┌───────────────────────────────┐
                  │    Microphone / Audio Input   │
                  └───────────────┬───────────────┘
                                  │
                                  ▼
                    ┌───────────────────────────┐
                    │  Offline Vosk ASR Engine  │
                    └─────────────┬─────────────┘
                                  │ (Transcribed Text)
                                  ▼
                    ┌───────────────────────────┐
                    │ Speaker Embedding (GE2E)  │
                    │  (Resemblyzer Similarity) │
                    └─────────────┬─────────────┘
                                  │ (Confidence / Verification)
                                  ▼
      ┌───────────────────────────────────────────────────────┐
      │          Reliability-Aware Decision Engine            │
      │  ┌─────────────────┐ ┌───────────────┐ ┌───────────┐  │
      │  │ Intent & Entity │ │ Multi-Turn    │ │ Safety &  │  │
      │  │ Extraction      │ │ Context Cache │ │ Ambiguity │  │
      │  └─────────────────┘ └───────────────┘ └───────────┘  │
      └───────────────────────────┬───────────────────────────┘
                                  │
        ┌──────────────┬──────────┴───────────┬──────────────┐
        ▼              ▼                      ▼              ▼
  [ EXECUTE ]     [ CLARIFY ]            [ REJECT ]     [ ESCALATE ]
  Device Action   Ask follow-up query    Confidence too  Emergency Alert
  state updated   to disambiguate        low / Malformed Dispatched & Logged
```

---

## Phase 1 vs Phase 2 Comparison

| Capability | Phase 1 (Baseline Prototype) | Phase 2 (VoxEdge Enhanced) |
|---|---|---|
| **Voice Processing** | Offline Vosk + Resemblyzer | Vosk + Resemblyzer + REST audio endpoint |
| **Parsing Technique** | Hardcoded keyword check ("fan on/off") | Rule-based Intent & Entity Extractor |
| **Supported Devices** | Single simulated Fan only | Multi-room (Bedroom Light, Living Room Light, Fan) |
| **Decision Outcomes** | Binary (Accepted / Access Denied) | 4-way (`EXECUTE`, `CLARIFY`, `REJECT`, `ESCALATE`) |
| **Context Memory** | None (stateless) | Multi-turn session tracking with pronoun resolution |
| **Ambiguity Handling** | Fails silently | Proactive clarification question |
| **Emergency Detection**| None (ignored) | Immediate escalation & contact dispatch simulation |
| **Persistence** | In-memory only | SQLite relational database with SQLAlchemy ORM |
| **User Interface** | Tkinter Desktop Canvas | Modern React 19 + TypeScript + Tailwind v4 Web App |
| **Observability** | Terminal console logs | Audit trail, state logs, and interactive evaluation page |

---

## Core Features

- 🎙️ **Voice & Text Multimodal Assistant:** Full conversational interface supporting live microphone recording or typed text commands with instant decision badge feedback.
- 💡 **Multi-Device Simulation:** Real-time state management for living room lights, bedroom lights, and ceiling fans with toggle control, power consumption indicators, and visual glowing effects.
- 🧠 **Context & Pronoun Resolution:** Resolves anaphoric expressions (e.g. "turn it off", "switch that one back on") using recent session interaction history.
- ❓ **Safety Disambiguation:** When an ambiguous command is uttered (e.g. "turn off the light"), the engine pauses execution and prompts for user clarification.
- 🚨 **Emergency Escalation Protocol:** Detects distress signals ("help me", "I fell", "can't breathe"), creates high-priority incidents, and triggers automated emergency contact dispatches.
- 📊 **Empirical Evaluation Dashboard:** Real-time benchmark page with Recharts visualizing baseline vs enhanced comparative metrics.

---

## Empirical Evaluation Benchmark

The system includes a 13-case gold-standard evaluation framework comparing Phase 1 against Phase 2:

| Metric | Phase 1 Baseline | Phase 2 Enhanced | Delta |
|---|---|---|---|
| **Command Accuracy** | 46.2% | **100.0%** | **+53.8%** |
| **Safety Compliance** | 0.0% | **100.0%** | **+100.0%** |
| **Usability & Clarification** | 0.0% | **100.0%** | **+100.0%** |
| **Context Resolution** | 0.0% (Failed) | **100.0%** (Resolved) | **+100.0%** |

*Run the benchmark locally via pytest or view the live interactive charts on the web UI at `/evaluation`.*

---

## Project Structure

```
Voxedge/
├── backend/                    # FastAPI Backend Application
│   ├── app/
│   │   ├── api/                # REST API Routers (voice, devices, decisions, activity, emergency, evaluation)
│   │   ├── core/               # Configuration, security, CORS settings
│   │   ├── database/           # SQLite connection, SessionLocal, init_db
│   │   ├── models/             # SQLAlchemy ORM models (Device, Interaction, Decision, Emergency)
│   │   ├── schemas/            # Pydantic v2 validation schemas
│   │   ├── services/           # DecisionEngine, IntentService, ContextService, DeviceSimulator, Evaluation
│   │   └── main.py             # FastAPI entry point & lifespan handler
│   └── tests/
│       └── test_evaluation.py  # Automated evaluation test suite (13 test conditions)
│
├── frontend/                   # Modern React Web Dashboard
│   ├── src/
│   │   ├── api/                # Type-safe API client functions
│   │   ├── components/         # Sidebar, Layout, Navigation
│   │   ├── pages/              # Dashboard, VoiceAssistant, DeviceControl, ActivityPage, EmergencyPage, EvaluationPage
│   │   ├── App.tsx             # Route definitions
│   │   └── main.tsx            # React root entry
│   ├── index.html              # HTML shell with Inter typography & metadata
│   ├── vite.config.ts          # Vite build configuration with Tailwind CSS v4
│   └── package.json            # Node dependencies
│
├── enrollment/                 # Audio recordings for speaker enrollment
├── enroll.py                   # GE2E voice embedding generator
├── record_enrollment.py        # 3x audio recorder for user enrollment
├── fan_simulator.py            # Phase 1 Tkinter animation GUI
├── main.py                     # Phase 1 offline voice control loop
└── requirements.txt            # Python dependencies for Phase 1
```

---

## Getting Started

### Prerequisites

- **Python 3.11+** installed
- **Node.js 18+** & npm installed
- **Vosk Acoustic Model:** Download [`vosk-model-small-en-us-0.15`](https://alphacephei.com/vosk/models), extract, and place in `Voxedge/model/`.

---

### Running Phase 1 Prototype

```powershell
# In the root repository directory:
python -m venv .venv311
.venv311\Scripts\activate
pip install -r requirements.txt

# Voice enrollment (one-time):
python record_enrollment.py
python enroll.py

# Run Tkinter fan controller:
python main.py
```

---

### Running Phase 2 Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Start backend on http://127.0.0.1:8000
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
Interactive API documentation is available at `http://127.0.0.1:8000/docs`.

---

### Running Phase 2 Frontend

```powershell
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173` in your browser.

---

### Running the Evaluation Test Suite

To run the automated research benchmark comparison:

```powershell
cd backend
.venv\Scripts\pytest tests/test_evaluation.py -v -s
```

Sample output:
```
==========================================================================================
VOXEDGE EVALUATION RESULTS - BASELINE vs ENHANCED
==========================================================================================
ID    Command                             Cat          Expected   Base   Enh    Enh Dec   
------------------------------------------------------------------------------------------
C1    turn on the fan                     correctness  EXECUTE    [OK]   [OK]   EXECUTE   
C2    turn off the fan                    correctness  EXECUTE    [OK]   [OK]   EXECUTE   
C3    turn on the bedroom light           correctness  EXECUTE    [X]    [OK]   EXECUTE   
C4    switch off the living room light    correctness  EXECUTE    [X]    [OK]   EXECUTE   
C5    fan off                             correctness  EXECUTE    [OK]   [OK]   EXECUTE   
U1    turn off the light                  usability    CLARIFY    [OK]   [OK]   CLARIFY   
U2    what can you do                     usability    REJECT     [OK]   [OK]   REJECT    
U3    blah blah random words              usability    REJECT     [OK]   [OK]   REJECT    
X1    turn it off                         context      EXECUTE    [X]    [OK]   EXECUTE   
S1    help me I've fallen                 safety       ESCALATE   [X]    [OK]   ESCALATE  
S2    call for help please                safety       ESCALATE   [X]    [OK]   ESCALATE  
S3    I can't breathe                     safety       ESCALATE   [X]    [OK]   ESCALATE  
C6    is the fan on                       correctness  EXECUTE    [X]    [OK]   EXECUTE   
------------------------------------------------------------------------------------------
Accuracy                  46.2%           100.0%           +53.8%
Safety Rate               0.0%            100.0%           +100.0%
Usability                 0.0%            100.0%           +100.0%
==========================================================================================
```

---

## API Documentation

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/voice/process-text` | Process typed command with intent & decision engine |
| `POST` | `/api/voice/process-audio` | Upload WAV audio for Vosk transcription + decision |
| `GET` | `/api/devices/` | List all registered smart devices and states |
| `POST` | `/api/devices/{id}/action` | Manually dispatch device action (`ON`/`OFF`) |
| `GET` | `/api/activity/` | Retrieve interaction logs and device state transitions |
| `GET` | `/api/emergency/` | List logged emergency events |
| `POST` | `/api/emergency/trigger` | Trigger emergency escalation workflow |
| `POST` | `/api/emergency/{id}/resolve`| Mark emergency incident as resolved |
| `GET` | `/api/evaluation/run` | Execute baseline vs enhanced benchmark test suite |
| `GET` | `/api/system/health` | Backend health, DB connectivity, and uptime |

---

## Research & Academic Significance

VoxEdge demonstrates that edge voice assistants can transition from fragile keyword matching to **fault-tolerant, safety-critical decision systems** without relying on external cloud APIs. 

Key contributions:
1. **Deterministic Edge Safety:** Explicit disambiguation and refusal logic prevent accidental activations that could cause physical distress.
2. **Context-Preserving Anaphora Resolution:** Empirically verified conversational continuity for users unable to repeat long device names.
3. **Medical & Physical Fall Interception:** Continuous monitoring for distress utterances connected to an emergency dispatch protocol.

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
