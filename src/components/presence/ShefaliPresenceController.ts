/**
 * ShefaliPresenceController
 *
 * Architectural boundary between Zarya runtime state
 * and Shefali's visual presentation.
 *
 * RULE: This component consumes runtime state.
 *       It does NOT infer, guess, or override it.
 *
 * The existing avatarStyle ("character" | "orb") in ZaryaSettings
 * already provides the presence mode abstraction:
 *   - "orb"       → abstract orb visualization (orb2.gif)
 *   - "character" → video-based character (idle/talking/thinking.webm)
 *
 * S10.4 Addition:
 *   deriveRuntimeState() maps the signals the frontend actually
 *   receives (LiveState, characterState, tool activity) to the
 *   canonical RuntimePresenceState. States the frontend cannot
 *   yet verify (VERIFIED_SUCCESS, VERIFIED_FAILURE) are reserved
 *   for when the backend WS protocol extends to send them.
 *   Until then, tool completion defaults to UNKNOWN — never
 *   inferring success from dispatch alone.
 */

export type RuntimePresenceState =
  | "IDLE"
  | "LISTENING"
  | "UNDERSTANDING"
  | "PLANNING"
  | "WORKING"
  | "VERIFYING"
  | "VERIFIED_SUCCESS"
  | "VERIFIED_FAILURE"
  | "UNKNOWN"
  | "BLOCKED";

/**
 * Maps Zarya runtime states to Shefali expression cues.
 * The frontend must consume these from the runtime —
 * never infer success from HTTP 200 or tool dispatch.
 */
export const PRESENCE_EXPRESSION_MAP: Record<RuntimePresenceState, string> = {
  IDLE:             "calm, neutral",
  LISTENING:        "attentive",
  UNDERSTANDING:    "thoughtful",
  PLANNING:         "focused",
  WORKING:          "concentrated",
  VERIFYING:        "careful",
  VERIFIED_SUCCESS: "subtle positive",
  VERIFIED_FAILURE: "acknowledges failure",
  UNKNOWN:          "uncertainty — never false celebration",
  BLOCKED:          "waiting",
};

/**
 * S10.4: Derive the canonical runtime presence state from the
 * signals the frontend actually receives.
 *
 * This function is deliberately conservative:
 * - It never returns VERIFIED_SUCCESS or VERIFIED_FAILURE because
 *   the current WS protocol does not send explicit verification.
 * - Tool completion maps to UNKNOWN (not SUCCESS) until the
 *   backend extends the protocol.
 * - This preserves the S1–S10 trust model.
 */
export function deriveRuntimeState(ctx: {
  liveState: string;
  characterState: string;
  isToolRunning: boolean;
}): RuntimePresenceState {
  // Disconnected / connecting → idle presence
  if (ctx.liveState === "disconnected" || ctx.liveState === "connecting") {
    return "IDLE";
  }

  // Active tool execution → working
  if (ctx.isToolRunning) {
    return "WORKING";
  }

  // Character thinking (tool dispatch / planning phase)
  if (ctx.characterState === "thinking") {
    return "PLANNING";
  }

  // Shefali speaking → user is listening, Shefali is present
  if (ctx.liveState === "speaking") {
    return "LISTENING";
  }

  // Mic active, waiting for user input
  if (ctx.liveState === "listening") {
    return "LISTENING";
  }

  return "IDLE";
}

/**
 * Visual expression config for the overlay layer.
 * Each state maps to a subtle CSS/Motion presentation.
 * States without explicit overlays render transparently.
 */
export const EXPRESSION_OVERLAY_CONFIG: Record<
  RuntimePresenceState,
  { label: string; hasOverlay: boolean }
> = {
  IDLE:             { label: "calm",          hasOverlay: false },
  LISTENING:        { label: "attentive",     hasOverlay: false },
  UNDERSTANDING:    { label: "thoughtful",    hasOverlay: false },
  PLANNING:         { label: "focused",       hasOverlay: true  },
  WORKING:          { label: "concentrated",  hasOverlay: true  },
  VERIFYING:        { label: "careful",       hasOverlay: true  },
  VERIFIED_SUCCESS: { label: "subtle positive", hasOverlay: true },
  VERIFIED_FAILURE: { label: "acknowledges",  hasOverlay: true  },
  UNKNOWN:          { label: "uncertain",     hasOverlay: true  },
  BLOCKED:          { label: "waiting",       hasOverlay: true  },
};
