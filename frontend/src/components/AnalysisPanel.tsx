import { useEffect, useMemo, useState } from 'react';
import { Activity, ExternalLink, FileImage, Plus } from 'lucide-react';
import { api } from '../api/client';
import type { AIStatus, AnalysisRun, AnalysisTools, Experiment, IntegratedAnalysisHistory, IntegratedAnalysisResult } from '../types';
import { useLanguage } from '../language';

type AdjustmentTarget = { key: string; label: string; kind: 'variable' | 'material'; value: string; unit: string; stepIndex?: number; variableIndex?: number; materialIndex?: number };
type ProcessGroup={key:string;name:string;target:string;experiments:Experiment[]};
function processStructureSignature(experiment:Experiment){return JSON.stringify([...experiment.steps].sort((a,b)=>a.order_index-b.order_index).map(step=>[step.order_index,step.name.trim().toLocaleLowerCase(),step.step_type,(step.description??'').trim().toLocaleLowerCase()]));}
function processGroupsFor(experiments:Experiment[]):ProcessGroup[]{const groups=new Map<string,ProcessGroup>();for(const experiment of experiments){const key=JSON.stringify([experiment.target,experiment.method_name??'',processStructureSignature(experiment)]);let group=groups.get(key);if(!group){group={key,name:experiment.method_name||experiment.target,target:experiment.target,experiments:[]};groups.set(key,group);}group.experiments.push(experiment);}return [...groups.values()].map(group=>({...group,experiments:[...group.experiments].sort((a,b)=>(a.date??'').localeCompare(b.date??'')||a.id-b.id)}));}

type HistoricalGuidance = { sampleSize:number; successes:number; failures:number; excludedOutcomes:number; successRate:number|null; interval:[number,number]|null; reference:Experiment|null; processVariantCount:number; processVariantExamples:string[]; changedConditions:{label:string;current:string;observed:string;unit:string;successMatches:number;failureMatches:number}[] };
function wilsonInterval(successes:number,total:number):[number,number] { const z=1.96;const p=successes/total;const denominator=1+z*z/total;const center=(p+z*z/(2*total))/denominator;const margin=z*Math.sqrt((p*(1-p)+z*z/(4*total))/total)/denominator;return [Math.max(0,(center-margin)*100),Math.min(100,(center+margin)*100)]; }
function historicalGuidanceFor(base:Experiment,pool:Experiment[]):HistoricalGuidance {
  const processSignature=processStructureSignature;
  const sameConcept=(item:Experiment)=>item.id!==base.id&&item.target===base.target&&item.method_name===base.method_name;
  const signature=processSignature(base);
  // A process recipe is the ordered sequence of named step types. Method-version
  // edits that keep this structure remain comparable; changed routes are held apart.
  const sameMethod=pool.filter(item=>sameConcept(item)&&processSignature(item)===signature);
  const processVariants=pool.filter(item=>sameConcept(item)&&processSignature(item)!==signature);
  const terminal=sameMethod.filter(item=>item.status==='success'||item.status==='failure');const successes=terminal.filter(item=>item.status==='success').length;const failures=terminal.length-successes;
  const values=(experiment:Experiment)=>new Map(experiment.steps.flatMap(step=>step.variables.map(variable=>[variable.name,{value:variable.value,unit:variable.unit??'',label:`${step.name} · ${variable.name}`}] as const)));
  const baseValues=values(base);const successful=sameMethod.filter(item=>item.status==='success');
  const ranked=successful.map(experiment=>{const candidateValues=values(experiment);let changes=0;for(const [name,current] of baseValues){const observed=candidateValues.get(name);if(!observed||observed.value!==current.value||observed.unit!==current.unit)changes+=1;}changes+=Math.max(0,candidateValues.size-baseValues.size);return {experiment,changes};}).sort((a,b)=>a.changes-b.changes||a.experiment.id-b.experiment.id);
  const reference=ranked[0]?.experiment??null;const referenceValues=reference?values(reference):new Map();
  const changedConditions=reference?[...referenceValues].flatMap(([name,observed])=>{const current=baseValues.get(name);if(current&&current.value===observed.value&&current.unit===observed.unit)return [];const matching=terminal.filter(item=>values(item).get(name)?.value===observed.value&&values(item).get(name)?.unit===observed.unit);return [{label:observed.label,current:current?.value??'—',observed:observed.value,unit:observed.unit,successMatches:matching.filter(item=>item.status==='success').length,failureMatches:matching.filter(item=>item.status==='failure').length}];}):[];
  if(reference){const referenceMaterials=new Map(reference.materials.map(item=>[item.name,{amount:item.amount,unit:item.unit??'',label:`${item.name} · ${item.role||'material amount'}`} ]));for(const [name,observed] of referenceMaterials){const current=base.materials.find(item=>item.name===name);if(current&&current.amount===observed.amount&&current.unit===observed.unit)continue;const matching=terminal.filter(item=>{const material=item.materials.find(entry=>entry.name===name);return material?.amount===observed.amount&&(material?.unit??'')===observed.unit;});changedConditions.push({label:observed.label,current:current?.amount??'—',observed:observed.amount,unit:observed.unit,successMatches:matching.filter(item=>item.status==='success').length,failureMatches:matching.filter(item=>item.status==='failure').length});}}
  return {sampleSize:terminal.length,successes,failures,excludedOutcomes:sameMethod.length-terminal.length,successRate:terminal.length?successes/terminal.length*100:null,interval:terminal.length?wilsonInterval(successes,terminal.length):null,reference,processVariantCount:processVariants.length,processVariantExamples:processVariants.slice(0,3).map(item=>`${item.code} · ${item.name}`),changedConditions};
}

