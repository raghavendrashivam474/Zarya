# Shefali Visual Identity Specification

## 1. Identity Role & System Boundary
- **System:** Zarya (computer-work engine, tool planner, verification fabric)
- **Persona:** Shefali (human-facing companion, conversational voice, presence)
- **Authority Rule:** Zarya executes and verifies. Shefali expresses and communicates.
- **Trust Guarantee:** Shefali never indicates success without verified execution. `UNKNOWN` and `VERIFIED_FAILURE` states are presented conservatively and honestly.

## 2. Character Appearance Baseline
- **Name:** Shefali
- **Aesthetic:** High-fidelity, calm, modern, photorealistic digital human.
- **Face & Demeanor:** Friendly yet focused, intelligent, approachable.
- **Hair & Style:** Professional, dark shoulder-length styling with clean ambient rim lighting.
- **Color Temperature:** Cool indigo / cyan ambient baseline; accents align with active Zarya system theme (violet, emerald, celestial, gold, rose, crimson).
- **Expression Baseline:** Attentive neutrality when listening; focused concentration when planning/working; gentle acknowledgment upon verified completion.

## 3. Current Presence Modes
1. **Orb Mode (`avatarStyle: "orb"`):**
   - Abstract energetic orb visualization (`public/assets/orb2.gif` and dynamic canvas)
   - Dynamic glow response based on listening, thinking, and speaking states.

2. **Character Mode (`avatarStyle: "character"`):**
   - Video-based digital human state machine:
     - `public/assets/idle.webm` — Neutral breathing & presence loop
     - `public/assets/talking.webm` — Natural speaking animation loop
     - `public/assets/thinking.webm` — Attentive cognitive processing loop
   - **S10.4 Runtime Expression Overlay (Layer z-20):**
     - Transparent motion overlay mapped to Zarya's verified runtime states (`PLANNING`, `WORKING`, `VERIFYING`, `VERIFIED_SUCCESS`, `VERIFIED_FAILURE`, `UNKNOWN`, `BLOCKED`).

## 4. State & Expression Mapping

| Runtime State | Shefali Expression | Overlay Visual Cue | Epistemic Rule |
| :--- | :--- | :--- | :--- |
| `IDLE` | Calm, neutral presence | Transparent / baseline particles | Ambient standby |
| `LISTENING` | Attentive | Responsive audio waveform glow | Mic receiving input |
| `UNDERSTANDING`| Thoughtful | Audio analysis reaction | Processing user input |
| `PLANNING` | Focused | Subtle indigo cranial aura pulse | Tool dispatch preparation |
| `WORKING` | Concentrated | Ambient violet activity aura | Tool execution active |
| `VERIFYING` | Careful observation | Focused cyan boundary circle | Verification in progress |
| `VERIFIED_SUCCESS` | Subtle positive response | Warm emerald ambient backdrop glow | **Only** on verified outcome |
| `VERIFIED_FAILURE` | Acknowledges error | Cool red tint + desaturation | **Never** celebrates on error |
| `UNKNOWN` | Uncertain, waiting | Subtle amber caution pulse | **Never** false positive |
| `BLOCKED` | Restrained | Muted slate veil | Awaiting user unblock |
