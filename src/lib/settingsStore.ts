/**
 * Zarya Settings Store — persistent user preferences (V2).
 *
 * Establishes the persistence pattern for Zarya: settings are mirrored to
 * localStorage (instant local read) AND synced to the backend (settings.json)
 * so auto-start / wake-word preferences survive across browsers and the
 * Python desktop agent can read them too.
 *
 * Pattern follows the existing codebase conventions: plain state + ref mirrors.
 * No Context/Zustand — this is deliberately lightweight to match audio.ts/memoryTypes.ts.
 */

export interface ZaryaSettings {
  /** Launch Zarya (backends + browser tab) silently on Windows login. */
  autoStart: boolean;

  /** Enable the always-listening wake-word detector. */
  wakeWordEnabled: boolean;

  /** Phrase that activates Shefali (case-insensitive substring match). */
  wakePhrase: string;

  /** Wake-word sensitivity: 0 (strict) .. 100 (loose). Affects debounce window. */
  sensitivity: number;

  /** Preferred microphone device ID (empty string = system default). */
  micDeviceId: string;

  /** Gemini Live voice name ("Puck" | "Charon" | "Kore" | "Fenrir" | "Aoede"). */
  voice: string;

  /** Background style ("solid" | "video_1" | "video_2"). */
  backgroundVideo: string;

  /** Avatar style ("character" | "orb"). */
  avatarStyle: "character" | "orb";

  /** Enable futuristic holographic interface glow & scanlines. */
  holographicGlow: boolean;

  /** Ambient audio visualizer responsiveness speed (1-10). */
  visualizerSpeed: number;

  /** Master UI audio volume multiplier (0.0 to 1.0). */
  masterVolume: number;

  /** Enable high-framerate ambient particle and orb rendering. */
  animations: boolean;
}

export const GEMINI_VOICES = [
  { id: "Puck", label: "Puck", desc: "Playful / Fast" },
  { id: "Charon", label: "Charon", desc: "Deep / Resonant (Default)" },
  { id: "Kore", label: "Kore", desc: "Warm / Soothing" },
  { id: "Fenrir", label: "Fenrir", desc: "Intense / Direct" },
  { id: "Aoede", label: "Aoede", desc: "Melodic / Clear" },
] as const;

/** Sane fallback defaults if no settings have ever been persisted. */
export const DEFAULT_SETTINGS: ZaryaSettings = {
  autoStart: false,
  wakeWordEnabled: false,
  wakePhrase: "hey shefali",
  sensitivity: 50,
  micDeviceId: "",
  voice: "Charon",
  backgroundVideo: "solid",
  avatarStyle: "orb",
  holographicGlow: true,
  visualizerSpeed: 5,
  masterVolume: 1.0,
  animations: true,
};

const STORAGE_KEY = "zarya.settings.v1";
const LEGACY_STORAGE_KEY = "elysia.settings.v2";

/** Settings keys that the browser should never persist (security). */
const NEVER_PERSIST: ReadonlySet<keyof ZaryaSettings> = new Set([]);

/**
 * Load settings from localStorage, merged over defaults so new keys always
 * have a sane value even when an older payload is present.
 */
export function loadSettings(): ZaryaSettings {
  if (typeof window === "undefined") return { ...DEFAULT_SETTINGS };
  try {
    let raw = window.localStorage.getItem(STORAGE_KEY);
    // Backward-compatible migration from legacy storage key
    if (!raw) {
      const legacy = window.localStorage.getItem(LEGACY_STORAGE_KEY);
      if (legacy) {
        raw = legacy;
        try {
          window.localStorage.setItem(STORAGE_KEY, legacy);
        } catch {
          // localStorage write failure is non-fatal
        }
      }
    }
    if (!raw) return { ...DEFAULT_SETTINGS };
    const parsed = JSON.parse(raw) as Partial<ZaryaSettings>;
    return { ...DEFAULT_SETTINGS, ...parsed };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

/**
 * Persist a full or partial settings update to localStorage.
 * Returns the fully merged settings object.
 */
export function saveSettings(patch: Partial<ZaryaSettings>): ZaryaSettings {
  const current = loadSettings();
  const next: ZaryaSettings = { ...current, ...patch };

  if (typeof window !== "undefined") {
    try {
      // Strip any sensitive keys before writing to localStorage.
      const safe: Record<string, unknown> = {};
      (Object.keys(next) as (keyof ZaryaSettings)[]).forEach((k) => {
        if (!NEVER_PERSIST.has(k)) safe[k] = next[k];
      });
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(safe));
    } catch {
      /* localStorage may be unavailable (private mode) — fail silently. */
    }
  }

  // Best-effort sync to backend so the Python agent can read auto-start state.
  void syncSettingsToBackend(next).catch(() => {});

  return next;
}

/** Push settings to the backend (server.ts persists to settings.json). */
async function syncSettingsToBackend(settings: ZaryaSettings): Promise<void> {
  try {
    await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    });
  } catch {
    /* Backend may be briefly unavailable during boot — non-fatal. */
  }
}