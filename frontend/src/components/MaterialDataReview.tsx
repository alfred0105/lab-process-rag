import { useEffect, useMemo, useState } from 'react';
import { ExternalLink, FileSearch, FlaskConical, Search, Sparkles } from 'lucide-react';
import { api } from '../api/client';
import { getOpenfoamRun, listOpenfoamRuns, startOpenfoamRun } from '../api/client';
import { useLanguage } from '../language';
import type { AssistantResult, Experiment, PaperDiscoveryResult } from '../types';

type DraftInput = { name: string; value: string; unit: string; stepId: string };
const TOTAL_UNITS = ['mol/kgw', 'mol/kg', 'mol/L', 'mmol/L', 'mmol/kgw', 'mmol/kg'];
const FLOW_INPUTS: Record<string, { name: string; unitHint: string; text?: boolean }> = {
  liquid_volume: { name: 'liquid_volume', unitHint: 'L or mL' },
  vessel_geometry: { name: 'vessel_geometry', unitHint: '', text: true },
  impeller_geometry: { name: 'impeller_geometry', unitHint: '', text: true },
  stirring_speed: { name: 'stirring_speed', unitHint: 'rpm or s⁻¹' },
  fluid_density: { name: 'fluid_density', unitHint: 'kg/m³ or g/cm³' },
  fluid_viscosity: { name: 'fluid_viscosity', unitHint: 'Pa·s or mPa·s' },
};

function OpenfoamRunResult({ results, t }: { results: Record<string, unknown>; t: (key: string) => string }) {
  const trace = Array.isArray(results.power_trace) ? results.power_trace as { time_s: number; divStressU: number }[] : [];
  const values = trace.map(point => point.divStressU).filter(Number.isFinite);
  const minTime = Math.min(...trace.map(point => point.time_s), 0);
  const maxTime = Math.max(...trace.map(point => point.time_s), minTime + 1);
  const minValue = Math.min(...values, 0);
  const maxValue = Math.max(...values, minValue + 1);
  const points = trace.map(point => `${36 + (point.time_s - minTime) / (maxTime - minTime) * 568},${118 - (point.divStressU - minValue) / (maxValue - minValue) * 88}`).join(' ');
  const powerNumber = typeof results.power_number === 'number' ? results.power_number : null;
  return <div className="openfoam-run-result">
    <div className="openfoam-result-stats"><span><small>{t('OpenFOAM tutorial power number')}</small><b>{powerNumber === null ? t('Not reported') : powerNumber.toPrecision(4)}</b></span><span><small>{t('Solver output points')}</small><b>{trace.length}</b></span><span><small>{t('Mesh')}</small><b>{String(results.mesh_size ?? '—')}</b></span></div>
    {trace.length > 1 && <div className="openfoam-trace-wrap"><b>{t('Integrated impeller power term')} · divStressU</b><svg viewBox="0 0 640 150" role="img" aria-label={t('OpenFOAM power trace')}><line x1="36" y1="118" x2="604" y2="118"/><line x1="36" y1="24" x2="36" y2="118"/><polyline points={points}/>{trace.map(point => <circle key={point.time_s} cx={36 + (point.time_s - minTime) / (maxTime - minTime) * 568} cy={118 - (point.divStressU - minValue) / (maxValue - minValue) * 88} r="3"/>)}</svg><div className="openfoam-trace-labels"><span>{minTime} s</span><span>{maxTime} s</span></div></div>}
    <small>{Array.isArray(results.limits) ? results.limits.join(' · ') : ''}</small>
  </div>;
}

