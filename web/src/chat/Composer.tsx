import { ArrowUp, ChevronDown, Square } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, type FormEvent, type KeyboardEvent } from "react";

import type { ModelChoice } from "../api/types";
import { useI18n } from "../i18n";

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  streaming: boolean;
  models: ModelChoice[] | null;
  defaultModel: number | null;
  selectedModel: number | null;
  onSelectModel: (id: number | null) => void;
  disabled?: boolean;
}

export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  streaming,
  models,
  defaultModel,
  selectedModel,
  onSelectModel,
  disabled,
}: Props) {
  const { t } = useI18n();
  const input = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    const element = input.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 224)}px`;
  }, [value]);

  useEffect(() => {
    input.current?.focus();
  }, []);

  const canSend = !streaming && !disabled && value.trim().length > 0;

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (canSend) onSend();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  const defaultLabel = models?.find((m) => m.id === defaultModel)?.label;

  return (
    <form className="composer" onSubmit={submit}>
      <label htmlFor="composer-input" className="sr-only">
        {t("chat.placeholder")}
      </label>
      <textarea
        id="composer-input"
        ref={input}
        rows={1}
        value={value}
        maxLength={8000}
        placeholder={t("chat.placeholder")}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
        disabled={disabled}
      />
      <div className="composer-bar">
        {models && models.length > 0 && (
          <div className="model-picker">
            <label htmlFor="model-select" className="sr-only">
              {t("chat.model")}
            </label>
            <select
              id="model-select"
              value={selectedModel ?? ""}
              onChange={(event) => onSelectModel(event.target.value ? Number(event.target.value) : null)}
            >
              <option value="">
                {defaultLabel ? `${defaultLabel} (${t("chat.modelDefault")})` : t("chat.modelDefault")}
              </option>
              {models.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.label} · {model.provider}
                </option>
              ))}
            </select>
            <ChevronDown aria-hidden />
          </div>
        )}
        {streaming ? (
          <button type="button" className="btn btn-primary composer-send" onClick={onStop} aria-label={t("chat.stop")} title={`${t("chat.stop")} (Esc)`}>
            <Square fill="currentColor" />
          </button>
        ) : (
          <button type="submit" className="btn btn-primary composer-send" disabled={!canSend} aria-label={t("chat.send")} title={t("chat.send")}>
            <ArrowUp />
          </button>
        )}
      </div>
    </form>
  );
}
