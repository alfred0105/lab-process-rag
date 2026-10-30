import { useMemo, useState } from 'react';
import { Activity, Beaker } from 'lucide-react';
import { api } from '../api/client';
import { useLanguage } from '../language';
import type { AqueousEquilibriumResult, Experiment } from '../types';

const ELEMENTS = new Set(['Al', 'B', 'Ba', 'Br', 'C(4)', 'Ca', 'Cd', 'Cl', 'Cu', 'F', 'Fe(2)', 'Fe(3)', 'K', 'Li', 'Mg', 'Mn', 'Na', 'N(5)', 'P', 'Pb', 'S(6)', 'Si', 'Sr', 'Zn']);
const PHASES: Record<string, string[]> = { Zn: ['Zn(OH)2(e)', 'Smithsonite', 'Zincite'], Ca: ['Calcite', 'Aragonite', 'Dolomite'], Mg: ['Dolomite', 'Gibbsite'], Al: ['Gibbsite'], Fe: ['Goethite', 'Hematite'] };
type DerivedInputs = { temperature: number; pH: number; totals: Record<string, number>; notes: string[]; missing: string[] };

function deriveInputs(experiment: Experiment): DerivedInputs {
  const variables = experiment.steps.flatMap(step => step.variables.map(variable => ({ ...variable, step: step.name })));
  const readNumber = (item: typeof variables[number]) => String(item.value).trim() ? Number(String(item.value).replace(',', '.')) : Number.NaN;
  const ph = variables.find(item => /^(ph|solution_ph|initial_ph)$/i.test(item.name.trim()));
  const temperature = variables.find(item => /^(temperature|temperature_c|reaction_temperature|reaction_temperature_c|growth[ _-]?temperature|synthesis[ _-]?temperature|hydrothermal[ _-]?temperature(?:_c)?|annealing[ _-]?temperature(?:_c)?)$/i.test(item.name.trim()));
  const totals: Record<string, number> = {};
  const notes: string[] = [];
  for (const item of variables) {
    const match = item.name.trim().match(/^(Al|B|Ba|Br|C\(4\)|Ca|Cd|Cl|Cu|F|Fe\(2\)|Fe\(3\)|K|Li|Mg|Mn|Na|N\(5\)|P|Pb|S\(6\)|Si|Sr|Zn)(?:[_ -]?(?:concentration|total))?$/i);
    if (!match) continue;
    const element = [...ELEMENTS].find(candidate => candidate.toLowerCase() === match[1].toLowerCase());
    const value = readNumber(item);
    if (!element || !Number.isFinite(value) || value <= 0) continue;
    const unit = (item.unit ?? '').trim().toLowerCase();
    if (['mol/kgw', 'mol/kg water', 'mol/kg'].includes(unit)) totals[element] = value;
    else if (['m', 'mol/l', 'mol/liter'].includes(unit)) { totals[element] = value; notes.push('Molarity converted using an approximate 1 kg water ≈ 1 L solution assumption.'); }
    else if (['mm', 'mmol/l', 'mmol/kgw', 'mmol/kg'].includes(unit)) { totals[element] = value / 1000; if (unit === 'mm' || unit === 'mmol/l') notes.push('Molarity converted using an approximate 1 kg water ≈ 1 L solution assumption.'); }
  }
  const missing = [...(!ph || !Number.isFinite(readNumber(ph)) ? ['pH'] : []), ...(!temperature || !Number.isFinite(readNumber(temperature)) ? ['temperature'] : []), ...(Object.keys(totals).length ? [] : ['supported dissolved-element total with a concentration unit'])];
  return { temperature: temperature ? readNumber(temperature) : 25, pH: ph ? readNumber(ph) : 7, totals, notes: [...new Set(notes)], missing };
}

