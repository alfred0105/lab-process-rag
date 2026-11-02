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
  form.append('title', metadata.title); form.append('authors', metadata.authors ?? '');
  form.append('year', metadata.year === null ? '' : String(metadata.year));
  form.append('doi', metadata.doi ?? ''); form.append('abstract', metadata.abstract ?? '');
  form.append('metadata_sources', JSON.stringify(metadata.metadata_sources));
  form.append('metadata_reviewed', 'true');
  return request<any>('/papers', form);
};

export type PaperEvidence = { evidence_id: number; page: number; section: string | null; text: string };
export const paperPdfUrl = (paperId: number, topicId: number) => `/api/papers/${paperId}/pdf?topic_id=${topicId}`;
export const fetchPaperEvidence = async (paperId: number, topicId: number): Promise<PaperEvidence[]> => {
  const response = await fetch(`/api/papers/${paperId}/evidence?topic_id=${topicId}`);
  if (!response.ok) throw new Error((await response.text()) || `Request failed (${response.status})`);
  return response.json();
};
