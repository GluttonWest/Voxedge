# VoxEdge

**VoxEdge** is a reliability-aware, voice-controlled assistive system for elderly, motor-impaired, and bedridden users. It combines offline speech recognition, speaker verification, deterministic intent handling, conversation context, simulated smart devices, and an emergency workflow in one local application.

The repository contains two usable experiences:

- **Phase 1 desktop prototype:** an offline microphone loop that controls a Tkinter fan simulator after speaker verification.
- **Phase 2 web application:** a FastAPI backend and React dashboard for voice/text commands, device control, safety decisions, conversation history, activity logs, emergency events, and evaluation.

> VoxEdge is a research/demo system. Device actions and emergency contacts are simulated; it is not a medical alert service or a replacement for emergency services.

## What it can do

### Voice and authentication

- Record three microphone samples and create a normalized 256-dimensional Resemblyzer speaker profile.
- Transcribe WAV audio locally with Vosk.
- Verify the speaker before executing voice commands.
- Issue short-lived session tokens after successful voice verification.
- Fail closed when there is no enrolled profile, invalid audio, a verification failure, or a voice-processing error.
- Accept either recorded audio or typed text through the web dashboard.

### Natural-language command handling

The rule-based intent service recognizes:

- Device control: turn devices **ON** or **OFF**.
- Status checks such as “is the fan on?”
- Help, confirmation, and cancellation responses.
- Emergency phrases such as “I fell”, “help me”, and “I can’t breathe”.
- Indirect requests such as “it’s too dark” and “I’m feeling hot”.
- Unknown devices and unsupported actions, which are rejected instead of executed.

Every command produces one of four explicit outcomes:

| Outcome | Meaning |
| --- | --- |
| `EXECUTE` | The request is understood, authorized, and applied. |
| `CLARIFY` | The request is plausible but ambiguous; the assistant asks a follow-up question. |
| `REJECT` | The request is unsafe, unsupported, unauthenticated, malformed, or too uncertain. |
| `ESCALATE` | A distress signal creates an emergency event and simulated contact dispatch. |

### Context and safety

- Resolve follow-ups such as “turn it off” using the recent session context.
- Keep a bounded conversation history with a configurable retention limit.
- Ask for clarification when multiple lights or another device target could match.
- Support confirmation and cancellation of pending clarifications.
- Use an optional local/ Ollama-compatible small-language-model proposal layer as a bounded aid; deterministic validation remains authoritative.
- Record interaction and device-action audit data in SQLite.

### Dashboard and monitoring

The React dashboard includes:

- Overview with live device status, recent decisions, emergency shortcut, and evaluation summary.
- Voice Assistant for enrollment, audio commands, text commands, and conversation history.
- Device Control for the simulated bedroom light, living-room light, and fan.
- Activity for interaction and device-action history.
- Emergency for triggering, reviewing, and updating simulated incidents.
- Evaluation for running and filtering the baseline-versus-enhanced benchmark.

## Architecture

```text
Microphone / typed text
          |
          v
  Vosk transcription + Resemblyzer speaker verification
          |
          v
 Intent extraction -> context resolution -> decision engine
          |
     +----+---------+-----------+-----------+
     |              |           |           |
 EXECUTE        CLARIFY     REJECT      ESCALATE
 device state   follow-up   no action   emergency event
```

The Phase 2 backend is organized into:

- `api/` — FastAPI routes for voice, decisions, devices, activity, emergency, system, and evaluation.
- `services/` — intent extraction, decision policy, context, conversation retention, device simulation, emergency handling, evaluation, SLM proposals, and voice authentication.
- `models/` and `schemas/` — SQLAlchemy persistence models and Pydantic request/response types.

## Repository layout

