import { useEffect, useState } from 'react';
import { Activity, ArrowRight, Beaker, CheckCircle2, CircleDashed, FlaskConical, GitBranch, Microscope, MoveRight, TriangleAlert, Waves } from 'lucide-react';
import PHREEQCWorkbench from './PHREEQCWorkbench';
import { api } from '../api/client';
import { useLanguage } from '../language';
import type { Experiment } from '../types';
import HistoricalOutcomeSimulator from './HistoricalOutcomeSimulator';
import MaterialDataReview from './MaterialDataReview';
import MagneticHydrothermalLab from './MagneticHydrothermalLab';

type SimulationStatus = { phreeqc_installed: boolean; aqueous_equilibrium: boolean; openfoam_installed:boolean; openfoam_version:string|null; openfoam_instance:string|null; openfoam_mixer_tutorial_verified:boolean; source: string };
export default function SimulationPanel({ onOpenExperiments, onOpenAnalysis, onDataChanged, experiments }: { onOpenExperiments: () => void; onOpenAnalysis: () => void; onDataChanged: () => Promise<void> | void; experiments:Experiment[] }) {
  const { t } = useLanguage();
  const [status, setStatus] = useState<SimulationStatus | null>(null);
  const [error, setError] = useState('');

  useEffect(() => { void api.simulationStatus().then(setStatus).catch(cause => setError(t(cause instanceof Error?cause.message:String(cause)))); }, []);
  const ready = Boolean(status?.phreeqc_installed && status.aqueous_equilibrium);
  const hasHistoricalAnalog = experiments.some(run=>run.method_version_id&&!run.demo&&experiments.filter(item=>item.method_version_id===run.method_version_id&&!item.demo&&['success','failure','partial_success','reference'].includes(item.status)).length>=3);
  const mixingRuns = experiments.filter(run=>!run.demo&&run.status!=='planned');

  return <div className="simulation-workspace">
    <section className="simulation-overview card">
      <div className="simulation-overview-copy">
        <div className="eyebrow">{t('SIMULATION WORKSPACE')}</div>
        <h2>{t('What can run today')}</h2>
        <p>{t('See which simulation pieces are connected, run the available local model, and identify what still needs an engine or experimental data.')}</p>
      </div>
      <div className="simulation-counts">
        <div className="simulation-count available"><CheckCircle2 size={17}/><b>{(ready?1:0)+(hasHistoricalAnalog?1:0)}</b><small>{t('Runnable here')}</small></div>
        <div className="simulation-count partial"><TriangleAlert size={17}/><b>1</b><small>{t('Connected analysis')}</small></div>
        <div className="simulation-count waiting"><CircleDashed size={17}/><b>2</b><small>{t('Not connected')}</small></div>
      </div>
    </section>

    {error && <div className="error" role="alert">{error}</div>}

    <section className="card simulation-flow-card">
      <div className="card-head"><div><div className="card-title">{t('How a simulation runs')}</div><div className="card-sub">{t('Two local calculation engines are connected. Automatic handoff between process-stage models is not wired yet.')}</div></div><span className={`simulation-state-pill ${ready ? 'ready' : 'waiting'}`}>{ready ? t('LIVE · LOCAL') : t('CHECKING')}</span></div>
      <div className="simulation-flow">
        <article><span className="simulation-flow-icon"><FlaskConical size={18}/></span><small>01</small><b>{t('Experiment inputs')}</b><p>{t('Conditions and materials already recorded in the selected process run')}</p><em className="state-connected">{t('Reused from process record')}</em></article>
        <MoveRight className="simulation-flow-arrow" size={20}/>
        <article className={ready ? 'is-live' : ''}><span className="simulation-flow-icon"><Beaker size={18}/></span><small>02</small><b>{t('Local chemistry engines')}</b><p>{status?.source ?? t('Checking local API connection')} · PHREEQC</p><em className={ready ? 'state-connected' : 'state-pending'}>{ready ? t('Executable on this Mac') : t('Not confirmed')}</em></article>
        <MoveRight className="simulation-flow-arrow" size={20}/>
        <article><span className="simulation-flow-icon"><Activity size={18}/></span><small>03</small><b>{t('Estimate + assumptions')}</b><p>{t('Calculated result stays labeled as an estimate, separate from measurements')}</p><em className="state-connected">{t('Returned by API')}</em></article>
        <MoveRight className="simulation-flow-arrow" size={20}/>
        <article><span className="simulation-flow-icon"><GitBranch size={18}/></span><small>04</small><b>{t('Pass into next process model')}</b><p>{t('Automatic stage-to-stage inputs and calibrated outcome prediction')}</p><em className="state-pending">{t('Not implemented')}</em></article>
      </div>
      <div className="simulation-flow-note"><b>{t('What this means')}</b><span>{t('Ideal acid/base pH estimates and PHREEQC aqueous equilibrium calculations are available locally. They do not simulate synthesis growth or predict final yield, and stage-to-stage model handoff is not connected.')}</span></div>
    </section>

    <section className="simulation-tool-grid">
      <article className="card simulation-tool-card active-tool">
        <header><span className="tool-icon"><Beaker size={18}/></span><span className={`simulation-state-pill ${ready ? 'ready' : 'waiting'}`}>{ready ? t('RUNNABLE') : t('CHECKING')}</span></header>
        <h3>{t('PHREEQC aqueous speciation')}</h3>
        <p>{t('Reads pH, temperature, and supported dissolved-element totals from the selected process run. Missing inputs are reported instead of replaced with defaults.')}</p>
        <div className="simulation-tool-meta"><span>{t('Model')}: <b>{'PHREEQC 3 / phreeqc.dat'}</b></span><span>{t('Compute')}: <b>{t('Local Python · deterministic')}</b></span></div>
      </article>
      <article className="card simulation-tool-card linked-tool">
        <header><span className="tool-icon"><Microscope size={18}/></span><span className="simulation-state-pill partial-pill">{t('ANALYSIS TOOL')}</span></header>
        <h3>{t('XRD peak candidate matching')}</h3>
        <p>{t('Peak detection and COD reference matching are available in Analysis. This compares observed data with crystal structures; it is not a process simulator.')}</p>
        <button className="text-button" type="button" onClick={onOpenAnalysis}>{t('Open measurement analysis')} <ArrowRight size={14}/></button>
      </article>
      <article className="card simulation-tool-card planned-tool">
        <header><span className="tool-icon"><CircleDashed size={18}/></span><span className="simulation-state-pill waiting">{t('NOT CONNECTED')}</span></header>
        <h3>{t('Synthesis kinetics and growth')}</h3>
        <p>{t('No material-specific kinetic model is connected. Existing run history is not yet used to calibrate predicted outcomes.')}</p>
      </article>
      <article className="card simulation-tool-card planned-tool">
        <header><span className="tool-icon"><CircleDashed size={18}/></span><span className="simulation-state-pill waiting">{t('NOT CONNECTED')}</span></header>
        <h3>{t('Chained process simulators')}</h3>
        <p>{t('No executable step graph currently transfers calculated values between separate simulation engines.')}</p>
      </article>
    </section>

    <MagneticHydrothermalLab experiments={mixingRuns} />
    <SolutionMixingReadiness experiments={mixingRuns} openfoamInstalled={Boolean(status?.openfoam_installed)} mixerTutorialVerified={Boolean(status?.openfoam_mixer_tutorial_verified)} openfoamVersion={status?.openfoam_version??null}/>
    <MaterialDataReview experiments={mixingRuns} onOpenExperiments={onOpenExperiments} onDataChanged={onDataChanged}/>

    <HistoricalOutcomeSimulator experiments={experiments}/>
    <PHREEQCWorkbench experiments={experiments} onOpenExperiments={onOpenExperiments}/>

    <section className="simulation-status-footer"><span><i className="status-led ready-led"/>{t('Working now')}: {t('pH estimate + PHREEQC equilibrium + XRD candidate analysis')}</span><span><i className="status-led waiting-led"/>{t('Still needed')}: {t('validated process models, stage handoff, and data-based calibration')}</span></section>
  </div>;
}