export default function PHREEQCWorkbench({ experiments, onOpenExperiments }: { experiments: Experiment[]; onOpenExperiments: () => void }) {
  const { t } = useLanguage();
  const candidates = experiments.filter(experiment => !experiment.demo && experiment.status !== 'planned');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const selected = candidates.find(experiment => experiment.id === selectedId) ?? candidates[0];
  const inputs = useMemo(() => selected ? deriveInputs(selected) : null, [selected]);
  const [result, setResult] = useState<AqueousEquilibriumResult | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const run = async () => {
    if (!inputs || !selected || inputs.missing.length) return;
    setBusy(true); setError('');
    try {
      const phases = [...new Set(Object.keys(inputs.totals).flatMap(element => PHASES[element] ?? []))].slice(0, 8);
      setResult(await api.aqueousEquilibrium({ temperature_c: inputs.temperature, pH: inputs.pH, totals_molal: inputs.totals, phases }));
    } catch (cause) { setError(t(cause instanceof Error ? cause.message : String(cause))); }
    finally { setBusy(false); }
  };
  return <section className="card phreeqc-workbench">
    <div className="card-head"><div><div className="card-title"><Beaker size={16}/>{t('PHREEQC aqueous equilibrium')}</div><div className="card-sub">{t('PHREEQC reads process conditions already saved in the selected experiment.')}</div></div><span className="simulation-state-pill ready">PHREEQC · LOCAL</span></div>
    {selected && inputs ? <>
      <label className="process-simulation-source">{t('Source experiment')}
        <select value={selected.id} onChange={event => { setSelectedId(Number(event.target.value)); setResult(null); setError(''); }}>
          {candidates.map(item => <option key={item.id} value={item.id}>{item.code} · {item.name} · {item.method_name ?? item.target}{item.status === 'reference' ? ` · ${t('Literature reference')}` : ''}</option>)}
        </select>
      </label>
      <div className="process-simulation-values"><div><small>{t('pH')}</small><b>{inputs.missing.includes('pH') ? '—' : inputs.pH}</b></div><div><small>{t('Temperature')}</small><b>{inputs.missing.includes('temperature') ? '—' : `${inputs.temperature} °C`}</b></div><div><small>{t('Dissolved totals')}</small><b>{Object.keys(inputs.totals).length || '—'}</b></div></div>
      {Object.keys(inputs.totals).length > 0 && <div className="process-simulation-values">{Object.entries(inputs.totals).map(([element, value]) => <div key={element}><small>{element}</small><b>{value.toPrecision(4)} mol/kgw</b></div>)}</div>}
      {inputs.notes.map(note => <p className="simulation-caveat" key={note}>{t(note)}</p>)}
      {inputs.missing.length > 0 ? <div className="simulation-range-note"><b>{t('Not enough chemistry was recorded to run PHREEQC.')}</b><span>{t('Missing process values')}: {inputs.missing.map(value => t(value)).join(', ')}. {t('No default or demo values were inserted.')}</span><button type="button" className="button outline small" onClick={onOpenExperiments}>{t('Edit process record')}</button></div> : <button type="button" className="button primary" disabled={busy} onClick={() => void run()}><Activity size={15}/>{busy ? t('Calculating…') : t('Run from saved process')}</button>}
      {result && <div className="phreeqc-results"><div className="phreeqc-result-summary"><span><small>{t('Calculated pH')}</small><b>{result.calculated_pH.toFixed(3)}</b></span><span><small>{t('Temperature')}</small><b>{result.temperature_c} °C</b></span><span><small>{t('Engine')}</small><b>{result.model_id}</b></span></div><section><h4>{t('Mineral saturation index')}</h4>{result.saturation_indices.map(item => <div className="phreeqc-si-row" key={item.phase}><b>{item.phase}</b><strong>{item.saturation_index === null ? '—' : item.saturation_index.toFixed(3)}</strong><em>{t(item.interpretation)}</em></div>)}</section><section><h4>{t('Calculated aqueous species')}</h4><div className="table-wrap"><table><thead><tr><th>{t('Aqueous species')}</th><th>{t('Molality (mol/kg water)')}</th></tr></thead><tbody>{result.aqueous_species.slice(0, 12).map(item => <tr key={item.name}><td>{item.name}</td><td>{item.molality.toExponential(3)}</td></tr>)}</tbody></table></div></section><div className="phreeqc-limitations"><b>{t('Interpretation limits')}</b>{result.limitations.map(item => <p key={item}>{t(item)}</p>)}</div></div>}
    </> : <div className="empty-hint">{t('No non-demo experiment records are available in this research topic.')}</div>}
    {error && <div className="error" role="alert">{error}</div>}
  </section>;
}