```text
Voxedge/
├── backend/
│   ├── app/
│   │   ├── api/              # REST endpoints
│   │   ├── core/             # Environment-backed settings
│   │   ├── database/         # SQLite session and table initialization
│   │   ├── models/           # Device, interaction, activity, emergency models
│   │   ├── schemas/          # API validation schemas
│   │   └── services/         # Core voice, intent, context, decision, and safety logic
│   ├── tests/                # Feature and evaluation tests
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── api/              # Typed backend client
│   │   ├── components/       # Shared layout
│   │   └── pages/            # Dashboard application views
│   └── package.json
├── model/                    # Vosk model assets expected by the local ASR pipeline
├── enrollment/               # Generated WAV samples (ignored by Git)
├── main.py                   # Phase 1 offline voice loop
├── fan_simulator.py          # Phase 1 Tkinter output simulator
├── record_enrollment.py      # Record three enrollment clips
├── enroll.py                 # Build enrolled_voice.npy
├── requirements.txt          # Phase 1 Python dependencies
└── start_*.bat               # Windows launch helpers
```

## Requirements

- Python 3.11 or newer
- Node.js and npm (the frontend uses Vite)
- A working microphone for enrollment and live audio commands
- A local Vosk model in `model/`
- Tkinter for the Phase 1 desktop simulator

