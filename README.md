# Stoker

**Mobile command center for V100 + Hearth + PIN.**

Stoker is the one who tends the fire. This is the mobile face for a V100 GPU
node running Hearth model residency on the PIN p2p inference network — full
command and control from an iPhone.

**Philosophy:** Utility first, epic coating. Every pixel serves a purpose.
Every interaction is satisfying. Powerful underneath, delightful on top.

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
9. [Roadmap](#roadmap)
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

---

## Core Features

### 1. Hearth — Model Residency

Hearth is the deterministic model residency protocol. Stoker dual-uses
Hearth's existing commands — it does not reimplement residency logic.

**States** (from Hearth protocol):
- `Unknown` — model declared but state not yet determined
- `Loading` — weights streaming into VRAM
- `Resident` — warm and serving
- `Lost` — evicted, GPU detached, or otherwise gone (with reason)
- `Failed` — load failed (with error)
- `Stopped` — intentionally unloaded

**Actions:**
- List all declared models with current state
- Load a model (triggers Hearth load, shows cinematic progress)
- Unload / evict a model (frees VRAM)
- View per-model VRAM footprint
- View load history and failure reasons

**VRAM Dashboard:**
- Total VRAM (32GB on V100)
- Used / free with per-model breakdown
- Visual sectors — each model's share as a glowing segment
- Warning threshold at 85%, critical at 95%

### 2. Inference

Chat interface to any `Resident` model.

**Features:**
- Model picker (only shows Resident models)
- Streaming token output
- Conversation history (per session, stored server-side)
- System prompt configuration per model
- Temperature / top-p / max-tokens controls (collapsible advanced panel)
- Stop generation button
- Copy / share response

**Backend:** Proxies to llama-server (or equivalent inference endpoint)
running on the V100 box. Stoker does not run inference itself.

### 3. PIN — Network Status

**Displays:**
- Node connection state (connected / connecting / disconnected)
- Operator identity and trust level
- Active routes — what's being served right now
- Request throughput (requests/min, tokens/sec)
- Uptime and last heartbeat

**Actions:**
- Reconnect / restart pin-clientd
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

**This is the keys to the kingdom.** See [Security](#security).

### 5. System Health

- GPU temperature (with history sparkline)
- GPU utilization %
- Fan speed (the V100 blower — critical, must stay powered)
- CPU / RAM of host
- Disk space
- Uptime

**Alerts** (push-style in-app banners):
- GPU temp > 80°C
- VRAM > 95%
- Hearth model Lost (unexpected)
- PIN disconnected > 60s
- Blower fan RPM = 0 (critical — V100 thermal risk)

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
               │ HTTPS + Bearer Token
               │ (Tailscale network only)
┌──────────────▼──────────────────┐
│  Stoker Backend (V100 box)      │
│  FastAPI + WebSocket            │
│                                 │
│  ┌──────────┐ ┌──────────────┐  │
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
  Hearth    llama-    pin-clientd
  CLI       server
```

**Design principles:**
- Stoker is a thin orchestration layer. It wraps, proxies, and presents.
  It does not reimplement Hearth, inference, or PIN logic.
- Every adapter shells out to or queries the existing tool:
  - Hearth adapter → `hearth` CLI / Hearth API
  - Inference proxy → llama-server HTTP API
  - PIN adapter → pin-clientd status endpoint / logs
  - Shell service → native PTY on Windows
- If the underlying tool changes, only the adapter changes.

---

## API Design

Base: `https://<tailscale-host>:<port>/api/v1`

All endpoints require `Authorization: Bearer <token>`.

### Hearth

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/hearth/models` | List all models with state + VRAM |
| POST | `/hearth/models/{id}/load` | Load a model |
| POST | `/hearth/models/{id}/unload` | Unload a model |
| GET | `/hearth/vram` | VRAM breakdown |
| GET | `/hearth/events` | SSE stream of state changes |

### Inference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/inference/chat` | Send prompt (SSE streaming response) |
| GET | `/inference/models` | List servable (Resident) models |
| DELETE | `/inference/sessions/{id}` | Clear conversation |

### PIN

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/pin/status` | Connection, trust, throughput |
| GET | `/pin/routes` | Active routes |
| POST | `/pin/restart` | Restart pin-clientd |
| GET | `/pin/logs?tail=50` | Recent log lines |

### System

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/system/health` | GPU temp, util, fan, CPU, RAM, disk |
| GET | `/system/health/stream` | SSE stream (1Hz updates) |
| GET | `/system/alerts` | Active alerts |

### Shell

| Method | Endpoint | Description |
|--------|----------|-------------|
| WS | `/shell/ws` | Websocket PTY session |
| GET | `/shell/favorites` | Saved commands |
| POST | `/shell/favorites` | Save a command |

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
   system health sparklines, alert banners. The "at a glance" screen.

2. **Models** — Full model list with states, VRAM per model,
   load/unload buttons, load history.

3. **Chat** — Inference interface. Model picker at top, messages in the
   middle, input at the bottom. Streaming with typewriter effect.

4. **PIN** — Network status, routes table, throughput graph, logs viewer.

5. **Terminal** — Full-screen xterm.js. Session tabs. Favorites drawer.

6. **Settings** — Token management, Tailscale status, alert thresholds,
   favorites editor, about.

### Gamification Principles

- **Epic, not gimmicky.** The interface should feel powerful, not childish.
- **Every interaction has feedback.** Tap → acknowledge → progress → resolve.
- **State changes are cinematic.** Model loading isn't a spinner — it's a
  sequence: declared → streaming weights → warming up → resident.
- **Haptics.** Use iOS haptic feedback on key actions (load complete,
  alert triggered, command executed).
- **No decoration without data.** If it moves, it means something.

### PWA

- Installable to iOS home screen (Add to Home Screen)
- Standalone display mode (no Safari chrome)
- App icon and splash screen
- Offline shell (shows last known state, reconnects automatically)

---

## Security

**Threat model:** This dashboard provides full shell access to a GPU server.
Compromise = full machine compromise.

**Layers:**

1. **Tailscale only.** The backend binds to the Tailscale interface.
   It is not reachable from the public internet. No port forwarding.
   No dynamic DNS. If you're not on the tailnet, it doesn't exist.

2. **Bearer token.** Every API request and websocket connection requires
   a high-entropy token. Token is generated on first run, displayed once,
   stored in iOS (manual entry or QR code).

3. **No credentials in repo.** Tokens, Tailscale keys, and any secrets
   are runtime-only. The repo contains zero secrets.

4. **Shell audit log.** Every command run through the terminal is logged
   with timestamp. Log is viewable in Settings.

5. **Rate limiting.** Auth endpoints are rate-limited. Failed auth
   attempts are logged.

6. **HTTPS.** Self-signed cert on Tailscale hostname, or Tailscale's
   built-in HTTPS. No plain HTTP.

**What we explicitly do NOT do:**
- Expose the dashboard to the public internet
- Store tokens in browser localStorage without encryption
- Allow CORS from arbitrary origins
- Log prompt contents server-side (only metadata)

---

## Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Backend | Python + FastAPI | Async-native, great websocket support, Mark's ecosystem |
| Frontend | Vanilla JS + xterm.js | No build step, fast, PWA-friendly |
| Terminal | xterm.js + pywinpty | Full PTY on Windows |
| Real-time | Server-Sent Events + WebSocket | SSE for state streams, WS for terminal |
| Auth | Bearer token | Simple, sufficient behind Tailscale |
| Network | Tailscale | Zero-config VPN, no open ports |
| Deployment | Windows service / NSSM | Auto-start on boot, auto-restart |

**Python venv required** for all installs (project convention).

---

## Development Setup

```powershell
# On the V100 Windows box
py -m venv C:\stoker\venv
C:\stoker\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Configure
copy .env.example .env
# Edit .env: set STOKER_TOKEN, TAILSCALE_HOSTNAME

# Run
uvicorn stoker.main:app --host 100.x.x.x --port 8443 --ssl-keyfile ... --ssl-certfile ...
```

Tailscale must be installed and authenticated on the box before first run.

---

## Roadmap

### v0.1 — Hearth + Inference (MVP)
- [ ] Backend skeleton (FastAPI, auth, Tailscale binding)
- [ ] Hearth adapter (list, load, unload, VRAM, SSE events)
- [ ] Inference proxy (chat, streaming, model picker)
- [ ] Deck screen (GPU viz, model states, health)
- [ ] Chat screen
- [ ] PWA manifest + installable

### v0.2 — PIN Integration
- [ ] PIN adapter (status, routes, throughput, logs)
- [ ] PIN screen
- [ ] Alert system (in-app banners)

### v0.3 — Shell / Terminal
- [ ] Websocket PTY service (pywinpty)
- [ ] Terminal screen (xterm.js, tabs, favorites)
- [ ] Shell audit log
- [ ] Command favorites CRUD

### v0.4 — Epic UI Pass
- [ ] Cinematic model load sequences
- [ ] Haptic feedback integration
- [ ] GPU 3D visualization upgrade
- [ ] Polish pass on all screens
- [ ] App icon + splash screen

### Future
- [ ] Voice input for chat (iOS dictation)
- [ ] Widgets (iOS home screen VRAM widget?)
- [ ] Multi-node support (if a second GPU joins)

---

## License

TBD
