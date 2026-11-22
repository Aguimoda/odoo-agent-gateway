-- Retrieval index (ADR 0010 and 0011). Idempotent: safe to run on every start.

create extension if not exists vector;

create table if not exists knowledge_chunks (
  id bigint generated always as identity primary key,
  kind text not null check (kind in ('document', 'record')),
  title text not null,
  -- documents: the company handbook, readable by every authenticated user
  doc_path text,
  chunk_index integer check (chunk_index >= 0),
  content text,
  -- records: only a reference; Odoo supplies the text, as the asking user, at query time
  model text,
  record_id bigint check (record_id > 0),
  field text,
  content_hash text not null,
  embedding vector(384) not null,
  indexed_at timestamptz not null default now(),
  constraint knowledge_document_shape check (
    kind <> 'document'
    or (doc_path is not null and chunk_index is not null and content is not null
        and model is null and record_id is null and field is null)
  ),
  -- ADR 0011: record text is never stored in the gateway database.
  constraint knowledge_record_shape check (
    kind <> 'record'
    or (model is not null and record_id is not null and field is not null
        and content is null and doc_path is null and chunk_index is null)
  )
);

create unique index if not exists knowledge_document_chunk_uq
  on knowledge_chunks (doc_path, chunk_index) where kind = 'document';

create unique index if not exists knowledge_record_uq
  on knowledge_chunks (model, record_id, field) where kind = 'record';

create index if not exists knowledge_embedding_hnsw_idx
  on knowledge_chunks using hnsw (embedding vector_cosine_ops);
