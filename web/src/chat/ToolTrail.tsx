import { ChevronDown, CircleCheck, CircleX, LoaderCircle, Wrench } from "lucide-react";
import { useId, useState } from "react";

import type { ToolUse } from "../api/types";
import { useI18n } from "../i18n";

export function argumentsText(args: Record<string, unknown>): string {
  return Object.entries(args)
    .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
    .join("  ");
}

/** What the agent did in Odoo, as the person: tool, arguments, outcome. Never the data. */
export function ToolTrail({ tools, login, running }: { tools: ToolUse[]; login: string; running: boolean }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const id = useId();
  if (!tools.length) return null;

  const busy = running && tools.some((tool) => tool.ok === null);
  return (
    <div className="trail" data-open={open}>
      <button type="button" className="trail-head" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
        {busy ? <span className="spinner" aria-hidden /> : <Wrench aria-hidden />}
        <span>{busy ? t("tools.running", { login }) : t("tools.summary", { count: tools.length, login })}</span>
        <ChevronDown className="chevron" aria-hidden />
      </button>
      <div className="trail-body" id={id}>
        <ol aria-hidden={!open}>
          {tools.map((tool, index) => (
            <li key={index} className="trail-step">
              {tool.ok === null ? (
                <LoaderCircle className="status-icon run" aria-label={t("tools.pending")} />
              ) : tool.ok ? (
                <CircleCheck className="status-icon ok" aria-label={t("tools.done")} />
              ) : (
                <CircleX className="status-icon bad" aria-label={t("tools.failed")} />
              )}
              <div>
                <span className="trail-name">{tool.name}</span>
                {Object.keys(tool.arguments).length > 0 && (
                  <span className="trail-args" title={argumentsText(tool.arguments)}>
                    {argumentsText(tool.arguments)}
                  </span>
                )}
              </div>
              <span className="trail-result">
                {tool.ok === null
                  ? t("tools.pending")
                  : !tool.ok
                    ? t("tools.failed")
                    : tool.count !== null
                      ? t("tools.ok", { count: tool.count })
                      : t("tools.done")}
              </span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
