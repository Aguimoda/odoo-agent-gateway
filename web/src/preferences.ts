// Per-browser conveniences only (theme, language, sidebar). Never credentials.
// Storage can be missing or blocked; the app works without it.

const PREFIX = "oag.";

export function readPreference(name: string): string | null {
  try {
    return window.localStorage.getItem(PREFIX + name);
  } catch {
    return null;
  }
}

export function writePreference(name: string, value: string): void {
  try {
    window.localStorage.setItem(PREFIX + name, value);
  } catch {
    // ignore: preferences are a convenience
  }
}