The repository currently contains Vosk model assets. If your checkout does not contain a usable model, download a compatible English model from the [Vosk models page](https://alphacephei.com/vosk/models) and extract it as `model/`.

## Setup

### 1. Create a voice profile

From the repository root:

```bash
python -m venv .venv311
```

Activate the environment:

```bash
# macOS/Linux
source .venv311/bin/activate

# Windows PowerShell
.venv311\Scripts\Activate.ps1
```

Install the Phase 1 dependencies and create the profile:

```bash
pip install -r requirements.txt
python record_enrollment.py
python enroll.py
```

`record_enrollment.py` records exactly three non-silent, three-second clips in `enrollment/`. `enroll.py` averages their Resemblyzer embeddings and writes `enrolled_voice.npy` at the repository root. Add `--force` to `enroll.py` to replace an existing profile without an interactive prompt.

### 2. Run the Phase 1 desktop prototype

```bash
python main.py
```

Press Enter to record a command. The prototype transcribes the audio, checks the enrolled speaker, recognizes fan commands such as “turn on the fan” and “turn off the fan”, and updates the Tkinter fan simulator. No physical hardware is controlled.

### 3. Install backend dependencies

```bash
cd backend
python -m venv .venv
```

Activate `.venv` using the same platform-specific commands above, then install:

```bash
pip install -r requirements.txt
```

Optional configuration:

```bash
cp .env.example .env       # macOS/Linux
copy .env.example .env     # Windows
```

The defaults are suitable for local development. Important settings include:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./voxedge.db` | SQLite database location |
| `VOSK_MODEL_PATH` | `../model` | Vosk model directory when running from `backend/` |
| `ENROLLED_VOICE_PATH` | `../enrolled_voice.npy` | Saved speaker embedding |
| `SIMILARITY_THRESHOLD` | `0.65` | Speaker verification threshold |
| `INTENT_CONFIDENCE_THRESHOLD` | `0.6` | Minimum intent confidence |
| `CONTEXT_EXPIRY_SECONDS` | `120` | Context lifetime for pronoun resolution |
| `MAX_CLARIFICATION_ATTEMPTS` | `2` | Clarification retry limit |
| `MAX_CONVERSATION_HISTORY` | `50` | Retained turns per session |
| `SLM_PROVIDER` | `local` | `local`, `ollama`, or `mock` proposal provider |
| `SLM_MODEL_NAME` | `qwen2.5-0.5b` | SLM model name |
| `SLM_API_BASE` | `http://localhost:11434` | Ollama-compatible endpoint |
| `EMERGENCY_AUTO_TIMEOUT_SECONDS` | `300` | Emergency timeout setting |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | Backend bind address |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Allowed frontend origins |

The backend uses SQLite and creates/seeds the default devices on startup. Database files are ignored by Git.

### 4. Start the Phase 2 backend

From `backend/`:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open the generated API documentation at <http://127.0.0.1:8000/docs>. The root health response is available at <http://127.0.0.1:8000/>.

### 5. Start the frontend

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` requests to `http://127.0.0.1:8000`.

For a production frontend build:

```bash
npm run build
```

The frontend also provides `npm run lint`.

### Windows shortcut

After creating `.venv311`, installing the root and backend dependencies, and running `npm install` in `frontend/`, `start_voxedge.bat` launches the backend and frontend in separate command windows. The individual `start_backend.bat` and `start_frontend.bat` scripts can be used when only one service is needed.

## API reference

The backend registers the primary routes both directly and under the `/api` namespace. The frontend uses `/api`.

| Method | Frontend path | Purpose |
| --- | --- | --- |
| `GET` | `/api/voice/enrollment-status` | Check whether a voice profile exists. |
| `POST` | `/api/voice/enroll` | Upload an enrollment recording (`multipart/form-data`). |
| `DELETE` | `/api/voice/profile` | Remove the enrolled voice profile. |
| `POST` | `/api/voice/process-audio` | Verify a WAV command and process it. |
| `POST` | `/api/voice/process` | Process typed text, optionally with a session ID. |
| `GET` | `/api/voice/history` | Read bounded conversation history for a session. |
| `DELETE` | `/api/voice/history` | Clear history and context for a session. |
| `GET` | `/api/voice/context` | Inspect the current session context. |
| `POST` | `/api/decisions/confirm` | Answer a pending clarification or confirmation. |
| `GET` | `/api/devices` | List active simulated devices and states. |
| `GET` | `/api/devices/{device_id}` | Read one device. |
| `POST` | `/api/devices/{device_id}/command` | Directly control a device. Requires an `Authorization` header containing the issued session token. |
| `GET` | `/api/activity` | Read interaction and device-action audit history. |
| `POST` | `/api/emergency/trigger` | Create a simulated emergency event. |
| `GET` | `/api/emergency` | List emergency events. |
| `GET` | `/api/emergency/{event_id}` | Read one emergency event. |
| `PUT` | `/api/emergency/{event_id}` | Update an emergency status and notes. |
| `GET` | `/api/system/status` | Read health, model, enrollment, counts, and uptime. |
| `GET` | `/api/evaluation/run` | Run the baseline-versus-enhanced benchmark. |

Voice verification returns a session token on successful authentication. The frontend stores it locally and sends it for authenticated text, confirmation, and direct device-control requests. Emergency triggering is intentionally available as a simulated workflow and does not contact real emergency services.

## Evaluation and tests

Run the backend tests from the repository root:

```bash
cd backend
pytest -q
```

The tests cover:

- Baseline-versus-enhanced evaluation behavior.
- Intent extraction and ambiguity handling.
- Indirect requests and pronoun resolution.
- Confirmation, cancellation, and conversation retention.
- Speaker enrollment, verification, malformed audio, and fail-closed behavior.
- Authentication requirements for direct device control.
- Emergency escalation and device execution failure logging.

The web evaluation page and `GET /api/evaluation/run` expose the same benchmark data used by the evaluation service.

## Default simulated devices

On the first backend startup, SQLite is seeded with:

| ID | Name | Type | Location | Actions |
| --- | --- | --- | --- | --- |
| `bedroom_light` | Bedroom Light | Light | Bedroom | `ON`, `OFF` |
| `living_room_light` | Living Room Light | Light | Living room | `ON`, `OFF` |
| `fan` | Fan | Fan | Bedroom | `ON`, `OFF` |

All state changes are simulated and persisted in the local database. No real appliances are contacted.

## Security and operational notes

- Keep `AUTH_SECRET_KEY` private and override the development default before exposing the backend beyond localhost.
- Use HTTPS and a real secret-management solution for any non-demo deployment.
- The default CORS list is intended for local development.
- Do not commit `enrolled_voice.npy`, enrollment recordings, `.env`, or generated database files.
- The emergency subsystem records events and simulated notifications; it does not replace a certified emergency response system.

## License

No license file is currently included in the repository. Add a license before distributing or deploying VoxEdge.
