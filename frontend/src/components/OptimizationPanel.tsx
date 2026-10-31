import { useEffect, useMemo, useState } from 'react';
import { optimizationApi, type OptimizationCandidate, type OptimizationModel } from '../api/client';
import type { ResearchTopic } from '../types';
import { useLanguage } from '../language';

export default function OptimizationPanel({topic}:{topic:ResearchTopic}){
  const {t}=useLanguage();
  const [mode,setMode]=useState<'sandbox'|'research'>('sandbox');
  const [methodVersionId,setMethodVersionId]=useState<number>(topic.methods?.[0]?.versions?.[0]?.id??0);
  const [featureIds,setFeatureIds]=useState('x1, x2');
  const [targetId,setTargetId]=useState('branin');
  const [bounds,setBounds]=useState('');
  const [acquisition,setAcquisition]=useState<'ei'|'pi'|'ucb'>('ei');
  const [maximize,setMaximize]=useState(false);
  const [model,setModel]=useState<OptimizationModel|null>(null);
  const [candidates,setCandidates]=useState<OptimizationCandidate[]>([]);
  const [benchmark,setBenchmark]=useState<any>(null);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const versions=useMemo(()=>topic.methods?.flatMap(method=>method.versions.map(version=>({id:version.id,label:`${method.name} · v${version.version_label??version.version_number}`})))??[],[topic]);
  useEffect(()=>{setMethodVersionId(topic.methods?.[0]?.versions?.[0]?.id??0);setModel(null);setCandidates([]);setBenchmark(null)},[topic.id]);
  const parseFeatures=()=>featureIds.split(',').map(x=>x.trim()).filter(Boolean);
  const parseBounds=()=>bounds.split(';').map(pair=>pair.split(',').map(value=>Number(value.trim())));
  const run=async()=>{
    setBusy(true);setError('');setCandidates([]);setBenchmark(null);
    try{
      const features=mode==='sandbox'?['x1','x2']:parseFeatures();
      const target=mode==='sandbox'?'branin':targetId.trim();
      const trained=await optimizationApi.train({topic_id:topic.id,mode,feature_ids:features,target_id:target,
        method_version_id:mode==='research'?methodVersionId:null,kernel:'matern',seed:7});
      setModel(trained);
      const box=mode==='sandbox'?[[-5,10],[0,15]]:parseBounds();
      const recommendation=await optimizationApi.recommend(trained.model_id,{topic_id:topic.id,acquisition,bounds:box,
        maximize,candidate_count:5,search_samples:mode==='sandbox'?5000:3000,seed:7});
      setCandidates(recommendation.candidates);
      if(mode==='sandbox')setBenchmark(await optimizationApi.benchmark(topic.id,20,7));
    }catch(e){setError(e instanceof Error?e.message:String(e))}finally{setBusy(false)}
  };
  return <div className="optimization-workspace">
    <section className="card optimization-setup">
      <div className="card-head"><div><div className="card-title">{t('Gaussian process optimization')}</div><div className="card-sub">{t('Fit a probabilistic model and rank next conditions within explicit bounds.')}</div></div><span className="badge">{mode==='sandbox'?t('SANDBOX'):t('RESEARCH DATA')}</span></div>
      <div className="optimization-mode"><button className={mode==='sandbox'?'active':''} onClick={()=>{setMode('sandbox');setFeatureIds('x1, x2');setTargetId('branin');setMaximize(false)}}>{t('Synthetic sandbox')}</button><button className={mode==='research'?'active':''} onClick={()=>{setMode('research');setFeatureIds('');setTargetId('');setBounds('');setMaximize(false)}}>{t('Approved research data')}</button></div>
      {mode==='sandbox'?<div className="optimization-note"><b>Branin · {t('synthetic benchmark')}</b><span>{t('Uses an isolated mathematical objective. No experiment data is read or written as observations.')}</span><small>x1: −5…10 · x2: 0…15 · target: minimize</small></div>:<div className="optimization-fields">
        <label>{t('Method version')}<select value={methodVersionId} onChange={e=>setMethodVersionId(Number(e.target.value))}><option value={0}>{t('Choose a method version')}</option>{versions.map(version=><option key={version.id} value={version.id}>{version.label}</option>)}</select></label>
        <label>{t('Input parameter IDs')}<input value={featureIds} onChange={e=>setFeatureIds(e.target.value)} placeholder="e.g. growth_temperature"/><small>{t('Comma-separated IDs from accepted process records')}</small></label>
        <label>{t('Measured outcome ID')}<input value={targetId} onChange={e=>setTargetId(e.target.value)} placeholder="e.g. length_um"/></label>
        <label>{t('Bounds (min,max per input; separated by semicolons)')}<input value={bounds} onChange={e=>setBounds(e.target.value)} placeholder="60,100"/></label>
      </div>}
      <div className="optimization-controls"><label>{t('Acquisition')}<select value={acquisition} onChange={e=>setAcquisition(e.target.value as any)}><option value="ei">Expected Improvement</option><option value="pi">Probability of Improvement</option><option value="ucb">Upper Confidence Bound</option></select></label><label>{t('Objective')}<select disabled={mode==='sandbox'} value={maximize?'max':'min'} onChange={e=>setMaximize(e.target.value==='max')}><option value="min">{t('Minimize')}</option><option value="max">{t('Maximize')}</option></select></label><button className="button primary" disabled={busy||!topic.id||(mode==='research'&&(!methodVersionId||!featureIds.trim()||!targetId.trim()||!bounds.trim()))} onClick={()=>void run()}>{busy?t('Training and ranking…'):t('Train GP and recommend')}</button></div>
      <p className="optimization-safety">{t('Recommendations are computational candidates only. Predictive uncertainty is not experimental success probability. Human review is required; this screen never executes an experiment.')}</p>
      {error&&<div className="error">{error}</div>}
    </section>
    {model&&<section className="card optimization-results"><div className="card-head"><div><div className="card-title">{t('Model result')} · #{model.model_id}</div><div className="card-sub">{model.mode==='sandbox'?t('Synthetic sandbox model'):t('Approved measured data model')} · {model.config.sample_count} {t('training pairs')} · {model.config.kernel}</div></div><span className="badge">{model.model_version}</span></div>
      <div className="optimization-metrics"><Metric label="RMSE · holdout" value={model.metrics.rmse}/><Metric label="MAE · holdout" value={model.metrics.mae}/><Metric label="95% interval coverage · holdout" value={model.metrics.coverage_95}/></div><small>{model.config.validation_scheme} · {model.config.validation_rows} {t('validation rows')} · {t('Small-data validation is uncertain.')}</small>
      <small className="dataset-hash">Dataset SHA-256 · {model.dataset_hash}</small>
      {candidates.length>0&&<div className="table-wrap"><table><thead><tr><th>{t('Rank')}</th><th>{t('Parameter values')}</th><th>{t('Predicted outcome')}</th><th>{t('Predictive uncertainty')}</th><th>{t('Acquisition score')}</th><th>{t('Review')}</th></tr></thead><tbody>{candidates.map(candidate=><tr key={candidate.rank}><td>{candidate.rank}</td><td>{candidate.values.map((value,index)=>`${value.toPrecision(4)} ${candidate.units[index]??''}`).join(' · ')}</td><td>{candidate.predicted_mean.toPrecision(5)}</td><td>± {candidate.predictive_std.toPrecision(4)}</td><td>{candidate.acquisition_score.toPrecision(5)}</td><td>{t('Researcher review required')}</td></tr>)}</tbody></table></div>}
    </section>}
    {benchmark&&<section className="card optimization-results"><div className="card-title">{t('Sandbox optimization comparison')} · {benchmark.function}</div><div className="optimization-metrics"><Metric label={t('Random Search median best')} value={benchmark.policies.random_search.median_best}/><Metric label={t('Latin Hypercube median best')} value={benchmark.policies.latin_hypercube.median_best}/><Metric label={t('GP + EI median best')} value={benchmark.policies.gp_ei.median_best}/><Metric label={t('GP + UCB median best')} value={benchmark.policies.gp_ucb.median_best}/></div><div className="card-sub">{benchmark.seeds} {t('seeds')} · {benchmark.initial_points} {t('shared initial points')} · {benchmark.additional_evaluations} {t('additional evaluations')} · {t('Lower objective is better')} · {t('Known optimum')}: {benchmark.known_global_minimum_approx}</div><p className="optimization-safety">{benchmark.notice}</p></section>}
  </div>;
}
function Metric({label,value}:{label:string;value:number|undefined}){return <div className="optimization-metric"><small>{label}</small><b>{typeof value==='number'?value.toPrecision(5):'—'}</b></div>}
