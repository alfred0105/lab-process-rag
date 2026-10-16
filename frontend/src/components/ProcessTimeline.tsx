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
  const processGroups = useMemo(() => {
    const grouped = new Map<string, Experiment[]>();
    for (const run of runs) {
      const signature = JSON.stringify([...run.steps].sort((a, b) => a.order_index - b.order_index).map(step => [step.order_index, step.name, step.step_type]));
      const key = run.method_version_id != null ? `version:${run.method_version_id}` : `process:${run.method_name ?? ''}:${run.target}:${signature}`;
      grouped.set(key, [...(grouped.get(key) ?? []), run]);
    }
    return [...grouped].map(([key, entries]) => {
      const ordered = [...entries].sort((a, b) => (a.date ?? '').localeCompare(b.date ?? '') || a.id - b.id);
      const results = [...new Set(ordered.flatMap(run => run.results.map(result => result.key)))];
      const steps = [...ordered[0].steps].sort((a, b) => a.order_index - b.order_index);
      return { key, name: ordered[0].method_name || ordered[0].target, target: ordered[0].target, version: ordered[0].method_version, entries: ordered, steps, results };
    }).sort((a, b) => a.name.localeCompare(b.name) || (a.version ?? 0) - (b.version ?? 0));
  }, [runs]);
  const selectedProcessGroup = processGroups.find(group => group.entries.some(run => run.id === selected?.id));
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
    <header className="timeline-toolbar"><div><div className="eyebrow">{t('PROCESS · SUB-EXPERIMENTS')}</div><h2>{t('Process timeline')}</h2><p>{t('See the process, intermediate measurements, images, and results in one place.')}</p></div><button className="button outline small" onClick={onArchive}><Archive size={14}/>{t('Open archived screen')}</button></header>
    {error && <div className="error timeline-error">{error}<button className="text-button" onClick={() => setError('')}>{t('Dismiss')}</button></div>}
    {!runs.length ? <div className="card timeline-empty"><h3>{t('No experiment runs yet')}</h3><p>{t('Create a method and record its first run to start using the process timeline.')}</p><button className="button primary" onClick={onArchive}><Plus size={14}/>{t('Open archived screen')}</button></div> : <>
      <section className="card timeline-run-list"><header className="timeline-run-list-head"><div><h3>{t('Processes and sub-experiments')}</h3><p>{t('Each process is one group. Its individual experiments are arranged as dated rows so you can compare results over time.')}</p></div><span className="timeline-run-total">{processGroups.length} {t('processes')} · {runs.length} {t('experiments')}</span><button className="button outline small" onClick={() => void reload()}><RefreshCw size={13}/>{t('Refresh')}</button></header>
        {processGroups.map((group, groupIndex) => <details className="process-history-group" key={group.key} open={groupIndex === 0 || group.entries.some(run => run.id === selected?.id)}><summary><span className="process-history-name"><b>{t('Process')} {groupIndex + 1} · {group.name}{group.version ? ` v${group.version}` : ''}</b><small>{group.target}</small></span><span className="process-history-count">{group.entries.length} {t('experiments')}</span></summary>
          <div className="process-stage-list">{group.steps.map((stage, stageIndex) => <section className="process-stage" key={`${group.key}-stage-${stage.order_index}`}>
            <div className="process-stage-marker"><span>{stageIndex + 1}</span></div>
            <div className="process-stage-body"><header className="process-stage-head"><div><b>{stage.name}</b>{stage.description && <small>{stage.description}</small>}</div><span>{t('Stage')} {stageIndex + 1}</span></header>
              <div className="process-experiment-table-wrap"><table className="process-experiment-table process-stage-table"><thead><tr><th>{t('Date')}</th><th>{t('Sub-experiment')}</th><th>{t('Status')}</th><th>{t('Conditions and records')}</th><th>{t('Analysis files')}</th></tr></thead><tbody>{group.entries.map((run, runIndex) => {
                const runStep = run.steps.find(item => item.order_index === stage.order_index) ?? run.steps.find(item => item.name === stage.name);
                const analysis = analysisRuns.filter(item => item.experiment_id === run.id && item.process_step_id === runStep?.id);
                const logs = (run.step_logs ?? []).filter(item => item.step_id === runStep?.id).sort((a, b) => a.occurred_at.localeCompare(b.occurred_at));
                const images = (run.attachments ?? []).filter(item => item.step_id === runStep?.id);
                return <tr key={run.id} className={run.id === selected?.id ? 'selected' : undefined}>
                  <td className="process-experiment-date">{run.date || '—'}</td>
                  <td><button type="button" className="process-experiment-title" aria-label={`${t('Open experiment record')}: ${run.name}`} onClick={() => setSelectedId(run.id)}><b>{run.name}</b><small>{run.code} · {t('Experiment')} {run.method_run_number ?? runIndex + 1}</small></button></td>
                  <td><span className={`status ${run.status}`}>{t(run.status.replace('_', ' '))}</span></td>
                  <td><div className="process-stage-values">{runStep?.variables.map(variable => <span key={variable.id}><b>{variable.name}</b> {variable.value} {variable.unit ?? ''}</span>)}{logs.map(log => <span key={`log-${log.id}`}><b>{log.label}</b> {log.value} {log.unit ?? ''}</span>)}{!runStep?.variables.length && !logs.length && !images.length && <small>—</small>}{images.length > 0 && <span>{images.length} {t('images')}</span>}</div></td>
                  <td><span className="process-analysis-count">{analysis.length ? `${analysis.length} · ${t('files')}` : '—'}</span></td>
                </tr>;
              })}</tbody></table></div>
            </div>
          </section>)}</div>
          {!!group.results.length && <section className="process-result-section"><h4>{t('Sub-experiment results')}</h4><div className="process-experiment-table-wrap"><table className="process-experiment-table process-result-table"><thead><tr><th>{t('Date')}</th><th>{t('Sub-experiment')}</th>{group.results.map(result => <th key={result}>{result}</th>)}</tr></thead><tbody>{group.entries.map((run, runIndex) => <tr key={run.id} className={run.id === selected?.id ? 'selected' : undefined}><td className="process-experiment-date">{run.date || '—'}</td><td><button type="button" className="process-experiment-title" onClick={() => setSelectedId(run.id)}><b>{run.name}</b><small>{run.code} · {t('Experiment')} {run.method_run_number ?? runIndex + 1}</small></button></td>{group.results.map(result => { const value = run.results.find(item => item.key === result); return <td key={result}>{value ? `${value.value}${value.unit ? ` ${value.unit}` : ''}` : '—'}</td>; })}</tr>)}</tbody></table></div></section>}
        </details>)}
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
          const stageRuns = (selectedProcessGroup?.entries ?? [selected]).map(run => ({
            run,
            step: run.steps.find(item => item.order_index === step.order_index) ?? run.steps.find(item => item.name === step.name),
          }));
          return <article className="timeline-step card" key={step.id}>
            <div className="timeline-step-marker"><span>{index + 1}</span><small>{index === 0 ? t('Start') : index === orderedSteps.length - 1 ? t('Finish') : t('Step')}</small></div>
            <div className="timeline-step-content">
              <header className="timeline-step-head"><div><h3>{step.name}</h3>{step.description && <p>{step.description}</p>}</div><span className="timeline-step-count">{logs.length + images.length + step.variables.length + env.length} {t('records')}</span></header>
              <div className="timeline-step-grid">
                <section className="timeline-data-block timeline-stage-history"><h4>{t('Conditions and intermediate records')}</h4>{stageRuns.map(({ run, step: runStep }, runIndex) => {
                  const runLogs = (run.step_logs ?? []).filter(item => item.step_id === runStep?.id).sort((a, b) => a.occurred_at.localeCompare(b.occurred_at));
                  return <article className={`timeline-stage-date-entry ${run.id === selected.id ? 'current' : ''}`} key={run.id}>
                    <header><div><b>{run.date || t('Date not recorded')} · {run.name}</b><small>{run.code} · {t('Experiment')} {run.method_run_number ?? runIndex + 1}</small></div><span className={`status ${run.status}`}>{t(run.status.replace('_', ' '))}</span></header>
                    {runStep?.variables.length ? <div className="timeline-chips">{runStep.variables.map(variable => <span key={variable.id}><b>{variable.name}</b><strong>{variable.value} {variable.unit ?? ''}</strong></span>)}</div> : <small>{t('No process values recorded for this step.')}</small>}
                    {!!runLogs.length && <div className="timeline-stage-log-list">{runLogs.map(item => <div className="timeline-event-line" key={item.id}><Clock3 size={12}/><div><b>{item.label}{item.value && ` · ${item.value} ${item.unit ?? ''}`}</b><span>{new Date(item.occurred_at).toLocaleString()}</span>{item.notes && <small>{item.notes}</small>}</div>{run.id === selected.id && <button className="icon-button" title={t('Remove')} onClick={() => void removeLog(item.id)}><Trash2 size={13}/></button>}</div>)}</div>}
                  </article>;
                })}</section>
                <section className="timeline-data-block"><h4>{t('Environment')}</h4>{env.length ? env.map((item) => <div className="timeline-event-line" key={item.id}><Clock3 size={13}/><div><b>{t(item.phase)} · {new Date(item.measured_at).toLocaleString()}</b><span>{item.temperature_c != null && `${t('Ambient temperature')} ${item.temperature_c} °C`}{item.relative_humidity_percent != null && ` · ${t('Relative humidity')} ${item.relative_humidity_percent}%`}{item.pressure_kpa != null && ` · ${t('Ambient pressure')} ${item.pressure_kpa} kPa`}</span>{item.notes && <small>{item.notes}</small>}</div></div>) : <small>{t('No environment measurements recorded.')}</small>}</section>
              </div>
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
