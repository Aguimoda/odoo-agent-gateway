import { useEffect, useRef } from "react";

import { useI18n, type MessageKey } from "../i18n";
import { modKey } from "./keys";

const SHORTCUTS: [MessageKey, string[]][] = [
  ["shortcuts.send", ["Enter"]],
  ["shortcuts.newline", ["Shift", "Enter"]],
  ["shortcuts.stop", ["Esc"]],
  ["shortcuts.newChat", [modKey, "Shift", "O"]],
  ["shortcuts.sidebar", [modKey, "B"]],
  ["shortcuts.focus", ["/"]],
  ["shortcuts.help", ["?"]],
];

export function ShortcutsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n();
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal?.();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className="dialog"
      aria-labelledby="shortcuts-title"
      onClose={onClose}
      onClick={(event) => event.target === ref.current && onClose()}
    >
      <div className="dialog-body">
        <h2 id="shortcuts-title">{t("shortcuts.title")}</h2>
        <table className="table">
          <tbody>
            {SHORTCUTS.map(([key, keys]) => (
              <tr key={key}>
                <td>{t(key)}</td>
                <td className="num">
                  {keys.map((k, i) => (
                    <span key={k}>
                      {i > 0 && " "}
                      <kbd>{k}</kbd>
                    </span>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="dialog-actions">
        <button type="button" className="btn" onClick={onClose} autoFocus>
          {t("common.close")}
        </button>
      </div>
    </dialog>
  );
}
