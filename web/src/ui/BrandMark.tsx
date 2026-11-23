// The product mark: a speech bubble with a key, drawn as SVG (no icon font, no emoji).
export function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-4.9A8 8 0 1 1 21 12Z" />
        <circle cx="10" cy="12" r="2" />
        <path d="M12 12h4.5M15 12v1.8" />
      </svg>
    </span>
  );
}
