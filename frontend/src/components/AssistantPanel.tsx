import { useEffect, useState } from 'react';
import { ExternalLink, Search, Send, Sparkles, Upload } from 'lucide-react';
import { api } from '../api/client';
import type { AIStatus, AssistantHistory, AssistantResult, Experiment, PaperDiscoveryResult } from '../types';
import { useLanguage } from '../language';

export default function AssistantPanel({ onPaperAdded, experiments = [], topicId }: { onPaperAdded?: () => void; experiments?: Experiment[]; topicId?: number }) {
  const { t, language } = useLanguage();
  const [status, setStatus] = useState<AIStatus | null>(null);
  const [query, setQuery] = useState('');
  const [allowGeneralKnowledge, setAllowGeneralKnowledge] = useState(true);
  const [experimentId, setExperimentId] = useState('');
  const [contextScope, setContextScope] = useState<'topic' | 'method' | 'step'>('topic');
  const [contextStepName, setContextStepName] = useState('');
  const [paperQuery, setPaperQuery] = useState('');
  const [paperSearch, setPaperSearch] = useState<PaperDiscoveryResult | null>(null);
  const [paperBusy, setPaperBusy] = useState(false);
  const [paperError, setPaperError] = useState('');
  const [uploadMessage, setUploadMessage] = useState('');
  const [result, setResult] = useState<AssistantResult | null>(null);
  const [history, setHistory] = useState<AssistantHistory[]>([]);
  const [historyError, setHistoryError] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const selectedExperiment = experiments.find((item) => item.id === Number(experimentId));

  useEffect(() => {
    if (!selectedExperiment?.steps.some((item) => item.name === contextStepName)) {
      setContextStepName(selectedExperiment?.steps[0]?.name ?? '');
    }
  }, [experimentId, contextStepName, selectedExperiment]);

  useEffect(() => {
    api.aiStatus().then(setStatus).catch((cause) => setError(t(cause instanceof Error?cause.message:String(cause))));
  }, []);

  const loadHistory = async () => {
    try { setHistory(await api.assistantHistory(topicId)); setHistoryError(''); }
    catch (cause) { setHistoryError(t(cause instanceof Error?cause.message:String(cause))); }
  };

  useEffect(() => { void loadHistory(); }, [topicId]);

  const ask = async () => {
    if (query.trim().length < 3 || busy) return;
    setBusy(true);
    setError('');
    setResult(null);
    try {
      setResult(await api.ask(query.trim(), allowGeneralKnowledge, experimentId ? Number(experimentId) : undefined, topicId, contextScope, contextScope === 'step' ? contextStepName : undefined, language));
      await loadHistory();
    } catch (cause) {
      setError(t(cause instanceof Error?cause.message:String(cause)));
    } finally {
      setBusy(false);
    }
  };

  const findPapers = async (term = paperQuery) => {
    if (term.trim().length < 3 || paperBusy) return;
    setPaperBusy(true); setPaperError(''); setUploadMessage('');
    try { const found = await api.discoverPapers(term.trim()); setPaperSearch(found); setPaperQuery(found.query); }
    catch (cause) { setPaperError(t(cause instanceof Error?cause.message:String(cause))); }
    finally { setPaperBusy(false); }
  };

  const uploadPaper = async (file: File, item: NonNullable<PaperDiscoveryResult['results'][number]>) => {
    const form = new FormData(); form.append('file', file); if (topicId) form.append('topic_id', String(topicId)); form.append('title', item.title);
    form.append('authors', item.authors.join(', ')); if (item.year) form.append('year', String(item.year));
    setUploadMessage(`Indexing ${item.title}…`); setPaperError('');
    try { await api.upload(form); setUploadMessage(`Added and indexed: ${item.title}`); onPaperAdded?.(); }
    catch (cause) { setPaperError(t(cause instanceof Error?cause.message:String(cause))); setUploadMessage(''); }
  };

  return <div className="assistant-layout">
    <section className="card assistant-card">
      <div className="card-head">
        <div><div className="card-title"><Sparkles size={17}/> {t('Gemma assistant')}</div>
          <div className="card-sub">{t('Ask about your papers, materials, methods, or general scientific concepts.')}</div></div>
        <span className={`ai-status ${status?.enabled && status.reachable && status.model_installed ? 'ready' : ''}`}>
          {t(status?.enabled ? !status.model ? 'MODEL NOT SELECTED' : status.model_installed ? 'LOCAL MODEL READY' : status.reachable ? 'MODEL NOT INSTALLED' : 'MODEL SERVER OFFLINE' : 'AI DISABLED')}
        </span>
      </div>
      {status && <div className="ai-config">
        <span>{t('Provider')} <b>{status.provider}</b></span><span>{t('Model')} <b>{status.model ?? t('not selected')}</b></span>
        <span>{t('Context')} <b>{status.memory_profile.context_tokens.toLocaleString()} {t('tokens')}</b></span>
        <span>{t('Parallel requests')} <b>{status.memory_profile.max_concurrent_requests}</b></span>
      </div>}
      {!status?.enabled && <div className="ai-notice">AI stays off until you choose a model and set <code>AI_PROVIDER=ollama</code> and <code>OLLAMA_MODEL</code> in the backend environment. The model survey is in the project docs.</div>}
      <label className="assistant-input-label" htmlFor="assistant-question">{t('Your question')}</label>
      <label className="assistant-context-label" htmlFor="experiment-context">{t('Use an experiment record')} <small>{t('Gemma can refer to its steps, settings, results, and observations.')}</small></label>
      <select id="experiment-context" className="assistant-context-select" value={experimentId} onChange={(event) => { setExperimentId(event.target.value); if (!event.target.value && contextScope !== 'topic') setContextScope('topic'); }}>
        <option value="">{t('No experiment selected')}</option>{experiments.map((item) => <option value={item.id} key={item.id}>{item.code} · {item.name} ({t(item.status.replace('_', ' '))})</option>)}
      </select>
      <label className="assistant-context-label" htmlFor="context-scope">{t('Lab context scope')} <small>{t('Choose how much of this research to provide to Gemma.')}</small></label>
      <select id="context-scope" className="assistant-context-select" value={contextScope} onChange={(event) => setContextScope(event.target.value as 'topic' | 'method' | 'step')}>
        <option value="topic">{t('Entire research topic')}</option>
        <option value="method" disabled={!selectedExperiment}>{t('Selected experiment method')}</option>
        <option value="step" disabled={!selectedExperiment}>{t('One process step')}</option>
      </select>
      {contextScope !== 'topic' && !selectedExperiment && <small className="assistant-hint">{t('Select an experiment above to choose its method or process step.')}</small>}
      {contextScope === 'step' && selectedExperiment && <><label className="assistant-context-label" htmlFor="context-step">{t('Process step')}</label><select id="context-step" className="assistant-context-select" value={contextStepName} onChange={(event) => setContextStepName(event.target.value)}>{selectedExperiment.steps.map((item) => <option key={`${item.order_index}-${item.id}`} value={item.name}>{item.order_index + 1}. {item.name}</option>)}</select></>}
      <div className="assistant-input"><textarea id="assistant-question" value={query} maxLength={1000} rows={3}
        placeholder={t('e.g. Summarize this experiment and identify which recorded settings differ from the target…')} onChange={(event) => setQuery(event.target.value)}
        onKeyDown={(event) => { if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) void ask(); }}/>
        <button className="button primary" onClick={() => void ask()} disabled={!status?.enabled || busy || query.trim().length < 3}>
          <Send size={15}/>{busy ? t('Gemma is answering…') : t('Ask Gemma')}
        </button>
      </div>
      <label className="assistant-general-toggle"><input type="checkbox" checked={allowGeneralKnowledge} onChange={(event) => setAllowGeneralKnowledge(event.target.checked)}/>
        <span><b>{t('Allow Gemma’s general knowledge')}</b><small>{t('When enabled, answers can cover gaps or questions without matching papers. Those statements are labeled MODEL KNOWLEDGE and are not paper-verified.')}</small></span>
      </label>
      <small className="assistant-hint">{t('⌘/Ctrl + Enter to submit · SUPPORTED/INFERRED claims cite excerpts; MODEL KNOWLEDGE claims come from Gemma.')}</small>
      {error && <div className="error assistant-error">{error}</div>}
      <section className="assistant-history">
        <div className="assistant-history-head"><div><div className="card-title">{t('Gemma execution history')}</div><small>{t('Saved on this device so you can reopen earlier answers.')}</small></div><button className="text-button" onClick={() => void loadHistory()}>{t('Refresh')}</button></div>
        {historyError && <div className="error">{historyError}</div>}
        {history.length === 0 && !historyError ? <p className="assistant-history-empty">{t('No saved Gemma runs yet.')}</p> : <div className="assistant-history-list">{history.map((item) => <button type="button" className={`assistant-history-item ${result?.history_id === item.id ? 'selected' : ''}`} key={item.id} onClick={() => { setQuery(item.query); setAllowGeneralKnowledge(item.allow_general_knowledge); setExperimentId(item.experiment_id ? String(item.experiment_id) : ''); setResult(item.response); setError(''); }}>
          <span className="assistant-history-main"><b>{item.query}</b><small>{item.context_label || t(item.context_scope === 'topic' ? 'Entire research topic' : item.context_scope === 'method' ? 'Selected experiment method' : 'One process step')} · {item.model || t('model not recorded')}</small></span><span className="assistant-history-date">{new Date(item.created_at).toLocaleString()}</span>
        </button>)}</div>}
      </section>
      {result && <div className="assistant-result"><div className="card-title">{t('Answer')} · {result.model}</div>
        <div className="research-trace"><b>{t('Research steps')}</b><span>{t('Gemma context')}: {result.context_scope?.label ?? t('No lab scope selected')} · {t(result.context_scope?.scope === 'topic' ? 'Entire research topic' : result.context_scope?.scope === 'method' ? 'Selected experiment method' : 'One process step')}</span><span>{t('Scanned paper summaries')}{result.research_trace?.summary_matches?.length ? ` · ${result.research_trace.summary_matches.join(', ')}` : ''}</span><span>{t('Read source passages')} · {result.research_trace?.source_passages_read ?? result.evidence.length}</span>{result.experiment_context&&<span>{t('Loaded lab record')} · {result.experiment_context.code} · {result.experiment_context.name}{result.experiment_context.method_name?` · ${result.experiment_context.method_name} v${result.experiment_context.method_version}`:''}</span>}</div>
        {result.claims.map((claim, index) => <article className="assistant-claim" key={`${index}-${claim.claim}`}>
          <span className={`badge ${claim.status.toLowerCase()}`}>{t(claim.status === 'MODEL_KNOWLEDGE' ? 'GEMMA KNOWLEDGE' : claim.status === 'LAB_RECORD' ? 'LAB RECORD' : claim.status)}</span><p>{claim.claim}</p>
          {claim.evidence_ids.length > 0 && <small>{t('Evidence IDs:')} {claim.evidence_ids.join(', ')}</small>}
          {claim.experiment_refs.length > 0 && <small>{t('Experiment records:')} {claim.experiment_refs.map((id) => experiments.find((item) => item.id === id)?.code ?? `#${id}`).join(', ')}</small>}
        </article>)}
        {result.evidence.map((item) => <article className="evidence-card" key={item.evidence_id}>
          <div><span className="citation">{item.paper_title} · p. {item.page}{item.section ? ` · ${item.section}` : ''} · found via {item.retrieved_via ?? 'full text'}</span></div>
          <p>{item.text}</p><small>Evidence ID {item.evidence_id}</small>
        </article>)}
        {!!result.evidence_gaps?.length && <section className="evidence-gaps"><div className="card-title">{t('Evidence still needed')}</div><p>These are the specific source gaps behind the answer. Search phrases open Crossref results; you can index a paper by selecting its PDF once you have access to it.</p>
          {result.evidence_gaps.map((gap, index) => <article className="gap-card" key={`${index}-${gap.need}`}><b>{gap.need}</b><p>{gap.why_needed}</p><div className="gap-queries">{gap.search_queries.map((term) => <button className="text-button" key={term} onClick={() => { setPaperQuery(term); void findPapers(term); }}>{term} <Search size={12}/></button>)}</div></article>)}
        </section>}
      </div>}
      <section className="paper-discovery"><div className="card-title"><Search size={15}/> {t('Find papers to fill a gap')}</div><p>Search Crossref scholarly metadata. Search terms are sent to Crossref; results link to DOI pages and publisher-provided PDFs when available.</p>
        <div className="paper-search-row"><input aria-label="Paper search terms" placeholder={t('e.g. ZnO nanowire hydrothermal growth temperature effects')} value={paperQuery} onChange={(event) => setPaperQuery(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void findPapers(); }}/><button className="button outline" disabled={paperBusy || paperQuery.trim().length < 3} onClick={() => void findPapers()}><Search size={14}/>{paperBusy ? t('Searching…') : t('Search papers')}</button></div>
        {paperError && <div className="error">{paperError}</div>}{uploadMessage && <div className="paper-upload-message">{uploadMessage}</div>}
        {paperSearch && <div className="discovery-results"><small>{paperSearch.results.length} records from {paperSearch.provider} · metadata only until you add a PDF</small>{paperSearch.results.map((item) => <article className="discovery-card" key={item.doi ?? item.title}><b>{item.title}</b><small>{item.authors.join(', ')}{item.year ? ` · ${item.year}` : ''}{item.journal ? ` · ${item.journal}` : ''}</small><div className="discovery-actions">{item.doi_url && <a href={item.doi_url} target="_blank" rel="noreferrer">{t('Open DOI')} <ExternalLink size={12}/></a>}{item.pdf_url && <a href={item.pdf_url} target="_blank" rel="noreferrer">{t('Publisher PDF')} <ExternalLink size={12}/></a>}<label className="paper-add-button"><Upload size={12}/> {t('Add PDF')}<input type="file" accept="application/pdf" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadPaper(file, item); event.target.value = ''; }}/></label></div></article>)}</div>}
      </section>
    </section>
  </div>;
}
