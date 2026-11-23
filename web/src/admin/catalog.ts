import type { CatalogModel } from "../api/types";

export interface CatalogFilter {
  query: string;
  toolsOnly: boolean; // drops only the models the provider says cannot use tools
  allKinds: boolean; // also voice, images, embeddings, moderation…
}

export function filterCatalog(models: CatalogModel[], filter: CatalogFilter): CatalogModel[] {
  const query = filter.query.trim().toLowerCase();
  const rank = (m: CatalogModel) => (m.tools === true ? 0 : m.tools === null ? 1 : 2);
  // Models that take tools first: they are the ones the assistant can use.
  return models
    .filter(
      (m) =>
        (filter.allKinds || m.kind === "chat") &&
        (!filter.toolsOnly || m.tools !== false) &&
        (!query || m.id.toLowerCase().includes(query)),
    )
    .sort((a, b) => rank(a) - rank(b));
}

export function formatTokens(value: number | null): string {
  if (!value) return "—";
  if (value >= 1_000_000) return `${Math.round(value / 1_048_576)}M`;
  if (value >= 1_000) return `${Math.round(value / 1_000)}K`;
  return String(value);
}
