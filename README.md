# Stoker

**Mobile command center for V100 + Hearth + PIN.**

Stoker is the one who tends the fire. This is the mobile face for Mark's V100
node — full command and control of Hearth model residency, PIN networking, and
the GPU itself, from an iPhone.

Utility first, epic coating. Powerful underneath, delightful on top.

## Vision

Open Safari on iOS. You see your V100 — live VRAM, temperature, compute load.
Tap a model to load it. Send it a prompt. Check PIN routing. Open a shell.
All from your phone, from anywhere.

No App Store. No TestFlight. One secured URL.

## Core Features

### Hearth — Model Residency
- Live model states: Unknown / Loading / Resident / Lost / Failed / Stopped
- Load / unload models with one tap (dual-uses Hearth's existing commands)
- VRAM usage per model, total, and headroom
- Cinematic load sequences — progress, then confirmation when resident

### Inference
- Chat interface to any resident model
- Streaming responses
- Model picker tied to Hearth residency state

### PIN — Network
- Node connection status and health
- What's routing through, live
- Operator trust state

### Shell — Command & Control
- Full terminal (xterm.js over websocket) to the V100 box
- Run anything: nvidia-smi, service restarts, git pulls, training launches
- Command history and favorites for common ops

### Gamified, Utility-First UI
- Big tactile buttons for common actions
- Satisfying visual feedback on every outcome
- Interface changes reflect real state — no decoration without data
- Haptic-friendly, thumb-reachable, dark mode native

## Architecture

```
iPhone (Safari)
    │  HTTPS + token auth, Tailscale
    ▼
Stoker backend (on V100 Windows box)
    ├── Hearth adapter  → wraps hearth CLI / protocol
    ├── Inference proxy → llama-server / model endpoint
    ├── PIN adapter     → pin-clientd status
    └── Shell service   → websocket PTY (PowerShell)
```

- Backend: Python (FastAPI) or Node — TBD
- Frontend: mobile-first web, xterm.js for terminal
- Auth: bearer token + Tailscale (never exposed to public internet)
- Hearth commands are dual-used, not reimplemented

## Security

- Tailscale-only access. The dashboard is not on the public internet.
- Token auth on every request.
- Shell access is the keys to the kingdom — treat it accordingly.
- No credentials in the repo. Ever.

## Roadmap

1. **v0.1** — Hearth status + model load/unload + inference chat
2. **v0.2** — PIN status panel
3. **v0.3** — Shell / terminal
4. **v0.4** — Gamified UI pass (animations, haptics, epic coating)

## License

TBD
