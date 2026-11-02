import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, BookOpen, ChevronLeft, ChevronRight, FileText, LoaderCircle, Minus, Plus, Search, ZoomIn, Sparkles, RotateCw } from 'lucide-react';
import * as pdfjs from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { createStructuredPaperAnalysis, fetchPaperEvidence, fetchStructuredPaperAnalysis, paperPdfUrl, type PaperEvidence, type StructuredPaperAnalysis } from '../api/papers';
import { useLanguage } from '../language';

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
type PaperRecord = { id: number; title: string; authors: string; year: number | null; doi: string | null; abstract: string | null; filename: string; pdf_available: boolean; summary: string | null; summary_method: string | null; summary_source_pages: number[] };

export default function PaperReader({ paper, topicId, onBack }: { paper: PaperRecord; topicId: number; onBack: () => void }) {
  const { t } = useLanguage();
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const renderRef = useRef<pdfjs.RenderTask | null>(null);
  const [document, setDocument] = useState<pdfjs.PDFDocumentProxy | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [containerWidth, setContainerWidth] = useState(0);
  const [fitWidth, setFitWidth] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [evidence, setEvidence] = useState<PaperEvidence[]>([]);
  const [evidenceError, setEvidenceError] = useState('');
  const [panel, setPanel] = useState<'overview' | 'summary' | 'structured' | 'evidence'>('overview');
  const [structured, setStructured] = useState<StructuredPaperAnalysis | null>(null);
  const [structuredBusy, setStructuredBusy] = useState(false);
  const [structuredError, setStructuredError] = useState('');

  useEffect(() => {
    let active = true;
    setDocument(null); setPageNumber(1); setError('');
    if (!paper.pdf_available) { setError(t('Original PDF is unavailable for this older paper.')); return; }
    setBusy(true);
    const loading = pdfjs.getDocument({ url: paperPdfUrl(paper.id, topicId) });
    loading.promise.then(pdf => { if (active) setDocument(pdf); })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : t('The PDF could not be opened.')); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; renderRef.current?.cancel(); void loading.destroy(); };
  }, [paper.id, paper.pdf_available, topicId, t]);

  useEffect(() => {
    let active = true;
    renderRef.current?.cancel();
    if (!document || !canvasRef.current || !hostRef.current) return;
    if (pageNumber < 1 || pageNumber > document.numPages) { setError(t('That page number is outside this PDF.')); return; }
    setBusy(true); setError('');
    document.getPage(pageNumber).then(page => {
      if (!active || !canvasRef.current || !hostRef.current) return;
      const base = page.getViewport({ scale: 1 });
      const fitScale = Math.min(1.65, Math.max(0.5, (hostRef.current.clientWidth - 28) / base.width));
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
      const scale = (fitWidth ? fitScale : zoom) * pixelRatio;
      const viewport = page.getViewport({ scale });
      const canvas = canvasRef.current;
      const context = canvas.getContext('2d');
      if (!context) throw new Error(t('Canvas rendering is unavailable.'));
      canvas.width = Math.ceil(viewport.width); canvas.height = Math.ceil(viewport.height);
      canvas.style.width = `${viewport.width / pixelRatio}px`; canvas.style.height = `${viewport.height / pixelRatio}px`;
      const task = page.render({ canvas, canvasContext: context, viewport });
      renderRef.current = task;
      return task.promise;
    }).catch(reason => {
      if (active && reason?.name !== 'RenderingCancelledException') setError(reason instanceof Error ? reason.message : t('The PDF page could not be rendered.'));
    }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; renderRef.current?.cancel(); };
  }, [document, pageNumber, zoom, fitWidth, containerWidth, t]);

  useEffect(() => {
    let active = true;
    setEvidence([]); setEvidenceError('');
    fetchPaperEvidence(paper.id, topicId).then(items => { if (active) setEvidence(items); })
      .catch(reason => { if (active) setEvidenceError(reason instanceof Error ? reason.message : String(reason)); });
    return () => { active = false; };
  }, [paper.id, topicId]);

  useEffect(() => {
    let active = true;
    setStructured(null); setStructuredError('');
    fetchStructuredPaperAnalysis(paper.id, topicId).then(value => { if (active) setStructured(value); })
      .catch(reason => { if (active) setStructuredError(reason instanceof Error ? reason.message : String(reason)); });
    return () => { active = false; };
  }, [paper.id, topicId]);

  const runStructuredAnalysis = async (reanalyze = false) => {
    setStructuredBusy(true); setStructuredError('');
    try { setStructured(await createStructuredPaperAnalysis(paper.id, topicId, reanalyze)); }
    catch (reason) { setStructuredError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setStructuredBusy(false); }
  };

  useEffect(() => {
    const host = hostRef.current;
    if (!host || !fitWidth) return;
    const observer = new ResizeObserver(entries => setContainerWidth(entries[0]?.contentRect.width ?? 0));
    observer.observe(host);
    return () => observer.disconnect();
  }, [fitWidth]);

  const jump = (page: number) => {
    if (document && page >= 1 && page <= document.numPages) { setPageNumber(page); setPanel('evidence'); }
    else setError(t('That page number is outside this PDF.'));
  };
  return <section className="paper-reader">
    <header className="paper-reader-head"><button type="button" className="button outline small" onClick={onBack}><ArrowLeft size={14}/>{t('Back to papers')}</button><div><div className="eyebrow">{t('PAPER READER')}</div><h2>{paper.title}</h2><small>{paper.authors}{paper.year ? ` · ${paper.year}` : ''}{paper.doi ? ` · DOI ${paper.doi}` : ''}</small></div><span className={`paper-source-status ${paper.pdf_available ? 'available' : ''}`}>{paper.pdf_available ? t('Original PDF available') : t('Original PDF unavailable')}</span></header>
    <div className="paper-reader-layout">
      <section className="paper-viewer card">
        <div className="paper-viewer-toolbar"><span className="paper-filename"><FileText size={14}/>{paper.filename}</span>{document && <><div className="paper-page-control"><button type="button" aria-label={t('Previous page')} disabled={pageNumber <= 1} onClick={() => setPageNumber(page => Math.max(1, page - 1))}><ChevronLeft size={16}/></button><input aria-label={t('Page number')} type="number" min="1" max={document.numPages} value={pageNumber} onChange={event => { const value = Number(event.target.value); if (Number.isInteger(value) && value >= 1 && value <= document.numPages) { setPageNumber(value); setError(''); } else if (event.target.value) setError(t('That page number is outside this PDF.')); }}/><span>/ {document.numPages}</span><button type="button" aria-label={t('Next page')} disabled={pageNumber >= document.numPages} onClick={() => setPageNumber(page => Math.min(document.numPages, page + 1))}><ChevronRight size={16}/></button></div><div className="paper-zoom-control"><button type="button" aria-label={t('Zoom out')} onClick={() => { setFitWidth(false); setZoom(value => Math.max(0.5, +(value - 0.15).toFixed(2))); }}><Minus size={14}/></button><span>{fitWidth ? t('Fit width') : `${Math.round(zoom * 100)}%`}</span><button type="button" aria-label={t('Zoom in')} onClick={() => { setFitWidth(false); setZoom(value => Math.min(2.5, +(value + 0.15).toFixed(2))); }}><Plus size={14}/></button><button type="button" className={fitWidth ? 'selected' : ''} aria-label={t('Fit width')} onClick={() => setFitWidth(true)}><ZoomIn size={14}/></button></div></>}</div>
        <div className="paper-canvas-scroll" ref={hostRef}>{busy && <div className="paper-reader-loading"><LoaderCircle className="spin" size={20}/>{t('Loading PDF page…')}</div>}{error && <div className="paper-reader-message"><BookOpen size={22}/><b>{t('PDF unavailable')}</b><span>{error}</span></div>}<canvas ref={canvasRef} className="paper-pdf-canvas" aria-label={`${t('PDF page')} ${pageNumber}`}/></div>
        <div className="paper-reader-foot">{t('The original PDF page is rendered as supplied. Extracted text and AI summary are shown separately.')}</div>
      </section>
      <aside className="paper-info-panel card">
        <nav className="paper-info-tabs" aria-label={t('Paper details')}>{(['overview','summary','structured','evidence'] as const).map(name => <button type="button" key={name} className={panel === name ? 'active' : ''} onClick={() => setPanel(name)}>{t(name === 'overview' ? 'Overview' : name === 'summary' ? 'AI Summary' : name === 'structured' ? 'Structured Analysis' : 'Evidence')}{name === 'evidence' && <span>{evidence.length}</span>}</button>)}</nav>
        {panel === 'overview' && <div className="paper-detail-content"><h3>{t('Original abstract')}</h3>{paper.abstract ? <p className="paper-abstract">{paper.abstract}</p> : <p className="paper-muted">{t('No original abstract was recorded.')}</p>}<dl><dt>{t('Authors')}</dt><dd>{paper.authors || '—'}</dd><dt>{t('Publication year')}</dt><dd>{paper.year ?? '—'}</dd><dt>DOI</dt><dd>{paper.doi || '—'}</dd><dt>{t('Research topic')}</dt><dd>{t('Current research space')}</dd><dt>{t('Original PDF')}</dt><dd>{paper.pdf_available ? t('Available locally') : t('Original file not stored')}</dd></dl></div>}
        {panel === 'summary' && <div className="paper-detail-content"><h3>{t('AI Summary')}</h3>{paper.summary ? <><p className="paper-summary-body">{paper.summary}</p><small className="paper-summary-method">{paper.summary_method === 'gemma_excerpt' ? t('Gemma excerpt summary') : t('Extractive preview')} · {t('source pages')}: </small><div className="paper-summary-pages">{paper.summary_source_pages?.map(page => <button type="button" key={page} onClick={() => jump(page)}>{t('Page')} {page}</button>)}</div></> : <p className="paper-muted">{t('No AI summary is available.')}</p>}<p className="paper-summary-separation">{t('AI summary is a system-generated interpretation. The original abstract above is publisher or paper text.')}</p></div>}
        {panel === 'structured' && <div className="paper-detail-content structured-paper-analysis">
          <div className="structured-paper-heading"><div><h3>{t('Structured Analysis')}</h3><p>{t('Evidence-linked fields extracted from this paper. Review each source in the original PDF.')}</p></div>{structured?.status === 'completed' && <button type="button" className="button outline small" disabled={structuredBusy} onClick={() => void runStructuredAnalysis(true)}><RotateCw size={13}/>{t('Reanalyze')}</button>}</div>
          {structuredBusy && <p className="paper-reader-inline-status"><LoaderCircle className="spin" size={15}/>{t('Analyzing paper evidence with Gemma…')}</p>}
          {structuredError && <p className="paper-reader-inline-error">{structuredError}</p>}
          {structured?.status !== 'completed' && !structuredBusy && <div className="structured-paper-empty"><Sparkles size={19}/><b>{t('No structured analysis yet')}</b><p>{t('Gemma will extract only information supported by indexed passages and link each item to its source page.')}</p><button type="button" className="button primary small" onClick={() => void runStructuredAnalysis()}><Sparkles size={14}/>{t('Analyze paper')}</button></div>}
          {structured?.status === 'completed' && structured.analysis && <><div className="structured-paper-meta">{t('AI-extracted · verify against source')} · {structured.model || 'Gemma'}{structured.generated_at ? ` · ${new Date(structured.generated_at).toLocaleString()}` : ''}</div><StructuredSections analysis={structured.analysis} sources={structured.sources} onSource={jump} t={t}/></>}
        </div>}
        {panel === 'evidence' && <div className="paper-evidence-panel"><div className="paper-evidence-heading"><div><h3>{t('RAG evidence')}</h3><small>{t('Select a passage to open its source page.')}</small></div><Search size={15}/></div>{evidenceError && <p className="paper-muted">{evidenceError}</p>}{evidence.map(item => <button type="button" className="paper-evidence-item" key={item.evidence_id} onClick={() => jump(item.page)}><span><b>Evidence {item.evidence_id}</b><em>{t('Page')} {item.page}{item.section ? ` · ${item.section}` : ''}</em></span><p>{item.text}</p></button>)}{!evidence.length && !evidenceError && <p className="paper-muted">{t('No indexed evidence excerpts are available.')}</p>}</div>}
      </aside>
    </div>
  </section>;
}

