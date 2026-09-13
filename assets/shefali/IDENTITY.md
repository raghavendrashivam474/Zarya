# Shefali Visual Identity Specification

## Identity Role & Relationship
- **System:** Zarya (computer-work engine, tool planner, verification fabric)
- **Persona:** Shefali (human-facing companion, conversational voice, presence)
- **Authority Rule:** Zarya executes and verifies. Shefali expresses and communicates.

## Current Presence Modes
1. **Orb Mode (`avatarStyle: "orb"`):**
   - Abstract energetic orb visualization (`public/assets/orb2.gif` and dynamic SVG canvas)
   - Dynamic glow response based on listening, thinking, and speaking states.

2. **Character Mode (`avatarStyle: "character"`):**
   - Video-based presence loop using pre-rendered digital human clips:
     - `public/assets/idle.webm` — Neutral breathing loop
     - `public/assets/talking.webm` — Active speech loop
     - `public/assets/thinking.webm` — Cognitive processing loop

## Visual Direction for Future Enhancements
- **Aesthetic:** Realistic digital human, calm, approachable, intelligent
- **Expression baseline:** Attentive neutrality, subtle reactions to verified runtime outcomes
- **Epistemic boundary:** Never exhibit false celebration or success animations on `UNKNOWN` or `FAILURE` states.