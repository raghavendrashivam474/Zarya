/**
 * ShefaliPresenceController
 *
 * Architectural boundary between Zarya runtime state
 * and Shefali's visual presentation.
 *
 * GOLDEN RULE:
 *   Zarya knows. The event bridge exposes. Shefali presents.
 *   This controller consumes runtime state. It does NOT infer, guess, or override it.
 *
 * S11 Refinements:
 *   - Sub-step progress presentation (step index, tool, verification status)
 *   - Humanized UNKNOWN handling with epistemic honesty (no false success/failure)
 *   - Calibrated visual timing for voice/visual synchronization
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
 * Human-facing descriptions for Shefali's status badge.
 * Deliberately honest: UNKNOWN is never coerced into success or failure.
 */
export const PRESENCE_HUMAN_LABELS: Record<RuntimePresenceState, string> = {
  IDLE:             "Ready",
  LISTENING:        "Listening…",
  UNDERSTANDING:    "Thinking…",
  PLANNING:         "Formulating plan…",
  WORKING:          "Working on it…",
  VERIFYING:        "Checking results…",
  VERIFIED_SUCCESS: "Done — verified",
  VERIFIED_FAILURE: "Encountered an issue",
  UNKNOWN:          "Could not verify outcome",
  BLOCKED:          "Awaiting confirmation",
};

/**
 * Maps Zarya runtime states to Shefali expression cues.
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

export interface ExpressionOverlayConfig {
  label: string;
  badgeBg: string;
  badgeBorder: string;
  badgeText: string;
  ringColor: string;
  auraIntensity: number;
}

export const EXPRESSION_OVERLAY_CONFIG: Record<RuntimePresenceState, ExpressionOverlayConfig> = {
  IDLE: {
    label: "Ready",
    badgeBg: "rgba(255, 255, 255, 0.05)",
    badgeBorder: "rgba(255, 255, 255, 0.15)",
    badgeText: "#94a3b8",
    ringColor: "rgba(148, 163, 184, 0.2)",
    auraIntensity: 0.15,
  },
  LISTENING: {
    label: "Listening",
    badgeBg: "rgba(147, 51, 234, 0.15)",
    badgeBorder: "rgba(147, 51, 234, 0.4)",
    badgeText: "#c084fc",
    ringColor: "rgba(168, 85, 247, 0.4)",
    auraIntensity: 0.45,
  },
  UNDERSTANDING: {
    label: "Understanding",
    badgeBg: "rgba(59, 130, 246, 0.15)",
    badgeBorder: "rgba(59, 130, 246, 0.4)",
    badgeText: "#60a5fa",
    ringColor: "rgba(96, 165, 250, 0.4)",
    auraIntensity: 0.4,
  },
  PLANNING: {
    label: "Planning",
    badgeBg: "rgba(99, 102, 241, 0.15)",
    badgeBorder: "rgba(99, 102, 241, 0.4)",
    badgeText: "#818cf8",
    ringColor: "rgba(129, 140, 248, 0.4)",
    auraIntensity: 0.4,
  },
  WORKING: {
    label: "Executing",
    badgeBg: "rgba(245, 158, 11, 0.15)",
    badgeBorder: "rgba(245, 158, 11, 0.4)",
    badgeText: "#fbbf24",
    ringColor: "rgba(251, 191, 36, 0.4)",
    auraIntensity: 0.5,
  },
  VERIFYING: {
    label: "Verifying",
    badgeBg: "rgba(20, 184, 166, 0.15)",
    badgeBorder: "rgba(20, 184, 166, 0.4)",
    badgeText: "#2dd4bf",
    ringColor: "rgba(45, 212, 191, 0.4)",
    auraIntensity: 0.45,
  },
  VERIFIED_SUCCESS: {
    label: "Verified \u2713",
    badgeBg: "rgba(16, 185, 129, 0.15)",
    badgeBorder: "rgba(16, 185, 129, 0.4)",
    badgeText: "#34d399",
    ringColor: "rgba(52, 211, 153, 0.45)",
    auraIntensity: 0.5,
  },
  VERIFIED_FAILURE: {
    label: "Failed \u2717",
    badgeBg: "rgba(239, 68, 68, 0.15)",
    badgeBorder: "rgba(239, 68, 68, 0.4)",
    badgeText: "#f87171",
    ringColor: "rgba(248, 113, 113, 0.45)",
    auraIntensity: 0.4,
  },
  UNKNOWN: {
    label: "Unverified \u2014 Checking",
    badgeBg: "rgba(245, 158, 11, 0.15)",
    badgeBorder: "rgba(245, 158, 11, 0.4)",
    badgeText: "#fbbf24",
    ringColor: "rgba(251, 191, 36, 0.35)",
    auraIntensity: 0.3,
  },
  BLOCKED: {
    label: "Blocked",
    badgeBg: "rgba(244, 63, 94, 0.15)",
    badgeBorder: "rgba(244, 63, 94, 0.4)",
    badgeText: "#fb7185",
    ringColor: "rgba(251, 113, 133, 0.4)",
    auraIntensity: 0.35,
  },
};

/**
 * Information describing an in-flight or completed step.
 */
export interface StepProgressInfo {
  stepId: string;
  stepIndex: number;
  totalSteps: number;
  tool: string;
  state: RuntimePresenceState;
  detail?: string;
}

/**
 * Humanize a step event into a clean, legible subtitle for the UI.
 */
export function formatStepProgressText(
  event: string,
  state: RuntimePresenceState,
  tool: string,
  payload?: Record<string, unknown>
): string {
  const stepIdx = typeof payload?.step_index === "number" ? payload.step_index + 1 : undefined;
  const total = typeof payload?.total_steps === "number" ? payload.total_steps : undefined;
  const stepPrefix = (stepIdx !== undefined && total !== undefined)
    ? "Step " + stepIdx + "/" + total
    : "Working";

  if (event === "work_step_started") {
    return stepPrefix + ": Running " + (tool || "tool") + "\u2026";
  }

  if (event === "work_step_completed") {
    if (state === "VERIFIED_SUCCESS") {
      return stepPrefix + ": Verified successfully";
    }
    if (state === "VERIFIED_FAILURE") {
      const detail = typeof payload?.detail === "string" ? payload.detail : "Step failed verification";
      return stepPrefix + ": Failed \u2014 " + detail;
    }
    if (state === "UNKNOWN") {
      return stepPrefix + ": Finished \u2014 outcome unverified";
    }
  }

  if (event === "work_completed") {
    if (state === "VERIFIED_SUCCESS") return "Workflow completed and verified";
    if (state === "VERIFIED_FAILURE") return "Workflow halted on failure";
    if (state === "UNKNOWN") return "Workflow finished with unverified steps";
  }

  return PRESENCE_HUMAN_LABELS[state] || "Working\u2026";
}

/**
 * Conservative derivation for non-event signals (e.g. idle vs listening).
 */
export function deriveRuntimeState(
  liveState: "disconnected" | "connecting" | "listening" | "speaking",
  characterState: "idle" | "talking" | "thinking",
  activeTool?: string | null
): RuntimePresenceState {
  if (activeTool) return "WORKING";
  if (characterState === "thinking") return "UNDERSTANDING";
  if (liveState === "listening") return "LISTENING";
  if (liveState === "speaking") return "WORKING";
  return "IDLE";
}