export default function MaterialDataReview({ experiments, onOpenExperiments, onDataChanged }: { experiments: Experiment[]; onOpenExperiments: () => void; onDataChanged: () => Promise<void> | void }) {
  const { t, language } = useLanguage();
  const runs = useMemo(() => experiments.filter(item => !item.demo && item.status !== 'planned'), [experiments]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const selected = runs.find(item => item.id === selectedId) ?? runs[0];
  const [materialQuery, setMaterialQuery] = useState('');
  const [lookups, setLookups] = useState<{ query: string; result: Awaited<ReturnType<typeof api.lookupMaterial>> }[]>([]);
  const [paperSearches, setPaperSearches] = useState<PaperDiscoveryResult[]>([]);
  const [review, setReview] = useState<AssistantResult | null>(null);
  const [readiness, setReadiness] = useState<Awaited<ReturnType<typeof api.simulationInputs>> | null>(null);
  const [openfoamPlan, setOpenfoamPlan] = useState<Awaited<ReturnType<typeof api.openfoamPlan>> | null>(null);
  const [openfoamRuns, setOpenfoamRuns] = useState<Awaited<ReturnType<typeof listOpenfoamRuns>>>([]);
  const [startingOpenfoam, setStartingOpenfoam] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, DraftInput>>({});
  const [totalRows, setTotalRows] = useState([0]);
  const [aqueousRequested, setAqueousRequested] = useState(false);
  const [mixerRequested, setMixerRequested] = useState(false);
  const [savingInputs, setSavingInputs] = useState(false);
  const [savedMessage, setSavedMessage] = useState('');
  const [materialDraft, setMaterialDraft] = useState({ name: '', amount: '', unit: '', role: '', supplier: '', lot_number: '' });
  const [savingMaterial, setSavingMaterial] = useState(false);
  const [busy, setBusy] = useState<'lookup' | 'papers' | 'gemma' | ''>('');
  const [error, setError] = useState('');

  useEffect(() => {
    setLookups([]); setPaperSearches([]); setReview(null); setReadiness(null); setOpenfoamPlan(null); setOpenfoamRuns([]); setError(''); setDrafts({}); setTotalRows([0]); setAqueousRequested(false); setMixerRequested(false); setSavedMessage(''); setMaterialDraft({ name: '', amount: '', unit: '', role: '', supplier: '', lot_number: '' });
    setMaterialQuery(selected?.materials[0]?.name ?? '');
    if (selected) {
      void api.simulationInputs(selected.id).then(setReadiness).catch(cause => setError(t(cause instanceof Error ? cause.message : String(cause))));
      void api.openfoamPlan(selected.id).then(setOpenfoamPlan).catch(cause => setError(t(cause instanceof Error ? cause.message : String(cause))));
      void listOpenfoamRuns(selected.id).then(setOpenfoamRuns).catch(cause => setError(t(cause instanceof Error ? cause.message : String(cause))));
    }
  }, [selected?.id]);

  useEffect(() => {
    if (!selected || !openfoamRuns.some(item => item.status === 'queued' || item.status === 'running')) return;
    const timer = window.setInterval(() => {
      const active = openfoamRuns.filter(item => item.status === 'queued' || item.status === 'running');
      void Promise.all(active.map(item => getOpenfoamRun(item.id))).then(updated => setOpenfoamRuns(current => current.map(item => updated.find(next => next.id === item.id) ?? item)));
    }, 2500);
    return () => window.clearInterval(timer);
  }, [selected?.id, openfoamRuns]);

  const runOpenfoam = async () => {
    if (!selected || startingOpenfoam) return;
    setStartingOpenfoam(true); setError('');
    try { const created = await startOpenfoamRun(selected.id); setOpenfoamRuns(current => [created, ...current]); }
    catch (cause) { setError(t(cause instanceof Error ? cause.message : String(cause))); }
    finally { setStartingOpenfoam(false); }
  };

  const lookupMaterial = async () => {
    const query = materialQuery.trim();
    if (query.length < 2 || busy) return;
    setBusy('lookup'); setError('');
    try {
      const result = await api.lookupMaterial(query);
      setLookups(current => [...current.filter(item => item.query.toLowerCase() !== query.toLowerCase()), { query, result }]);
    }
    catch (cause) { setError(t(cause instanceof Error ? cause.message : String(cause))); }
    finally { setBusy(''); }
  };

  const findPapers = async () => {
    if (busy) return;
    const terms = [materialQuery.trim(), selected?.method_name ?? selected?.target ?? '', selected?.name ?? ''].filter(Boolean).join(' ');
    if (terms.length < 3) return;
    setBusy('papers'); setError('');
    try {
      const result = await api.discoverPapers(terms);
      setPaperSearches(current => [...current.filter(item => item.query !== result.query), result]);
    }
    catch (cause) { setError(t(cause instanceof Error ? cause.message : String(cause))); }
    finally { setBusy(''); }
  };

  const askGemma = async () => {
    if (!selected || busy) return;
    setBusy('gemma'); setError(''); setReview(null);
    try {
      const inputReadiness = readiness ?? await api.simulationInputs(selected.id);
      setReadiness(inputReadiness);
      const answer = await api.simulationInputReview(selected.id, language);
      setReview(answer);
      // Search only when Gemma reports a source gap. Keep each source result linked
      // to its query; PubChem identity properties are never treated as lot data.
      const gapText = answer.evidence_gaps.map(gap => `${gap.need} ${gap.why_needed}`).join(' ').toLowerCase();
      const needsMaterialLookup = /material|reagent|chemical|compound|시약|시료|화학물질|물성|밀도|점도/.test(gapText);
      const materialQueries = needsMaterialLookup
        ? [...new Set(selected.materials.map(item => item.name.trim()).filter(Boolean))].slice(0, 4)
        : [];
      const paperQueries = [...new Set(answer.evidence_gaps.flatMap(gap => gap.search_queries).map(term => term.trim()).filter(term => term.length >= 3))].slice(0, 2);
      const [materialResults, paperResults] = await Promise.all([
        Promise.allSettled(materialQueries.map(query => api.lookupMaterial(query))),
        Promise.allSettled(paperQueries.map(query => api.discoverPapers(query))),
      ]);
      const fetchedMaterials = materialResults.flatMap((result, index) => result.status === 'fulfilled' ? [{ query: materialQueries[index], result: result.value }] : []);
      const fetchedPapers = paperResults.flatMap(result => result.status === 'fulfilled' ? [result.value] : []);
      setLookups(current => {
        const next = new Map(current.map(item => [item.query.toLowerCase(), item]));
        fetchedMaterials.forEach(item => next.set(item.query.toLowerCase(), item));
        return [...next.values()];
      });
      setPaperSearches(current => {
        const next = new Map(current.map(item => [item.query, item]));
        fetchedPapers.forEach(item => next.set(item.query, item));
        return [...next.values()];
      });
    }
    catch (cause) { setError(t(cause instanceof Error ? cause.message : String(cause))); }
    finally { setBusy(''); }
  };

  const setInput = (key: string, defaults: Omit<DraftInput, 'value'>, patch: Partial<DraftInput>) => {
    setDrafts(current => {
      const previous = current[key];
      return { ...current, [key]: {
        name: patch.name ?? previous?.name ?? defaults.name,
        value: patch.value ?? previous?.value ?? '',
        unit: patch.unit ?? previous?.unit ?? defaults.unit,
        stepId: patch.stepId ?? previous?.stepId ?? defaults.stepId,
      } };
    });
    setSavedMessage('');
  };

  const saveKnownInputs = async () => {
    if (!selected || !readiness || savingInputs) return;
    const entries = Object.entries(drafts).filter(([, item]) => item.value.trim() && item.stepId && item.name.trim());
    if (!entries.length) return;
    setSavingInputs(true); setError(''); setSavedMessage('');
    try {
      for (const [, item] of entries) {
        await api.addProcessVariable(selected.id, Number(item.stepId), { name: item.name.trim(), value: item.value.trim(), unit: item.unit.trim() || undefined });
      }
      setReadiness(await api.simulationInputs(selected.id));
      setOpenfoamPlan(await api.openfoamPlan(selected.id));
      setDrafts({}); setSavedMessage(t('Known values were added to the selected process step.'));
      await onDataChanged();
    } catch (cause) { setError(t(cause instanceof Error ? cause.message : String(cause))); }
    finally { setSavingInputs(false); }
  };

  const saveMaterial = async () => {
    if (!selected || !materialDraft.name.trim() || savingMaterial) return;
    setSavingMaterial(true); setError(''); setSavedMessage('');
    try {
      await api.addExperimentMaterial(selected.id, materialDraft);
      setMaterialDraft({ name: '', amount: '', unit: '', role: '', supplier: '', lot_number: '' });
      setReadiness(await api.simulationInputs(selected.id));
      setSavedMessage(t('Material was added to this experiment record.'));
      await onDataChanged();
    } catch (cause) { setError(t(cause instanceof Error ? cause.message : String(cause))); }
    finally { setSavingMaterial(false); }
  };

  const renderConditionField = (key: string, title: string, name: string, unitHint: string, text = false) => {
    if (!selected?.steps.length) return null;
    const isTotal = key.startsWith('dissolved_total');
    const defaults = { name, unit: name === 'temperature_C' ? '°C' : '', stepId: String(selected.steps[0].id) };
    const draft = drafts[key];
    const item: DraftInput = {
      name: draft?.name ?? defaults.name,
      value: draft?.value ?? '',
      unit: draft?.unit ?? defaults.unit,
      stepId: draft?.stepId ?? defaults.stepId,
    };
    return <div className="simulation-input-row" key={key}>
      <div className="simulation-input-label"><b>{t(title)}</b>{text && <small>{t(key === 'vessel_geometry' ? 'For the Rushton case: cylindrical; diameter [measured] mm; height [measured] mm; baffled; closed and fully filled.' : 'For the Rushton case: Rushton turbine; blade count [measured 4 or 6]; diameter [measured] mm.')}</small>}</div>
      <select aria-label={`${t(title)} ${t('process step')}`} value={item.stepId} onChange={event => setInput(key, defaults, { stepId: event.target.value })}>{selected.steps.map(step => <option key={step.id} value={step.id}>{step.order_index + 1}. {step.name}</option>)}</select>
      {isTotal && <input value={item.name === 'dissolved_total' ? '' : item.name} onChange={event => setInput(key, defaults, { name: event.target.value })} placeholder={t('Element variable e.g. Zn_concentration')}/>}
      <input value={item.value} onChange={event => setInput(key, defaults, { value: event.target.value })} placeholder={t('Known value only; leave blank if unknown')}/>
      {isTotal ? <select aria-label={t('Concentration unit')} value={item.unit} onChange={event => setInput(key, defaults, { unit: event.target.value })}><option value="">{t('Choose unit')}</option>{TOTAL_UNITS.map(unit => <option key={unit}>{unit}</option>)}</select> : key === 'pH' ? <span className="simulation-unit-hint">{t('No unit')}</span> : text ? <span className="simulation-unit-hint">{t('Include units in the description when relevant')}</span> : <input value={item.unit} onChange={event => setInput(key, defaults, { unit: event.target.value })} placeholder={unitHint || t('Unit')}/>}
    </div>;
  };

  const phreeqcChecks = readiness?.groups.find(group => group.key === 'phreeqc')?.checks ?? [];
  const openfoamChecks = readiness?.groups.find(group => group.key === 'openfoam_mixer')?.checks ?? [];
  const materialCheck = readiness?.groups.find(group => group.key === 'materials')?.checks.find(check => check.key === 'material_identity');
  const hasPendingCondition = Object.values(drafts).some(item => item.value.trim() && item.stepId);

  return <section className="card material-data-review">
    <div className="card-head"><div><div className="card-title"><FileSearch size={16}/>{t('Input data and trusted sources')}</div><div className="card-sub">{t('Ask Gemma to identify missing inputs for a selected run, then look up general chemical identity data or related paper records.')}</div></div><span className="simulation-state-pill partial-pill">{t('Reference only')}</span></div>
    {selected ? <>
      <label className="process-simulation-source">{t('Source experiment')}<select value={selected.id} onChange={event => setSelectedId(Number(event.target.value))}>{runs.map(item => <option key={item.id} value={item.id}>{item.code} · {item.name} · {item.method_name ?? item.target}</option>)}</select></label>
      {readiness && <div className="input-readiness-report"><div className="input-readiness-head"><b>{t('Saved input check')} · {readiness.record_code}</b><button type="button" className="text-button" onClick={onOpenExperiments}>{t('Edit process record')}</button></div>{readiness.groups.map(group => <section key={group.key}><b>{t(group.key === 'phreeqc' ? 'PHREEQC aqueous inputs' : group.key === 'openfoam_mixer' ? 'OpenFOAM mixer inputs' : 'Material information')}{group.conditional && <small>{t(group.key === 'phreeqc' ? 'Only if running aqueous equilibrium' : 'Only if modelling a stirred liquid')}</small>}</b><div className="input-readiness-items">{group.checks.map(check => <span key={check.key} className={check.present ? 'present' : 'absent'}><i/>{t(check.key)}{check.present && check.value ? ` · ${check.value}${check.unit ? ` ${check.unit}` : ''}` : check.reason === 'recorded_but_not_usable' ? ` · ${check.recorded_value ?? ''}${check.recorded_unit ? ` ${check.recorded_unit}` : ''} · ${t('Recorded but needs review')}` : ` · ${check.required ? t('missing') : t('optional')}`}</span>)}</div></section>)}{readiness.limitations.map(item => <small className="input-readiness-limit" key={item}>{t(item)}</small>)}{openfoamPlan && <section className="openfoam-case-plan"><b>{t('OpenFOAM case compatibility')} · {openfoamPlan.model_id}</b><small className={`openfoam-plan-status ${openfoamPlan.status}`}>{t(openfoamPlan.status)}</small><div className="input-readiness-items">{openfoamPlan.checks.map(check => <span key={check.key} className={check.present ? 'present' : 'absent'}><i/>{t(check.key)}{check.present && check.value_si !== null && check.value_si !== undefined ? ` · ${typeof check.value_si === 'number' ? Number(check.value_si.toPrecision(4)) : check.value_si}${check.unit_si ? ` ${check.unit_si}` : ''}` : ` · ${t('missing')}`}</span>)}</div><div className="openfoam-run-control"><p>{t('This runs a local OpenFOAM 14 CFD case. It creates a separate simulation record and does not change measured results.')}</p><button className="button primary small" disabled={openfoamPlan.status !== 'ready_for_review' || startingOpenfoam || openfoamRuns.some(item => item.status === 'queued' || item.status === 'running')} onClick={() => void runOpenfoam()}>{startingOpenfoam ? t('Starting…') : t('Run local CFD simulation')}</button></div>{openfoamRuns.map(item => <article className="openfoam-run-card" key={item.id}><b>#{item.id} · {t(item.status)}</b>{item.error && <p className="error">{item.error}</p>}{item.results && <OpenfoamRunResult results={item.results} t={t}/>}{item.log && <details><summary>{t('Solver log')}</summary><pre>{item.log}</pre></details>}</article>)}{openfoamPlan.unsupported_reasons?.map(item => <small className="input-readiness-limit" key={item}>{t(item)}</small>)}{openfoamPlan.limitations.map(item => <small className="input-readiness-limit" key={item}>{t(item)}</small>)}</section>}</div>}
      {readiness && selected.steps.length > 0 && <section className="simulation-input-capture">
        <div className="simulation-input-capture-head"><div><b>{t('Provide values you know')}</b><small>{t('Saved as new process conditions on the step you select. Existing values are never replaced; unknown fields can stay blank.')}</small></div></div>
        {phreeqcChecks.some(check => !check.present) && <div className="simulation-input-mode"><label><input type="checkbox" checked={aqueousRequested} onChange={event => setAqueousRequested(event.target.checked)}/><span><b>{t('I want to run aqueous-equilibrium calculation')}</b><small>{t('Only enter values you have from the experiment or an applicable source.')}</small></span></label>{aqueousRequested && <div className="simulation-input-fields">
          {!phreeqcChecks.find(check => check.key === 'pH')?.present && renderConditionField('pH', 'pH', 'pH', '')}
          {!phreeqcChecks.find(check => check.key === 'temperature')?.present && renderConditionField('temperature', 'Temperature', 'temperature_C', '°C')}
          {!phreeqcChecks.find(check => check.key === 'dissolved_total')?.present && <>{totalRows.map(row => renderConditionField(`dissolved_total_${row}`, 'Dissolved element total', 'dissolved_total', ''))}<button type="button" className="text-button" onClick={() => setTotalRows(current => [...current, Math.max(...current, -1) + 1])}>{t('Add another element')}</button></>}
        </div>}</div>}
        {openfoamChecks.some(check => !check.present) && <div className="simulation-input-mode"><label><input type="checkbox" checked={mixerRequested} onChange={event => setMixerRequested(event.target.checked)}/><span><b>{t('I want to model a mechanically stirred liquid')}</b><small>{t('These fields are needed only for that model. Geometry and fluid properties are not guessed.')}</small></span></label>{mixerRequested && <div className="simulation-input-fields">{openfoamChecks.filter(check => !check.present).map(check => {const spec=FLOW_INPUTS[check.key];return spec?renderConditionField(check.key,t(check.key),spec.name,spec.unitHint,Boolean(spec.text)):null})}</div>}</div>}
        {materialCheck && !materialCheck.present && <form className="simulation-material-capture" onSubmit={event=>{event.preventDefault();void saveMaterial()}}><b>{t('Record exact materials used')}</b><small>{t('Use the reagent label or source record. Enter known amounts; supplier and lot can stay blank when unknown.')}</small><div><input required value={materialDraft.name} onChange={event=>setMaterialDraft(current=>({...current,name:event.target.value}))} placeholder={t('Exact material name / chemical form')}/><input value={materialDraft.amount} onChange={event=>setMaterialDraft(current=>({...current,amount:event.target.value}))} placeholder={t('Amount if known')}/><input value={materialDraft.unit} onChange={event=>setMaterialDraft(current=>({...current,unit:event.target.value}))} placeholder={t('Unit if known')}/><input value={materialDraft.role} onChange={event=>setMaterialDraft(current=>({...current,role:event.target.value}))} placeholder={t('Purpose / role if known')}/><input value={materialDraft.supplier} onChange={event=>setMaterialDraft(current=>({...current,supplier:event.target.value}))} placeholder={t('Supplier if known')}/><input value={materialDraft.lot_number} onChange={event=>setMaterialDraft(current=>({...current,lot_number:event.target.value}))} placeholder={t('Lot / batch if known')}/><button className="button outline small" disabled={savingMaterial}>{savingMaterial?t('Saving…'):t('Add material to this run')}</button></div></form>}
        {hasPendingCondition && <button type="button" className="button primary small" disabled={savingInputs} onClick={()=>void saveKnownInputs()}>{savingInputs?t('Saving…'):t('Save known process values')}</button>}
        {savedMessage&&<p className="simulation-input-saved">{savedMessage}</p>}
      </section>}
      <div className="material-review-actions"><button className="button primary small" type="button" disabled={busy !== ''} onClick={() => void askGemma()}><Sparkles size={14}/>{busy === 'gemma' ? t('Gemma is checking…') : t('Ask Gemma what is missing')}</button><small>{t('The review uses this run’s recorded conditions and materials. It does not fill missing values.')}</small></div>
      {review && <div className="material-gemma-review"><b>{t('Gemma input review')} · {review.model}</b>{review.claims.map((claim, index) => <article key={`${index}-${claim.claim}`}><span className={`badge ${claim.status.toLowerCase()}`}>{t(claim.status === 'MODEL_KNOWLEDGE' ? 'GEMMA KNOWLEDGE' : claim.status)}</span><p>{claim.claim}</p>{claim.evidence_ids.length > 0 && <small>{t('Evidence IDs:')} {claim.evidence_ids.join(', ')}</small>}</article>)}{review.evidence_gaps.map((gap, index) => <article className="material-gap" key={`${index}-${gap.need}`}><b>{gap.need}</b><p>{gap.why_needed}</p></article>)}</div>}
      <div className="material-reference-search"><div className="material-reference-title"><FlaskConical size={15}/><b>{t('Look up a chemical identity')}</b><small>{t('Formula and molecular weight can help identify a compound; they do not provide batch or solution data.')}</small></div>
        <div className="paper-search-row"><input value={materialQuery} onChange={event => setMaterialQuery(event.target.value)} aria-label={t('Chemical name or formula')} placeholder={t('Chemical name, formula, or CAS number')}/><button className="button outline" type="button" disabled={busy !== '' || materialQuery.trim().length < 2} onClick={() => void lookupMaterial()}><Search size={14}/>{busy === 'lookup' ? t('Searching…') : t('Search PubChem')}</button></div>
      {lookups.map(({ query, result }) => <div className="material-lookup-results" key={query}>
        <small>{t('Candidate records for')} {query} · {result.provider}</small>
        {result.candidates.length ? result.candidates.map(item => <article className="material-source-card" key={item.cid}>
          <div><b>{item.name}</b><small>{t('CID')} {item.cid} · {t('Formula')} {item.formula ?? '—'} · {t('Molecular weight')} {item.molecular_weight_g_mol ?? '—'} g/mol</small>{item.inchikey && <small>InChIKey · {item.inchikey}</small>}</div>
          <a href={item.source_url} target="_blank" rel="noreferrer">{t('Open PubChem record')} <ExternalLink size={12}/></a>
        </article>) : <p>{t('No candidate identity was found. Check the exact name, salt, hydrate, or CAS number; leave it blank if unknown.')}</p>}
        {result.limitations.map(item => <small className="material-source-limit" key={item}>{t(item)}</small>)}
        <div className="material-nist-record"><b>{t('NIST Chemistry WebBook')}</b>{result.nist.status === 'record_found' ? <><span>{result.nist.title}</span>{result.nist.available_data.length > 0 && <small>{t('Available NIST data sections')}: {result.nist.available_data.map(item => t(item)).join(' · ')}</small>}</> : <small>{t(result.nist.status === 'unavailable' ? 'NIST lookup is unavailable right now.' : 'No matching NIST record was found.')}</small>}<a className="material-nist-link" href={result.nist.source_url || result.additional_source_url} target="_blank" rel="noreferrer">{t('Open NIST source record')} <ExternalLink size={12}/></a></div>
      </div>)}
      </div>
      <div className="material-paper-search"><div><b>{t('Find related research papers')}</b><small>{t('Crossref returns scholarly metadata; a paper’s contents are not added as evidence until its full text is indexed.')}</small></div><button className="button outline small" type="button" disabled={busy !== '' || !materialQuery.trim()} onClick={() => void findPapers()}><Search size={13}/>{busy === 'papers' ? t('Searching…') : t('Search related papers')}</button></div>
      {paperSearches.map(paperSearch => <div className="discovery-results" key={paperSearch.query}><small>{paperSearch.results.length} {t('records from Crossref')} · {paperSearch.query}</small>{paperSearch.results.map(item => <article className="discovery-card" key={item.doi ?? item.title}><b>{item.title}</b><small>{item.authors.join(', ')}{item.year ? ` · ${item.year}` : ''}{item.journal ? ` · ${item.journal}` : ''}</small>{item.doi_url && <a href={item.doi_url} target="_blank" rel="noreferrer">{t('Open DOI')} <ExternalLink size={12}/></a>}</article>)}</div>)}
    </> : <div className="empty-hint">{t('No non-demo experiment record is available to review.')}</div>}
    {error && <div className="error" role="alert">{error}</div>}
  </section>;
}
