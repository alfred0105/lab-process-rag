import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Archive, Camera, Clock3, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { api } from '../api/client';
import { useLanguage } from '../language';
import type { AnalysisRun, Experiment, ResearchTopic } from '../types';

export default function ProcessTimeline({ topic, onArchive, onChanged }: { topic: ResearchTopic; onArchive: () => void; onChanged: () => void }) {
  const { t } = useLanguage();
  const [runs, setRuns] = useState<Experiment[]>([]);
  const [analysisRuns, setAnalysisRuns] = useState<AnalysisRun[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [captions, setCaptions] = useState<Record<number, string>>({});
  const selected = runs.find((run) => run.id === selectedId) ?? null;
  const runEntries = useMemo(() => [...runs]
    .sort((a, b) => (a.date ?? '').localeCompare(b.date ?? '') || a.id - b.id)
    .map((run) => {
      const sameMethod = runs.filter((candidate) => run.method_version_id != null
        ? candidate.method_version_id === run.method_version_id
        : candidate.method_version_id == null && candidate.method_name === run.method_name && candidate.target === run.target);
      const runNumber = run.method_run_number ?? sameMethod.filter((candidate) => candidate.id <= run.id).length;
      return { run, runNumber };
    }), [runs]);
  const reload = async () => {
    try {
      const [items, measurements] = await Promise.all([api.experiments(topic.id), api.analysisRuns(topic.id)]);
      setRuns(items);
      setAnalysisRuns(measurements);
      setSelectedId((current) => items.some((run) => run.id === current) ? current : null);
    } catch (cause) { setError(String(cause)); }
  };
  useEffect(() => { void reload(); }, [topic.id]);
  const orderedSteps = useMemo(() => [...(selected?.steps ?? [])].sort((a, b) => a.order_index - b.order_index), [selected]);
  const runDuration = (minutes?: number | null) => {
    if (minutes == null) return t('Duration not recorded');
    const hours = Math.floor(minutes / 60); const remaining = minutes % 60;
    return [hours ? `${hours}${t('h')}` : '', remaining ? `${remaining}${t('min')}` : ''].filter(Boolean).join(' ') || `0 ${t('min')}`;
  };

  const addLog = async (event: FormEvent<HTMLFormElement>, stepId: number) => {
    event.preventDefault();
    if (!selected || busy) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true); setError('');
    try {
      await api.addStepLog(selected.id, stepId, {
        kind: String(data.get('kind') || 'measurement'),
        label: String(data.get('label') || '').trim(),
        value: String(data.get('value') || '').trim(),
        unit: String(data.get('unit') || '').trim() || null,
        notes: String(data.get('notes') || '').trim(),
      });
      form.reset(); await reload(); onChanged();
    } catch (cause) { setError(String(cause)); }
    finally { setBusy(false); }
  };

  const addImage = async (file: File | undefined, stepId: number) => {
    if (!selected || !file || busy) return;
    setBusy(true); setError('');
    try {
      await api.attachStepImage(selected.id, stepId, file, captions[stepId] ?? '');
      setCaptions((current) => ({ ...current, [stepId]: '' })); await reload(); onChanged();
    } catch (cause) { setError(String(cause)); }
    finally { setBusy(false); }
  };

  const removeLog = async (logId: number) => {
    if (!selected || !window.confirm(t('Remove this process record?'))) return;
    try { await api.deleteStepLog(selected.id, logId); await reload(); onChanged(); }
    catch (cause) { setError(String(cause)); }
  };
  const removeImage = async (attachmentId: number) => {
    if (!selected || !window.confirm(t('Remove this image?'))) return;
    try { await api.deleteStepImage(selected.id, attachmentId); await reload(); onChanged(); }
    catch (cause) { setError(String(cause)); }
  };

  return <section className="process-timeline-workspace">
    <header className="timeline-toolbar"><div><div className="eyebrow">{t('EXPERIMENT RUN')}</div><h2>{t('Process timeline')}</h2><p>{t('See the process, intermediate measurements, images, and results in one place.')}</p></div><button className="button outline small" onClick={onArchive}><Archive size={14}/>{t('Open archived screen')}</button></header>
    {error && <div className="error timeline-error">{error}<button className="text-button" onClick={() => setError('')}>{t('Dismiss')}</button></div>}
    {!runs.length ? <div className="card timeline-empty"><h3>{t('No experiment runs yet')}</h3><p>{t('Create a method and record its first run to start using the process timeline.')}</p><button className="button primary" onClick={onArchive}><Plus size={14}/>{t('Open archived screen')}</button></div> : <>
      <section className="card timeline-run-list"><header className="timeline-run-list-head"><div><h3>{t('Experiment run history')}</h3><p>{t('Select an experiment title to expand its process, results, and analysis records.')}</p></div><span className="timeline-run-total">{runs.length} {t('runs recorded')}</span><button className="button outline small" onClick={() => void reload()}><RefreshCw size={13}/>{t('Refresh')}</button></header>
        <div className="timeline-accordion" aria-label={t('Experiment run history')}>{runEntries.map(({ run, runNumber }) => <article className={`timeline-accordion-item ${run.id === selected?.id ? 'open' : ''}`} key={run.id}>
          <button type="button" className="timeline-accordion-trigger" aria-expanded={run.id === selected?.id} aria-controls={`run-panel-${run.id}`} onClick={() => setSelectedId((current) => current === run.id ? null : run.id)}><span className="timeline-accordion-number">{t('Experiment')} {runNumber}</span><span className="timeline-accordion-title"><b>{run.name}</b><small>{run.method_name ?? t('No reusable method')} · {run.date || t('Date not recorded')}</small></span><span className="timeline-accordion-duration">{runDuration(run.duration_minutes)}</span><span className={`status ${run.status}`}>{t(run.status.replace('_', ' '))}</span><span className="timeline-accordion-chevron" aria-hidden="true">{run.id === selected?.id ? '−' : '+'}</span></button>
        </article>)}</div>
      </section>
      {selected && <>
        <section className="timeline-accordion-panel" role="region" id={`run-panel-${selected.id}`} aria-label={selected.name}><section className="card timeline-run-summary"><div className="timeline-summary-main"><div><span className={`status ${selected.status}`}>{t(selected.status.replace('_', ' '))}</span><h3>{selected.name}</h3><p>{selected.code} · {selected.target} · {selected.method_name ?? t('No reusable method')}</p></div><div className="timeline-summary-meta"><span>{t('Date')}<b>{selected.date || '—'}</b></span><span>{t('Duration')}<b>{runDuration(selected.duration_minutes)}</b></span><span>{t('Method version')}<b>{selected.method_version ? `v${selected.method_version}` : '—'}</b></span></div></div>
          {!!selected.results.length && <div className="timeline-final-results"><b>{t('Final results')}</b>{selected.results.map((result, index) => <span key={`${result.key}-${index}`}>{result.key}: {result.value} {result.unit ?? ''}</span>)}</div>}
          {!!selected.observations.length && <div className="timeline-summary-observations">{selected.observations.map((item, index) => <span key={`${item.category}-${index}`}>{item.description}</span>)}</div>}
        </section>
        {analysisRuns.some((item) => item.experiment_id === selected.id) && <section className="card timeline-analysis-links"><h3>{t('Measurement analyses linked to this experiment')}</h3>{analysisRuns.filter((item) => item.experiment_id === selected.id).map((item) => <article key={item.id}><div><b>{item.result_key || item.modality}</b><small>{item.modality.toUpperCase()} · {item.filename}{item.process_step_id ? ` · ${selected.steps.find((step) => step.id === item.process_step_id)?.name ?? ''}` : ''}</small></div><span className={`analysis-state ${item.analysis_status === 'completed' ? 'complete' : 'pending'}`}>{item.analysis_status === 'completed' ? t('Analysis complete') : t('Analysis pending')}</span>{item.analysis_status === 'completed' && <div className="timeline-analysis-output">{Object.entries(item.result ?? {}).filter(([key]) => !['notice', 'tool_id', 'modality', 'filename'].includes(key)).slice(0, 6).map(([key, value]) => <span key={key}><b>{key.replaceAll('_', ' ')}</b> {typeof value === 'object' ? JSON.stringify(value) : String(value)}</span>)}</div>}</article>)}</section>}
        {!orderedSteps.length ? <div className="empty-hint">{t('This run has no process steps to display.')}</div> : <div className="timeline-track">{orderedSteps.map((step, index) => {
          const logs = (selected.step_logs ?? []).filter((item) => item.step_id === step.id).sort((a, b) => a.occurred_at.localeCompare(b.occurred_at));
          const images = (selected.attachments ?? []).filter((item) => item.step_id === step.id);
          const env = (selected.environment_records ?? []).filter((item) => item.step_id === step.id);
          return <article className="timeline-step card" key={step.id}>
            <div className="timeline-step-marker"><span>{index + 1}</span><small>{index === 0 ? t('Start') : index === orderedSteps.length - 1 ? t('Finish') : t('Step')}</small></div>
            <div className="timeline-step-content">
              <header className="timeline-step-head"><div><h3>{step.name}</h3>{step.description && <p>{step.description}</p>}</div><span className="timeline-step-count">{logs.length + images.length + step.variables.length + env.length} {t('records')}</span></header>
              <div className="timeline-step-grid">
                <section className="timeline-data-block"><h4>{t('Recorded process conditions')}</h4>{step.variables.length ? <div className="timeline-chips">{step.variables.map((variable) => <span key={variable.id}><b>{variable.name}</b><strong>{variable.value} {variable.unit ?? ''}</strong></span>)}</div> : <small>{t('No process values recorded for this step.')}</small>}</section>
                <section className="timeline-data-block"><h4>{t('Environment')}</h4>{env.length ? env.map((item) => <div className="timeline-event-line" key={item.id}><Clock3 size={13}/><div><b>{t(item.phase)} · {new Date(item.measured_at).toLocaleString()}</b><span>{item.temperature_c != null && `${t('Ambient temperature')} ${item.temperature_c} °C`}{item.relative_humidity_percent != null && ` · ${t('Relative humidity')} ${item.relative_humidity_percent}%`}{item.pressure_kpa != null && ` · ${t('Ambient pressure')} ${item.pressure_kpa} kPa`}</span>{item.notes && <small>{item.notes}</small>}</div></div>) : <small>{t('No environment measurements recorded.')}</small>}</section>
              </div>
              {!!logs.length && <section className="timeline-data-block timeline-events"><h4>{t('Intermediate values and observations')}</h4>{logs.map((item) => <div className={`timeline-event-line ${item.kind}`} key={item.id}><Clock3 size={13}/><div><b>{item.label}{item.value && ` · ${item.value} ${item.unit ?? ''}`}</b><span>{new Date(item.occurred_at).toLocaleString()}</span>{item.notes && <small>{item.notes}</small>}</div><button className="icon-button" title={t('Remove')} onClick={() => void removeLog(item.id)}><Trash2 size={13}/></button></div>)}</section>}
              {!!images.length && <section className="timeline-data-block"><h4>{t('Stage images')}</h4><div className="timeline-gallery">{images.map((image) => <figure key={image.id}><a href={image.image_url} target="_blank" rel="noreferrer"><img src={image.image_url} alt={image.caption || image.filename}/></a><figcaption>{image.caption || image.filename}<button className="icon-button" title={t('Remove')} onClick={() => void removeImage(image.id)}><Trash2 size={12}/></button></figcaption></figure>)}</div></section>}
              <details className="timeline-add-details"><summary><Plus size={14}/>{t('Add a measurement or observation')}</summary><form className="timeline-log-form" onSubmit={(event) => void addLog(event, step.id)}><select name="kind" aria-label={t('Record type')}><option value="measurement">{t('Measurement')}</option><option value="observation">{t('Observation')}</option><option value="result">{t('Intermediate result')}</option></select><input name="label" required placeholder={t('e.g. pH, color, particle size')}/><input name="value" placeholder={t('Value or description')}/><input name="unit" placeholder={t('Unit')}/><input name="notes" placeholder={t('Notes')}/><button className="button primary small" disabled={busy}><Plus size={13}/>{t('Save record')}</button></form></details>
              <details className="timeline-add-details"><summary><Camera size={14}/>{t('Attach a photo to this step')}</summary><div className="timeline-image-form"><input value={captions[step.id] ?? ''} onChange={(event) => setCaptions((current) => ({ ...current, [step.id]: event.target.value }))} placeholder={t('Photo caption or sample label')}/><label className="button outline small"><Camera size={13}/>{busy ? t('Saving…') : t('Choose image')}<input type="file" accept="image/jpeg,image/png,image/webp,image/gif" hidden disabled={busy} onChange={(event) => { void addImage(event.target.files?.[0], step.id); event.currentTarget.value = ''; }}/></label><small>{t('JPEG, PNG, WebP, or GIF · up to 15 MiB')}</small></div></details>
            </div>
          </article>;
        })}</div>}
        </section>
      </>}
    </>}
  </section>;
}