function StructuredSections({ analysis, sources, onSource, t }: {
  analysis: StructuredPaperAnalysis['analysis'];
  sources: StructuredPaperAnalysis['sources'];
  onSource: (page: number) => void;
  t: (value: string) => string;
}) {
  if (!analysis) return null;
  const labels: Record<string, string> = {
    research_objectives: 'Research objectives', materials: 'Materials and samples', experimental_methods: 'Experimental methods',
    process_conditions: 'Process conditions', characterization_methods: 'Characterization methods', key_findings: 'Key findings',
    reported_limitations: 'Reported limitations', analysis_limitations: 'Analysis limitations',
  };
  const recordSources = (value: unknown) => Array.isArray(value) ? value.map(Number).filter(Number.isFinite) : [];
  const cite = (item: Record<string, unknown>) => {
    const ids = recordSources(item.evidence_ids);
    const pages = [...new Set(ids.map(id => sources.find(source => source.evidence_id === id)?.page).filter((page): page is number => typeof page === 'number'))];
    return pages.length ? <div className="structured-paper-citations">{pages.map(page => <button type="button" key={page} onClick={() => onSource(page)}>{t('Source')} · {t('Page')} {page}</button>)}</div> : <small className="paper-muted">{t('No source page available')}</small>;
  };
  const objectItems = (key: string) => Array.isArray(analysis[key]) ? (analysis[key] as Array<Record<string, unknown>>) : [];
  const stringItems = (key: string) => Array.isArray(analysis[key]) ? (analysis[key] as string[]) : [];
  const field = (value: unknown) => typeof value === 'string' && value.trim() ? value : null;
  const card = (title: string, body: string, item?: Record<string, unknown>, extra?: string) => <article className="structured-paper-item" key={`${title}-${body}`}><b>{body}</b>{extra && <p>{extra}</p>}{item && cite(item)}</article>;
  return <div className="structured-paper-sections">
    {objectItems('research_objectives').length > 0 && <section><h4>{t(labels.research_objectives)}</h4>{objectItems('research_objectives').map((item, index) => card(`${index}`, String(item.description ?? ''), item))}</section>}
    {objectItems('materials').length > 0 && <section><h4>{t(labels.materials)}</h4><div className="structured-paper-table-wrap"><table><thead><tr><th>{t('Material')}</th><th>{t('Formula')}</th><th>{t('Role')}</th><th>{t('Details')}</th><th>{t('Source')}</th></tr></thead><tbody>{objectItems('materials').map((item, index) => <tr key={index}><td>{field(item.name) ?? '—'}</td><td>{field(item.formula) ?? '—'}</td><td>{field(item.role) ?? '—'}</td><td>{field(item.details) ?? '—'}</td><td>{cite(item)}</td></tr>)}</tbody></table></div></section>}
    {objectItems('experimental_methods').length > 0 && <section><h4>{t(labels.experimental_methods)}</h4>{objectItems('experimental_methods').map((item, index) => card(`${index}`, String(item.name ?? ''), item, field(item.description) ?? undefined))}</section>}
    {objectItems('process_conditions').length > 0 && <section><h4>{t(labels.process_conditions)}</h4><div className="structured-paper-table-wrap"><table><thead><tr><th>{t('Process')}</th><th>{t('Parameter')}</th><th>{t('Value')}</th><th>{t('Sample / uncertainty')}</th><th>{t('Source')}</th></tr></thead><tbody>{objectItems('process_conditions').map((item, index) => <tr key={index}><td>{field(item.method) ?? '—'}</td><td>{field(item.parameter) ?? '—'}</td><td>{[field(item.value), field(item.unit)].filter(Boolean).join(' ') || '—'}</td><td>{[field(item.sample), field(item.uncertainty)].filter(Boolean).join(' · ') || '—'}</td><td>{cite(item)}</td></tr>)}</tbody></table></div></section>}
    {objectItems('characterization_methods').length > 0 && <section><h4>{t(labels.characterization_methods)}</h4>{objectItems('characterization_methods').map((item, index) => card(`${index}`, String(item.name ?? ''), item, [field(item.purpose), field(item.instrument_conditions)].filter(Boolean).join(' · ') || undefined))}</section>}
    {objectItems('key_findings').length > 0 && <section><h4>{t(labels.key_findings)}</h4>{objectItems('key_findings').map((item, index) => card(`${index}`, String(item.finding ?? ''), item, [field(item.sample), field(item.condition), field(item.quantitative_value), field(item.unit)].filter(Boolean).join(' · ') || undefined))}</section>}
    <section><h4>{t(labels.reported_limitations)}</h4>{objectItems('reported_limitations').length ? objectItems('reported_limitations').map((item, index) => card(`${index}`, String(item.description ?? ''), item)) : <p className="paper-muted">{t('No explicit author-reported limitation was found in the selected excerpts. This does not mean the paper has none.')}</p>}</section>
    <section><h4>{t(labels.analysis_limitations)}</h4>{stringItems('analysis_limitations').length ? stringItems('analysis_limitations').map((item, index) => <p className="paper-muted" key={index}>{item}</p>) : <p className="paper-muted">{t('No extraction limitation was identified during this analysis.')}</p>}</section>
    {Object.entries(labels).filter(([key]) => key !== 'analysis_limitations').every(([key]) => objectItems(key).length === 0) && <p className="paper-muted">{t('No supported structured findings were extracted from the selected excerpts.')}</p>}
  </div>;
}