function SolutionMixingReadiness({experiments,openfoamInstalled,mixerTutorialVerified,openfoamVersion}:{experiments:Experiment[];openfoamInstalled:boolean;mixerTutorialVerified:boolean;openfoamVersion:string|null}) {
  const {t}=useLanguage();
  const [selectedId,setSelectedId]=useState<number|null>(null);
  const selected=experiments.find(run=>run.id===selectedId)??experiments[0];
  const vars=selected?.steps.flatMap(step=>step.variables.map(value=>({name:value.name,unit:value.unit??'',value:String(value.value)})))??[];
  const checks:[string,RegExp][]=[
    [t('Stirring speed'),/\b(stirring|mixing|agitator)[ _-]?(speed|rate)?\b|\brpm\b/i],
    [t('Liquid volume'),/\b(batch|solution|liquid|working)[ _-]?(volume|amount)\b/i],
    [t('Vessel and impeller geometry'),/\b(vessel|tank|impeller|blade|baffle|diameter|geometry)\b/i],
    [t('Liquid properties'),/\b(viscosity|density|diffusivity)\b/i],
    [t('Addition sequence and rate'),/\b(addition|feed|dosing|滴加|투입).*(order|rate|time|sequence)?\b/i],
  ];
  const present=checks.map(([label,pattern])=>({label,found:vars.some(item=>pattern.test(`${item.name} ${item.unit}`))}));
  const readyCount=present.filter(item=>item.found).length;
  return <section className="card solution-mixing-card">
    <div className="card-head"><div><div className="card-title"><Waves size={16}/>{t('Solution mixing and reaction pathway')}</div><div className="card-sub">{t('A real liquid mixture needs flow, local concentration, chemistry, and particle formation to be treated as separate linked models.')}</div></div><span className={`simulation-state-pill ${openfoamInstalled?'ready':'waiting'}`}>{mixerTutorialVerified?`${t('MIXER TUTORIAL VERIFIED')} · OpenFOAM ${openfoamVersion??''}`:openfoamInstalled?`${t('INSTALLED IN LOCAL VM')} · OpenFOAM ${openfoamVersion??''}`:t('FLOW MODEL NOT INSTALLED')}</span></div>
    {selected&&<label className="process-simulation-source">{t('Source experiment')}<select value={selected.id} onChange={event=>setSelectedId(Number(event.target.value))}>{experiments.map(run=><option key={run.id} value={run.id}>{run.code} · {run.name} · {run.method_name??run.target}</option>)}</select></label>}
    <div className="mixing-stage-grid">
      <article><small>01</small><b>{t('Tank-scale flow')}</b><span>{t('Circulation, dead zones, impeller flow')}</span><em className={openfoamInstalled?'state-connected':'state-pending'}>{mixerTutorialVerified?t('OpenFOAM mixer tutorial completed; experiment case is not connected'):openfoamInstalled?t('Installed in VM; mixer case is not connected'):`OpenFOAM · ${t('not installed')}`}</em></article>
      <article><small>02</small><b>{t('Feed mixing')}</b><span>{t('Concentration gradients and mixing time')}</span><em className="state-pending">CFD + scalar transport</em></article>
      <article className="mixing-chemistry"><small>03</small><b>{t('Aqueous chemistry')}</b><span>{t('Speciation and saturation from the bulk chemistry')}</span><em className="state-connected">PHREEQC · {t('connected separately')}</em></article>
      <article><small>04</small><b>{t('Precipitation and growth')}</b><span>{t('Nucleation, particle growth, aggregation')}</span><em className="state-pending">{t('system-specific rate data needed')}</em></article>
    </div>
    {selected?<div className="mixing-readiness"><div className="mixing-readiness-heading"><b>{t('What this process record contains')}</b><span>{readyCount}/{checks.length} {t('input groups found')}</span></div><div className="mixing-input-checks">{present.map(item=><span className={item.found?'found':'missing'} key={item.label}><i/>{item.label}</span>)}</div><small>{t('Only saved process values are inspected here. Missing geometry or feed details are not guessed, and no mixing time or precipitation result is claimed.')}</small></div>:<div className="empty-hint">{t('No non-demo experiment record is available to inspect.')}</div>}
    <p className="simulation-caveat">{t('Mixing and precipitation depend on their relative time scales. A stirrer RPM by itself cannot determine local supersaturation, nucleation, particle size, or yield.')}</p>
  </section>;
}
