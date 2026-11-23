import { memo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

// Model output is Markdown, rendered without raw HTML (react-markdown ignores it by default)
// and with links that never pass the page as referrer or opener (ADR 0019).
const SAFE_PROTOCOLS = /^(https?:|mailto:)/i;

const components: Components = {
  a: ({ href, children }) =>
    href && SAFE_PROTOCOLS.test(href) ? (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    ) : (
      <span>{children}</span>
    ),
  img: ({ alt }) => <span>{alt}</span>, // no remote images: they would leak that the page was read
};

export const Markdown = memo(function Markdown({ text }: { text: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components} skipHtml>
      {text}
    </ReactMarkdown>
  );
});
