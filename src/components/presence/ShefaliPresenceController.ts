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
 * Future presence levels plug into this boundary without
 * changing Zarya runtime contracts.
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