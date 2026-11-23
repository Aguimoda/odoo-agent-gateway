const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

/** The modifier key shown in shortcuts: ⌘ on Apple devices, Ctrl elsewhere. */
export const modKey = isMac ? "⌘" : "Ctrl";
