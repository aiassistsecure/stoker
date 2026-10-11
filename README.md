# Stoker

**Mobile command center for V100 + Hearth + PIN.**

Stoker is the one who tends the fire. This is the mobile face for a V100 GPU
node running Hearth model residency on the PIN p2p inference network — full
command and control from an iPhone.

**Philosophy:** Utility first, epic coating. Every pixel serves a purpose.
Every interaction is satisfying. Powerful underneath, delightful on top.

**Version:** v0.1.1 — incorporates Oracle architecture review patch notes
(2026-10-10). Status: APPROVE WITH CHANGES, all P0/P1/P2 applied.

---

## Table of Contents

1. [Vision](#vision)
2. [Core Features](#core-features)
3. [Architecture](#architecture)
4. [API Design](#api-design)
5. [UI/UX Design](#uiux-design)
6. [Security](#security)
7. [Tech Stack](#tech-stack)
8. [Development Setup](#development-setup)
9. [Roadmap & Release Gates](#roadmap--release-gates)
10. [License](#license)

---

## Vision

Open Safari on iOS. You see your V100 — live VRAM sectors, temperature,
compute load, all breathing in real time. Tap a model to load it. Watch it
materialize. Send it a prompt. Check what's routing through PIN. Open a
terminal and run `nvidia-smi`. All from your phone, from anywhere.

No App Store. No TestFlight. One secured URL.

The target user is one person: the operator of the node. This is not a
multi-tenant dashboard. It's a personal command deck.

**Model-agnostic by design.** Stoker manages whatever Hearth supports.
The control plane understands:

```
Model → Residency → Runtime → Endpoint → Health
```

Not `Imagine → llama.cpp → GPU`. This abstraction preserves compatibility
as inference infrastructure evolves.

---

## Core Features

### 1. Hearth — Model Residency

Hearth is the deterministic model residency protocol. Stoker dual-uses
Hearth's existing commands — it does not reimplement residency logic.

**Operation State Machine** (explicit, transactional):

```
DECLARED
   ↓
LOADING      ← weights streaming into VRAM
   ↓
WARMING      ← weights resident, runtime initializing
   ↓
RESIDENT     ← warm in VRAM
   ↓
SERVING      ← inference endpoint ready and accepting requests
```

Failure transitions carry actionable error details. Every async operation
(load, unload, restart) gets an `operation_id` for tracking.

**Critical distinction:** Model residency ≠ inference readiness. A model
occupying VRAM does not necessarily mean its inference endpoint is ready.
Stoker tracks both independently.

**Hearth protocol states** (mapped):
- `Unknown` — model declared but state not yet determined
- `Loading` — weights streaming into VRAM
- `Resident` — warm and serving
- `Lost` — evicted, GPU detached, or otherwise gone (with reason)
- `Failed` — load failed (with error)
- `Stopped` — intentionally unloaded

**Actions:**
- List all declared models with current state
- Load a model (returns `operation_id`, SSE streams progress)
- Unload / evict a model (frees VRAM)
- View per-model VRAM footprint
- View load history and failure reasons

**VRAM Dashboard:**
- Total VRAM discovered dynamically via NVML (not hardcoded)
- Used / free with per-model breakdown
- Visual sectors — each model's share as a glowing segment
- Warning threshold at 85%, critical at 95%
- All readings timestamped; stale values clearly marked

### 2. Inference

Chat interface to any `SERVING` model (not just `RESIDENT` — the endpoint
must be ready).

**Features:**
- Model picker (only shows SERVING models)
- Streaming token output via SSE (typed events, reconnect-safe)
- Conversation history (per session, stored server-side)
- System prompt configuration per model
- Temperature / top-p / max-tokens controls (collapsible advanced panel)
- Stop generation button (explicit cancellation, not just disconnect)
- Copy / share response

**Conversation storage policy:**
- Session storage is separate from operational logging
- Configurable retention period (default: 7 days)
- Prompt bodies are NEVER written to request logs or error logs
- Explicit session deletion available
- No offline caching of sensitive conversations

**Backend:** Proxies to the model's inference endpoint (llama-server or
equivalent) running on the V100 box. Stoker does not run inference itself.

### 3. PIN — Network Status

**Displays:**
- Node connection state (connected / connecting / disconnected)
- Operator identity and trust level
- Active routes — what's being served right now
- Request throughput (requests/min, tokens/sec)
- Uptime and last heartbeat
- Last confirmed update timestamp (critical for mobile reconnect)

**Actions:**
- Reconnect / restart pin-clientd (returns `operation_id`)
- View recent log tail (last 50 lines)

### 4. Shell — Command & Control

Full terminal access to the V100 Windows box.

**Features:**
- xterm.js frontend over websocket
- PowerShell (default) with CMD fallback
- Multiple concurrent sessions (tabs)
- Command favorites — saved one-tap commands:
  - `nvidia-smi`
  - `nvidia-smi dmon -s u`
  - Restart inference server
  - `git pull` on key repos
  - Disk space check
- Command history (per session)
- Copy/paste support

**Hardening** (P1 — required):
- Shell sessions run with least necessary privileges
- Reauthentication required for privileged operations
- Idle session timeouts (configurable, default 15 min)
- Destructive favorite commands require explicit confirmation
- PowerShell transcription for command-level audit (not just raw input)
- Credentials redacted from all audit records
- Every command logged with timestamp — viewable in Settings

**This is the keys to the kingdom.** See [Security](#security).

### 5. System Health

All telemetry from actual hardware readings. **No fabricated telemetry. Ever.**

- GPU temperature via NVML (with history sparkline)
- GPU utilization % via NVML
- GPU thermal throttling status (where supported)
- Fan status: `unknown` / `running` / `stopped` — **never interpret
  unavailable RPM telemetry as zero.** Our independently powered blower
  may not expose RPM to NVIDIA's management interface.
- CPU / RAM of host
- Disk space
- Uptime
- Every reading timestamped; `null` for unavailable values
- Telemetry failure distinguished from hardware failure
- Stale values never presented as live

**Alerts** (push-style in-app banners):
- GPU temp > 80°C (critical — temp monitoring is primary blower proxy)
- VRAM > 95%
- Hearth model Lost (unexpected)
- PIN disconnected > 60s
- GPU thermal throttling detected

**Note on blower monitoring:** Temperature monitoring cannot guarantee the
blower is operational. Independent fan sensing would provide stronger
protection if instrumentation becomes available.

---

## Architecture

```
┌─────────────────────────────────┐
│  iPhone (Safari)                │
│  Stoker PWA frontend            │
│  - Dashboard                    │
│  - Chat                         │
│  - Terminal (xterm.js)          │
└──────────────┬──────────────────┘
               │ HTTPS
               │ Cookie session (Secure, HttpOnly, SameSite)
               │ (Tailscale network only)
┌──────────────▼──────────────────┐
│  Stoker Backend (V100 box)      │
│  FastAPI + WebSocket            │
│                                 │
│  ┌──────────┐ ┌──────────────�┐  │
│  │ Hearth   │ │ Inference    │  │
│  │ Adapter  │ │ Proxy        │  │
│  └────┬─────┘ └──────┬───────┘  │
│       │              │          │
│  ┌────▼─────┐ ┌──────▼───────┐  │
│  │ PIN      │ │ Shell        │  │
│  │ Adapter  │ │ Service      │  │
│  └──────────┘ └──────────────┘  │
└──────────────┬──────────────────┘
               │
    ┌──────────┼──────────┐
    ▼          ▼          ▼
  Hearth   Inference  pin-clientd
  CLI      Endpoint
```

**Design principles:**
- Stoker is a thin orchestration layer. It wraps, proxies, and presents.
  It does not reimplement Hearth, inference, or PIN logic.
- Every adapter shells out to or queries the existing tool:
  - Hearth adapter → `hearth` CLI / Hearth API
  - Inference proxy → inference endpoint HTTP API
  - PIN adapter → pin-clientd status endpoint / logs
  - Shell service → native PTY on Windows
- If the underlying tool changes, only the adapter changes.
- Model → Residency → Runtime → Endpoint → Health. Never hardcoded
  to a specific model family or inference server.

---

## API Design

Base: `https://<tailscale-host>:<port>/api/v1`

### Authentication

Browser-native session auth (P0 fix):
- `POST /auth/login` with bearer token → sets `Secure`, `HttpOnly`,
  `SameSite=Strict` session cookie
- All subsequent requests (REST, SSE, WebSocket) use the cookie
- **Native `EventSource` and `WebSocket` cannot set `Authorization`
  headers** — cookie sessions are required for browser compatibility
- WebSocket validates `Origin` header + CSRF token
- Token rotation supported; sessions revocable from Settings
- **Never place auth tokens in URL query strings**

### Standard Envelopes

**Success (async operation):**
```json
{
  "operation_id": "op_abc123",
  "status": "accepted",
  "resource": "imagine-v11",
  "timestamp": "2026-10-10T23:00:00Z"
}
```

**Error:**
```json
{
  "error": {
    "code": "MODEL_LOAD_FAILED",
    "message": "VRAM insufficient: need 8.2GB, have 3.1GB",
    "operation_id": "op_abc123",
    "timestamp": "2026-10-10T23:00:05Z",
    "retryable": false
  }
}
```

**Rules:**
- Every response includes `timestamp`
- Every async operation returns `operation_id`
- Destructive actions accept `idempotency_key` to prevent duplicate
  execution on retry
- Automatic retries never duplicate destructive operations
- SSE events are typed: `{"event": "model.state", "data": {...}}`
- SSE clients handle reconnect with `Last-Event-ID`
- Stale state is explicitly marked with `stale: true` + last update time

### Hearth

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/hearth/models` | List all models with state + VRAM |
| POST | `/hearth/models/{id}/load` | Load a model (returns `operation_id`) |
| POST | `/hearth/models/{id}/unload` | Unload a model (returns `operation_id`) |
| GET | `/hearth/models/{id}/operations/{op}` | Poll operation status |
| GET | `/hearth/vram` | VRAM breakdown (NVML, timestamped) |
| GET | `/hearth/events` | SSE stream of typed state changes |

### Inference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/inference/chat` | Send prompt (SSE streaming, typed events) |
| POST | `/inference/chat/{id}/cancel` | Cancel in-flight generation |
| GET | `/inference/models` | List SERVING models (endpoint-ready) |
| GET | `/inference/sessions` | List conversation sessions |
| DELETE | `/inference/sessions/{id}` | Delete a session |

### PIN

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/pin/status` | Connection, trust, throughput, last update |
| GET | `/pin/routes` | Active routes |
| POST | `/pin/restart` | Restart pin-clientd (returns `operation_id`) |
| GET | `/pin/logs?tail=50` | Recent log lines |

### System

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/system/health` | GPU temp, util, throttling, fan state, CPU, RAM, disk |
| GET | `/system/health/stream` | SSE stream (1Hz, typed events) |
| GET | `/system/alerts` | Active alerts |

### Shell

| Method | Endpoint | Description |
|--------|----------|-------------|
| WS | `/shell/ws` | Websocket PTY session (cookie auth + CSRF) |
| GET | `/shell/favorites` | Saved commands |
| POST | `/shell/favorites` | Save a command |
| GET | `/shell/audit?limit=100` | Command audit log |

---

## UI/UX Design

### Design Language

- **Dark mode native.** This is a command deck, not a settings page.
- **Thumb-reachable.** Primary actions in the bottom third on mobile.
- **Dense but breathable.** Information-rich without clutter.
- **Motion with meaning.** Every animation reflects a real state change.
  Loading = progress. Success = confirmation. Error = attention.

### Screens

1. **Deck (home)** — GPU visualization, VRAM sectors, model states,
   system health sparklines, alert banners, last-updated timestamps.
   The "at a glance" screen.

2. **Models** — Full model list with operation states, VRAM per model,
   load/unload buttons, operation history with IDs.

3. **Chat** — Inference interface. Model picker at top (SERVING only),
   messages in the middle, input at the bottom. Streaming with
   typewriter effect. Explicit cancel button.

4. **PIN** — Network status, routes table, throughput graph, logs viewer,
   reconnect button.

5. **Terminal** — Full-screen xterm.js. Session tabs. Favorites drawer.
   Destructive commands show confirmation dialog.

6. **Settings** — Session management, Tailscale status, alert thresholds,
   favorites editor, audit log viewer, about.

### Mobile Reconnection (P2)

iOS suspends PWAs. Stoker handles this gracefully:
- Detect foreground/background transitions
- On foreground: reconcile with authoritative server state
- Display "Last confirmed: 2m ago" when data may be stale
- **Never automatically replay terminal commands**
- Interrupted inference streams show explicit "interrupted" state with
  option to retry (new `operation_id`, no duplicate side effects)

### Gamification Principles

- **Epic, not gimmicky.** The interface should feel powerful, not childish.
- **Every interaction has feedback.** Tap → acknowledge → progress → resolve.
- **State changes are cinematic.** Model loading follows the operation
  state machine visibly: DECLARED → LOADING → WARMING → RESIDENT → SERVING.
- **Haptics as progressive enhancement.** iOS Safari haptic support is
  limited — every important event must be fully understandable through
  visual and textual feedback alone. Haptics are a bonus, not a requirement.
- **No decoration without data.** If it moves, it means something.

### PWA

- Installable to iOS home screen (Add to Home Screen)
- Standalone display mode (no Safari chrome)
- App icon and splash screen
- Offline shell (shows last known state with timestamps, reconnects
  automatically)

---

## Security

**Threat model:** This dashboard provides full shell access to a GPU server.
Compromise = full machine compromise.

**Layers:**

1. **Tailscale only.** The backend binds to the Tailscale interface.
   It is not reachable from the public internet. No port forwarding.
   No dynamic DNS. If you're not on the tailnet, it doesn't exist.

2. **Cookie sessions.** Short-lived, server-managed sessions via
   `Secure`, `HttpOnly`, `SameSite=Strict` cookies. Initial login
   uses a high-entropy bearer token (generated on first run, displayed
   once, entry via manual input or QR code). Sessions support rotation
   and revocation. WebSocket connections validate Origin + CSRF token.

3. **No credentials in repo.** Tokens, Tailscale keys, and any secrets
   are runtime-only. The repo contains zero secrets.

4. **Shell audit log.** PowerShell transcription captures actual command
   execution (not just raw terminal input). Every entry timestamped.
   Credentials redacted. Viewable in Settings.

5. **Privilege separation.** Shell sessions run with least necessary
   privileges. Privileged operations require reauthentication.
   Idle sessions timeout (default 15 min).

6. **Rate limiting.** Auth endpoints are rate-limited. Failed auth
   attempts are logged.

7. **HTTPS.** Self-signed cert on Tailscale hostname, or Tailscale's
   built-in HTTPS. No plain HTTP.

**What we explicitly do NOT do:**
- Expose the dashboard to the public internet
- Place auth tokens in URL query strings
- Store tokens in browser localStorage without encryption
- Allow CORS from arbitrary origins
- Log prompt bodies in request or error logs
- Auto-replay terminal commands after reconnect
- Fabricate telemetry — unavailable values return `null`

---

## Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Backend | Python + FastAPI | Async-native, great websocket support |
| Frontend | Vanilla JS + xterm.js | No build step, fast, PWA-friendly |
| Terminal | xterm.js + pywinpty | Full PTY on Windows |
| Real-time | Server-Sent Events + WebSocket | SSE for typed state streams, WS for terminal |
| Auth | Cookie sessions (Secure/HttpOnly/SameSite) | Browser-compatible for SSE + WS |
| GPU telemetry | NVML (pynvml) | Actual hardware readings, dynamic discovery |
| Network | Tailscale | Zero-config VPN, no open ports |
| Deployment | Windows service / NSSM | Auto-start on boot, auto-restart |

**Python venv required** for all installs (project convention).

---

## Development Setup

```powershell
# On the V100 Windows box

# 1. Create and activate venv
py -m venv C:\stoker\venv
C:\stoker\venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure (copy and edit)
Copy-Item .env.example .env
notepad .env
# Set: STOKER_INIT_TOKEN, TAILSCALE_HOSTNAME, SESSION_SECRET

# 4. Ensure Tailscale is installed and authenticated
tailscale status

# 5. Get Tailscale IP for binding
$TS_IP = (tailscale ip -4).Trim()

# 6. Run (development)
uvicorn stoker.main:app --host $TS_IP --port 8443

# 7. For production, install as Windows service via NSSM
nssm install Stoker "C:\stoker\venv\Scripts\python.exe" `
  -m uvicorn stoker.main:app --host $TS_IP --port 8443
nssm set Stoker AppDirectory C:\stoker
nssm set Stoker Start SERVICE_AUTO_START
nssm start Stoker
```

Tailscale must be installed and authenticated on the box before first run.
The backend binds exclusively to the Tailscale interface IP.

---

## Roadmap & Release Gates

### v0.1 — Hearth + Inference
**Gate:** Secure access, Hearth integration, truthful GPU telemetry,
streaming inference.

- [ ] Backend skeleton (FastAPI, cookie auth, Tailscale binding)
- [ ] Hearth adapter (list, load, unload, VRAM via NVML, typed SSE events)
- [ ] Operation state machine (DECLARED → SERVING with operation IDs)
- [ ] Inference proxy (chat, streaming SSE, SERVING-only model picker)
- [ ] Deck screen (GPU viz, model states, health, timestamps)
- [ ] Chat screen (streaming, cancel, session management)
- [ ] PWA manifest + installable
- [ ] Standard error envelopes + idempotency keys

### v0.2 — PIN Integration
**Gate:** PIN integration, reconnect recovery, network alerts.

- [ ] PIN adapter (status, routes, throughput, logs)
- [ ] PIN screen
- [ ] Alert system (in-app banners)
- [ ] Mobile reconnection handling (foreground/background, state reconciliation)

### v0.3 — Shell / Terminal
**Gate:** Audited terminal, privilege restrictions, session security.

- [ ] Websocket PTY service (pywinpty, cookie + CSRF auth)
- [ ] Terminal screen (xterm.js, tabs, favorites)
- [ ] PowerShell transcription audit log
- [ ] Least-privilege sessions, reauth for privileged ops, idle timeouts
- [ ] Destructive command confirmation dialogs
- [ ] Command favorites CRUD

### v0.4 — Epic UI Pass
**Gate:** Cinematic UI, accessible feedback, visual polish.

- [ ] Cinematic model load sequences (operation state machine visualized)
- [ ] Haptic feedback (progressive enhancement)
- [ ] GPU visualization upgrade
- [ ] Polish pass on all screens
- [ ] App icon + splash screen

### Future
- [ ] Voice input for chat (iOS dictation)
- [ ] Widgets (iOS home screen VRAM widget?)
- [ ] Multi-node support (if a second GPU joins)

---

## Changelog

### v0.1.1 (2026-10-10)
Oracle architecture review — all patch notes applied:
- **P0-1:** Cookie sessions replace bearer tokens for browser compat
  (EventSource/WebSocket cannot set Authorization headers)
- **P0-2:** Fan telemetry tristate (unknown/running/stopped); never
  treat unavailable RPM as zero; thermal throttling telemetry added
- **P0-3:** Explicit operation state machine with operation IDs;
  residency distinguished from inference readiness
- **P0-4:** Standardized API contracts — error envelopes, idempotency
  keys, typed SSE events, timestamps, stale-state indicators
- **P1-5:** Terminal hardening — least privilege, reauth, idle timeouts,
  destructive confirmations, PowerShell transcription, credential redaction
- **P1-6:** NVML-based telemetry contracts — dynamic discovery,
  timestamps, null for unavailable, no fabricated data
- **P1-7:** Conversation storage policy separated from operational logging
- **P2-8:** Haptics as progressive enhancement (Safari limitations)
- **P2-9:** Mobile reconnection behavior specified
- **P2-10:** PowerShell-native installation examples
- Architecture made model-agnostic: Model → Residency → Runtime →
  Endpoint → Health

### v0.1.0 (2026-10-10)
Initial comprehensive spec.

---

## License

TBD
