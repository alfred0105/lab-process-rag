export type PaperMetadataPreview = {
  title: string; authors: string; year: number | null; doi: string | null; abstract: string | null;
  journal: string | null; metadata_sources: Record<string, string>;
  conflicts: Record<string, { pdf: unknown; crossref: unknown }>;
  needs_review: boolean; warnings: string[];
};

async function request<T>(path: string, form: FormData): Promise<T> {
  const response = await fetch(`/api${path}`, { method: 'POST', body: form });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

export const previewPaperMetadata = (file: File) => {
  const form = new FormData(); form.append('file', file);
  return request<PaperMetadataPreview>('/papers/metadata-preview', form);
};

export const savePaperWithMetadata = (file: File, topicId: number, metadata: PaperMetadataPreview) => {
  const form = new FormData(); form.append('file', file); form.append('topic_id', String(topicId));
  form.append('title', metadata.title); form.append('authors', metadata.authors);
  if (metadata.year !== null) form.append('year', String(metadata.year));
  if (metadata.doi) form.append('doi', metadata.doi);
  if (metadata.abstract) form.append('abstract', metadata.abstract);
  form.append('metadata_sources', JSON.stringify(metadata.metadata_sources));
  return request<any>('/papers', form);
};