export default function AnalysisPanel({ experiments, topicId, onExperimentCreated, onOpenMethods }: { experiments: Experiment[]; topicId: number; onExperimentCreated?: () => void; onOpenMethods?: () => void }) {
  const { t, language } = useLanguage();
  const [tools, setTools] = useState<AnalysisTools | null>(null);
  const [ai, setAi] = useState<AIStatus | null>(null);
  const [runs, setRuns] = useState<AnalysisRun[]>([]);
  const [integratedHistory, setIntegratedHistory] = useState<IntegratedAnalysisHistory[]>([]);
  const [experimentId, setExperimentId] = useState('');
  const [error, setError] = useState('');
  const [result, setResult] = useState<AnalysisRun | null>(null);
  const [goal, setGoal] = useState(() => language === 'ko' ? '이 연구 주제의 모든 실험 기록과 분석 완료 측정을 종합해줘. 같은 공정 안의 조건 차이와 공정 버전 간 차이를 구분하고, 확인된 관찰·논문 근거·불확실성·추가로 필요한 측정을 정리해줘. 근거 없이 원인이나 다음 조건을 단정하지 마.' : 'Synthesize all experiment records and completed measurements in this research topic. Separate condition changes within the same process from differences between process versions, and summarize observations, paper evidence, uncertainty, and additional measurements needed. Do not assert causes or next settings without evidence.');
  const [allowGeneralKnowledge, setAllowGeneralKnowledge] = useState(true);
  const [integrating, setIntegrating] = useState(false);
  const [integrated, setIntegrated] = useState<IntegratedAnalysisResult | null>(null);
  const [draftTarget, setDraftTarget] = useState('');
  const [draftValue, setDraftValue] = useState('');
  const [savingDraft, setSavingDraft] = useState(false);
  const [draftMessage, setDraftMessage] = useState('');

  const processGroups = useMemo(()=>processGroupsFor(experiments),[experiments]);
  const topicAnalysisRuns = runs;
  const completedTopicRuns = topicAnalysisRuns.filter(run => run.analysis_status === 'completed');
  const baseExperiment = experiments.find(item => item.id === Number(experimentId));
  const adjustmentTargets: AdjustmentTarget[] = baseExperiment ? [
    ...baseExperiment.steps.flatMap((step, stepIndex) => step.variables.map((variable, variableIndex) => ({ key: `v:${stepIndex}:${variableIndex}`, label: `${step.name} · ${variable.name}`, kind: 'variable' as const, value: variable.value, unit: variable.unit ?? '', stepIndex, variableIndex }))),
    ...baseExperiment.materials.map((material, materialIndex) => ({ key: `m:${materialIndex}`, label: `${material.name} · ${t('sample amount')}`, kind: 'material' as const, value: material.amount, unit: material.unit ?? '', materialIndex })),
  ] : [];
  const activeTarget = adjustmentTargets.find(item => item.key === draftTarget);
  const historicalGuidance = baseExperiment ? historicalGuidanceFor(baseExperiment, experiments) : null;
  const refresh = async () => {
    try {
      const [catalog, history, status, reports] = await Promise.all([api.analysisTools(), api.analysisRuns(topicId), api.aiStatus(), api.integratedAnalysisHistory(topicId)]);
      setTools(catalog); setRuns(history); setAi(status); setIntegratedHistory(reports);
    } catch (cause) { setError(String(cause)); }
  };
  useEffect(() => { void refresh(); }, [topicId]);
  useEffect(()=>{if(!experiments.some(item=>item.id===Number(experimentId)))setExperimentId(String(experiments[0]?.id??''));},[experiments]);
  useEffect(()=>{if(baseExperiment&&!draftTarget){const first=[...baseExperiment.steps.flatMap((step,stepIndex)=>step.variables.map((variable,variableIndex)=>({key:`v:${stepIndex}:${variableIndex}`,value:variable.value}))),...baseExperiment.materials.map((material,materialIndex)=>({key:`m:${materialIndex}`,value:material.amount}))][0];if(first){setDraftTarget(first.key);setDraftValue(first.value);}}},[baseExperiment?.id]);
  const integrateTopic = async () => {
    const runIds = completedTopicRuns.map(run => run.id);
    if ((!runIds.length&&!experiments.length) || integrating) return;
    setIntegrating(true); setError(''); setIntegrated(null); setDraftMessage('');
    try {
      const report = await api.integrateAnalysis({ analysis_run_ids: runIds, experiment_ids: experiments.map(item=>item.id), goal: goal.trim() || t('Synthesize all completed measurements and experiment records in this research topic. Compare process variants separately and describe evidence gaps.'), allow_general_knowledge: allowGeneralKnowledge });
      setIntegrated(report);
      await refresh();
    } catch (cause) { setError(String(cause)); }
    finally { setIntegrating(false); }
  };

  const setBaseExperiment = (value:string) => {
    setExperimentId(value); setDraftMessage('');
    const next=experiments.find(item=>item.id===Number(value));
    const first=next?[...next.steps.flatMap((step,stepIndex)=>step.variables.map((variable,variableIndex)=>({key:`v:${stepIndex}:${variableIndex}`,value:variable.value}))),...next.materials.map((material,materialIndex)=>({key:`m:${materialIndex}`,value:material.amount}))][0]:undefined;
    setDraftTarget(first?.key??'');setDraftValue(first?.value??'');
  };

  const saveNextExperiment = async () => {
    if (!baseExperiment || !activeTarget || !draftValue.trim() || !integrated || savingDraft) return;
    setSavingDraft(true); setError(''); setDraftMessage('');
    const steps = baseExperiment.steps.map((step, stepIndex) => ({
      name: step.name, step_type: step.step_type, order_index: step.order_index, description: step.description,
      variables: step.variables.map((variable, variableIndex) => ({
        name: variable.name,
        value: activeTarget.kind === 'variable' && activeTarget.stepIndex === stepIndex && activeTarget.variableIndex === variableIndex ? draftValue.trim() : variable.value,
        unit: variable.unit ?? null, material: variable.material ?? null, source_type: 'lab',
      })),
    }));
    const materials = baseExperiment.materials.map((material, materialIndex) => ({
      name: material.name, amount: activeTarget.kind === 'material' && activeTarget.materialIndex === materialIndex ? draftValue.trim() : material.amount,
      unit: material.unit ?? null, role: material.role, lot_number: material.lot_number, supplier: material.supplier,
    }));
    const change = `${activeTarget.label}: ${draftValue.trim()} ${activeTarget.unit}`.trim();
    try {
      const created = await api.create({
        name: `${baseExperiment.name} · ${t('analysis follow-up')}`, target: baseExperiment.target, status: 'planned', demo: false,
        topic_id: topicId, method_version_id: baseExperiment.method_version_id,
        notes: `${t('Created from integrated instrument review')}. ${t('Researcher-selected change')}: ${change}. ${t('The change is a candidate to test, not a verified cause or recommendation')}. Analysis run IDs: ${integrated.measurements.map(item => item.analysis_run_id).join(', ')}.`,
        steps, materials, results: [], observations: [],
      });
      setDraftMessage(`${t('Saved as planned experiment')}: ${created.code} · ${created.name}`);
      onExperimentCreated?.();
    } catch (cause) { setError(String(cause)); }
    finally { setSavingDraft(false); }
  };

  const resultData = result?.result ?? {};
  const analysisProcessName=(run:AnalysisRun)=>{const experiment=experiments.find(item=>item.id===run.experiment_id);if(!experiment)return t('Unlinked measurement');return processGroups.find(group=>group.experiments.some(item=>item.id===experiment.id))?.name??experiment.target;};

  return <div className="analysis-layout">
    <section className="card process-analysis-overview"><div className="card-head"><div><div className="card-title">{t('Research topic overview')}</div><div className="card-sub">{t('Build this research topic through separate experiments and process versions. When the records are ready, synthesize the whole topic at the end.')}</div></div><span className="history-tag">{experiments.length} {t('experiments in this topic')}</span></div>
      <div className="process-analysis-stats"><span><b>{experiments.length}</b>{t('experiments')}</span><span><b>{processGroups.length}</b>{t('process versions')}</span><span><b>{experiments.filter(item=>item.status==='success').length}</b>{t('success')}</span><span><b>{experiments.filter(item=>item.status==='failure').length}</b>{t('failure')}</span><span><b>{topicAnalysisRuns.length}</b>{t('measurements')}</span></div>
      {processGroups.length?<div className="topic-process-groups">{processGroups.map(group=><details className="topic-process-group" key={group.key}><summary><span><b>{group.name}</b><small>{group.target}</small></span><em>{group.experiments.length} {t('experiments')} · {topicAnalysisRuns.filter(run=>group.experiments.some(item=>item.id===run.experiment_id)).length} {t('measurements')}</em></summary><div className="process-run-rail">{group.experiments.map((item,index)=><button type="button" className={`process-run-chip ${item.id===Number(experimentId)?'active':''}`} key={item.id} onClick={()=>setBaseExperiment(String(item.id))}><b>{t('Experiment')} {item.method_run_number??index+1}</b><strong>{item.name}</strong><small>{item.date||t('Date not recorded')} · {t(item.status)}</small><span>{item.results.length} {t('recorded results')} · {topicAnalysisRuns.filter(run=>run.experiment_id===item.id).length} {t('analyses')}</span>{!!item.results.length&&<span className="process-run-result-values">{item.results.slice(0,4).map(result=>`${result.key}: ${result.value}${result.unit?` ${result.unit}`:''}`).join(' · ')}</span>}</button>)}</div></details>)}</div>:<div className="empty-hint">{t('Record experiments under a method before starting topic synthesis.')}</div>}
      <p className="process-analysis-hint">{t('Experiments with the same process are compared by their changed conditions. Different process versions stay visibly separate while the final review considers the whole research topic.')}</p>
    </section>

    <section className="card process-integrated-action"><div className="card-head"><div><div className="card-title"><Activity size={16}/>{t('Final topic synthesis')}</div><div className="card-sub">{t('Once you have collected experiment runs and measurement files, analyze all completed results in this research topic together with one click.')}</div></div><span className={`ai-status ${ai?.reachable && ai.model_installed ? 'ready' : ''}`}>{ai?.model ?? t('Gemma unavailable')}</span></div>
      <div className="process-analysis-action-row"><div><b>{completedTopicRuns.length} {t('completed measurements ready')}</b><small>{topicAnalysisRuns.length-completedTopicRuns.length} {t('measurements still waiting for a specialist tool')}</small></div><button className="button primary" disabled={(!completedTopicRuns.length&&!experiments.length)||integrating||!ai?.enabled} onClick={()=>void integrateTopic()}><Activity size={15}/>{integrating?t('Preparing combined explanation…'):t('Analyze the entire research topic')}</button></div>
      <details className="analysis-focus-settings"><summary>{t('Adjust analysis focus (optional)')}</summary><label className="integrated-goal">{t('What should Gemma explain about these results?')}<textarea rows={2} value={goal} onChange={event=>setGoal(event.target.value)}/></label><label className="assistant-general-toggle"><input type="checkbox" checked={allowGeneralKnowledge} onChange={event=>setAllowGeneralKnowledge(event.target.checked)}/><span><b>{t('Allow general scientific context')}</b><small>{t('Paper-backed claims still show citations; general context is labeled separately.')}</small></span></label></details>
      {error&&<div className="error analysis-error">{error}<button onClick={()=>setError('')}>{t('Dismiss')}</button></div>}
      {result&&<div className="analysis-output"><div className="analysis-output-head"><div><b>{result.result_key||result.filename}</b><small>{analysisProcessName(result)} · {result.modality.toUpperCase()} · {result.tool_id} · #{result.id}</small></div><a href={`/api/analysis/runs/${result.id}/original`}><ExternalLink size={13}/>{t('Original file')}</a></div><div className="metrics-grid">{Object.entries(result.result??{}).filter(([key,value])=>!['filename','interpretation_limit','review_required','mask_url','image_size_px','grid_shape_px','observed_peaks'].includes(key)&&(typeof value==='number'||typeof value==='string')).map(([key,value])=><div className="metric" key={key}><small>{key.replaceAll('_',' ')}</small><b>{typeof value==='number'?Number(value.toPrecision(5)).toString():String(value)}</b></div>)}</div><p className="analysis-caveat">{String(result.result?.interpretation_limit??'')}</p></div>}
    </section>

    <section className="card analysis-history"><div className="card-head"><div><div className="card-title">{t('All topic measurements')}</div><div className="card-sub">{t('Measurements remain linked to the experiment run and process version where they were recorded.')}</div></div><span className="history-tag">{topicAnalysisRuns.length} {t('measurements')}</span></div>
      {topicAnalysisRuns.length?<div className="analysis-run-list">{topicAnalysisRuns.map(run=>{const source=experiments.find(item=>item.id===run.experiment_id);const metrics=Object.entries(run.result??{}).filter(([key,value])=>!['filename','interpretation_limit','review_required','mask_url','image_size_px','grid_shape_px','observed_peaks'].includes(key)&&(typeof value==='number'||typeof value==='string')).slice(0,5);return <button type="button" className={`analysis-run-choice ${result?.id===run.id?'chosen':''}`} key={run.id} onClick={()=>{setResult(run);if(run.experiment_id)setBaseExperiment(String(run.experiment_id));}}><span className="history-tag">{run.modality.toUpperCase()}</span><span className="analysis-run-label"><b>{run.result_key||run.filename}</b><small>{analysisProcessName(run)} · {source?.name||t('Unlinked measurement')} · {source?.date||t('Date not recorded')} · {run.filename}</small></span><span className={`status ${run.analysis_status==='completed'?'success':'planned'}`}>{run.analysis_status==='completed'?t('Analyzed'):t('Waiting')}</span><span className="integrated-metrics">{metrics.map(([key,value])=><span key={key}><small>{key.replaceAll('_',' ')}</small><b>{String(value)}</b></span>)}</span></button>})}</div>:<div className="empty-hint">{t('No measurements are linked to this research topic yet. Mark a result for analysis while recording an experiment run.')}</div>}
    </section>

    {!!integratedHistory.length&&<section className="card integrated-history"><div className="card-head"><div><div className="card-title">{t('Saved topic syntheses')}</div><div className="card-sub">{t('Reopen a final analysis created from the research topic records.')}</div></div></div>{integratedHistory.slice(0,8).map(item=><button className="integrated-history-row" key={item.id} onClick={()=>{setIntegrated(item.result);setGoal(item.goal);setAllowGeneralKnowledge(item.allow_general_knowledge);setExperimentId(String(item.experiment_id??item.result.experiment_ids[0]??experiments[0]?.id??''));setDraftMessage('')}}><span className="history-tag">{item.analysis_run_ids.length} · {t('data files')}</span><span className="analysis-run-label"><b>{item.goal}</b><small>{item.model} · {new Date(item.created_at).toLocaleString()}</small></span></button>)}</section>}

    <section className="card integrated-analysis"><div className="card-head"><div><div className="card-title">{t('Integrated explanation')}</div><div className="card-sub">{t('Specialist tools calculate the measurements; Gemma explains their combined meaning, limits, and evidence.')}</div></div><span className="badge unknown">{t('Historical records ground next-step candidates')}</span></div>
      {integrated && <div className="integrated-report"><div className="research-trace"><b>{integrated.model}</b><span>{integrated.research_trace.measurement_runs_integrated} {t('measurement runs')}</span><span>{integrated.research_trace.experiment_records_loaded} {t('linked experiment records')}</span><span>{integrated.research_trace.source_passages_read} {t('paper excerpts')}</span></div>
        <section className="integrated-measurements"><h3>{t('Computed observations')}</h3><p>{t('These are values calculated from the selected files. Gemma interpretations below do not replace these measurements.')}</p>{integrated.measurements.map(item => <article className="integrated-measurement" key={item.analysis_run_id}><div><span className="history-tag">{item.modality.toUpperCase()}</span><b>{item.filename}</b><small>{t('Analysis run')} #{item.analysis_run_id} · SHA-256 {item.sha256.slice(0, 12)}…</small></div><div className="integrated-metrics">{Object.entries(item.computed_outputs).filter(([key, value]) => !['filename','interpretation_limit','review_required','mask_url','observed_peaks','grid_shape_px','image_size_px'].includes(key) && (typeof value === 'number' || typeof value === 'string')).slice(0, 8).map(([key,value]) => <span key={key}><small>{key.replaceAll('_',' ')}</small><b>{typeof value === 'number' ? Number(value.toPrecision(5)).toString() : String(value)}</b></span>)}</div>{Array.isArray(item.computed_outputs.observed_peaks) && <div className="integrated-metrics peak-preview">{(item.computed_outputs.observed_peaks as {x:number;relative_intensity_percent:number}[]).slice(0,8).map((peak,index)=><span key={`${peak.x}-${index}`}><small>2θ</small><b>{peak.x.toPrecision(5)} · {peak.relative_intensity_percent.toFixed(1)}%</b></span>)}</div>}</article>)}</section>
        <section className="integrated-claims"><h3>{t('Gemma explains the combined results')}</h3>{integrated.claims.map((claim,index) => <article className="assistant-claim" key={`${index}-${claim.claim}`}><span className={`badge ${claim.status.toLowerCase()}`}>{t(claim.status === 'MODEL_KNOWLEDGE' ? 'GEMMA KNOWLEDGE' : claim.status === 'LAB_RECORD' ? 'LAB RECORD' : claim.status)}</span><p>{claim.claim}</p>{!!claim.analysis_run_refs.length && <small>{t('Analysis runs:')} {claim.analysis_run_refs.map(id => `#${id}`).join(', ')}</small>}{!!claim.evidence_ids.length && <small>{t('Evidence IDs:')} {claim.evidence_ids.join(', ')}</small>}{!!claim.experiment_refs.length && <small>{t('Experiment records:')} {claim.experiment_refs.map(id => experiments.find(item => item.id === id)?.code ?? `#${id}`).join(', ')}</small>}</article>)}</section>
        {!!integrated.evidence.length && <section className="integrated-evidence"><h3>{t('Paper evidence used')}</h3>{integrated.evidence.map(item => <article className="evidence-card" key={item.evidence_id}><b>{item.paper_title} · p. {item.page}{item.section ? ` · ${item.section}` : ''}</b><p>{item.text}</p><small>Evidence ID {item.evidence_id}</small></article>)}</section>}
        {!!integrated.evidence_gaps.length && <section className="evidence-gaps"><h3>{t('Evidence or measurements still needed')}</h3>{integrated.evidence_gaps.map((gap,index) => <article className="gap-card" key={`${index}-${gap.need}`}><b>{gap.need}</b><p>{gap.why_needed}</p>{!!gap.search_queries.length && <small>{t('Search ideas')}: {gap.search_queries.join(' · ')}</small>}</article>)}</section>}
        {baseExperiment && historicalGuidance && <section className="historical-guidance"><div className="historical-guidance-head"><div><h3>{t('What past runs suggest')}</h3><p>{t('These are patterns in this method’s records, not proof that a condition caused the outcome.')}</p></div>{historicalGuidance.successRate===null?<span className="history-tag">{t('No comparable outcomes yet')}</span>:<div className="historical-rate"><b>{historicalGuidance.successRate.toFixed(0)}%</b><span>{t('observed success rate')}</span></div>}</div><div className="process-comparison-rule"><b>{t('Same-process comparison')}</b><span>{t('Runs with the same ordered process steps are compared together even when their condition values differ. Runs with changed steps or order are kept separate.')}</span></div>{historicalGuidance.interval&&<div className="historical-confidence"><b>{historicalGuidance.successes} {t('success')} / {historicalGuidance.failures} {t('failure')}</b><span>{t('Recorded outcomes')}: {historicalGuidance.sampleSize}</span>{historicalGuidance.excludedOutcomes>0&&<span>{historicalGuidance.excludedOutcomes} {t('partial, planned, or running outcomes excluded')}</span>}<span>{t('Approximate 95% uncertainty range')}: {historicalGuidance.interval[0].toFixed(0)}–{historicalGuidance.interval[1].toFixed(0)}%</span>{historicalGuidance.sampleSize<10&&<small>{t('Too few comparable runs for a dependable probability; treat this as an early indication only.')}</small>}</div>}{historicalGuidance.processVariantCount>0&&<div className="process-variant-note"><b>{t('Changed-process runs are separate')}</b><span>{historicalGuidance.processVariantCount} {t('runs use a different ordered step sequence and are excluded from this success rate.')}</span>{historicalGuidance.processVariantExamples.map(example=><small key={example}>{example}</small>)}{onOpenMethods&&<button className="text-button" onClick={onOpenMethods}>{t('Open methods to create or compare a process version')}</button>}</div>}{historicalGuidance.reference&&<div className="historical-reference"><b>{t('Closest successful reference run')}: {historicalGuidance.reference.code} · {historicalGuidance.reference.name}</b><small>{historicalGuidance.changedConditions.length?t('Candidate values below were used in this successful run. They are starting points to compare, not causal recommendations.'):t('This successful run has the same recorded process conditions as the selected run.')}</small>{!!historicalGuidance.changedConditions.length&&<div className="historical-variable-list">{historicalGuidance.changedConditions.map(item=><article key={item.label}><b>{item.label}</b><span>{t('Selected run')}: {item.current} {item.unit}</span><strong>{t('Successful reference')}: {item.observed} {item.unit}</strong><small>{t('Matching recorded outcomes')}: {item.successMatches} {t('success')} · {item.failureMatches} {t('failure')}</small></article>)}</div>}</div>}{!historicalGuidance.reference&&<p className="empty-hint">{t('No successful comparison exists for this method yet.')}</p>}</section>}
        {baseExperiment && <section className="next-experiment-builder"><h3>{t('Turn a reviewed change into a planned experiment')}</h3><p>{t('Choose one process condition or material amount and enter the value you want to test. Candidate values above come from recorded runs; choose and review the actual setting yourself.')}</p><label>{t('Variable to change')}<select value={draftTarget} onChange={event => { const target = adjustmentTargets.find(item => item.key === event.target.value); setDraftTarget(event.target.value); setDraftValue(target?.value ?? ''); }}>{adjustmentTargets.map(item => <option key={item.key} value={item.key}>{item.label} · {item.value} {item.unit}</option>)}</select></label>{activeTarget && <label>{t('Your next value')}<div className="analysis-value-input"><input value={draftValue} onChange={event => setDraftValue(event.target.value)} placeholder={t('Enter the value to test')}/><span>{activeTarget.unit}</span></div></label>}<button className="button outline" disabled={!activeTarget || !draftValue.trim() || savingDraft} onClick={() => void saveNextExperiment()}><Plus size={14}/>{savingDraft ? t('Saving…') : t('Save as planned experiment')}</button>{draftMessage && <div className="paper-upload-message">{draftMessage}</div>}</section>}
      </div>}
    </section>

    <details className="card analysis-tool-list"><summary className="card-title">{t('Available analysis tools and limits')}</summary><p className="card-sub">{t('Installed specialist software is listed here. Its format adapter must be connected before the app can run it.')}</p>{tools?.pilot_tools.map(tool => <article className="tool-row" key={tool.tool_id}><div className="tool-ready"><FileImage size={15}/></div><div><b>{tool.name}</b><small>{tool.modality.toUpperCase()} · {tool.method}</small><p>{tool.limits}</p></div><span className="status success">{t('READY')}</span></article>)}<div className="planned-label">{t('SPECIALIST ANALYSIS SOFTWARE')}</div>{tools?.specialist_adapters.map(tool => <a className="tool-row planned-tool" href={tool.url} target="_blank" rel="noreferrer" key={tool.tool_id}><div className={`tool-ready ${tool.installed ? '' : 'muted'}`}><ExternalLink size={14}/></div><div><b>{tool.tool_id.replaceAll('_', ' ')}</b><small>{tool.modality.toUpperCase()} · {tool.purpose}{tool.version ? ` · ${tool.version}` : ''}</small></div><span className={`status ${tool.installed ? 'success' : 'planned'}`}>{tool.installed ? t('INSTALLED') : t('NOT INSTALLED')}</span></a>)}</details>
    <p className="analysis-policy">{t('Instrument outputs remain computed observations. Integrated analysis separates paper evidence, lab records, and model context; save the next experiment only after reviewing and choosing the actual change.')}</p>
  </div>;
}
