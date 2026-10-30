import { useMemo, useState } from 'react';
import type { Experiment } from '../types';
import { useLanguage } from '../language';

type Group = { key: string; label: string; runs: Experiment[]; referenceOnly: boolean };
export default function HistoricalOutcomeSimulator({ experiments }: { experiments: Experiment[] }) {
  const { t } = useLanguage();
  const groups = useMemo(() => {
    const map = new Map<string, Group>();
    for (const run of experiments) {
      if (run.demo || !['success', 'failure', 'partial_success', 'reference'].includes(run.status)) continue;
      const key = run.method_version_id ? `version-${run.method_version_id}` : `legacy-${run.method_name ?? run.target}`;
      const label = `${run.method_name ?? run.target}${run.method_version_label ? ` · ${run.method_version_label}` : run.method_version ? ` · v${run.method_version}` : ''}`;
      const group = map.get(key) ?? { key, label, runs: [], referenceOnly: true };
      group.runs.push(run); group.referenceOnly = group.referenceOnly && run.status === 'reference'; map.set(key, group);
    }
    return [...map.values()];
  }, [experiments]);
  const [groupKey, setGroupKey] = useState('');
  const activeGroup = groups.find(group => group.key === groupKey) ?? groups[0];
  const runs = activeGroup?.runs ?? [];
  const [targetRunId, setTargetRunId] = useState<number | null>(null);
  const target = runs.find(run => run.id === targetRunId) ?? runs[0];
  const variableOptions = [...new Set(runs.flatMap(run => run.steps.flatMap(step => step.variables.map(variable => `${step.name}::${variable.name}`))))];
  const [variable, setVariable] = useState(''); const [selectedOutcome, setSelectedOutcome] = useState('');
  const activeVariable = variableOptions.includes(variable) ? variable : variableOptions[0] ?? '';
  const outcomes = [...new Set(runs.flatMap(run => run.results.filter(result => Number.isFinite(Number(result.value))).map(result => result.key)))];
  const outcomeKey = outcomes.includes(selectedOutcome) ? selectedOutcome : outcomes[0] ?? '';
  const [stepName, variableName] = activeVariable.split('::');
  const targetCondition = target?.steps.find(step => step.name === stepName)?.variables.find(item => item.name === variableName);
  const candidate = Number(targetCondition?.value);
  const actualResult = Number(target?.results.find(item => item.key === outcomeKey)?.value);
  const points = runs.filter(run => run.id !== target?.id).flatMap(run => {
    const condition = run.steps.find(step => step.name === stepName)?.variables.find(item => item.name === variableName);
    const outcome = run.results.find(result => result.key === outcomeKey);
    const x = Number(condition?.value); const y = Number(outcome?.value);
    return condition && outcome && Number.isFinite(x) && Number.isFinite(y) ? [{ run, x, y, unit: condition.unit ?? '', outcomeUnit: outcome.unit ?? '' }] : [];
  });
  const xValues = points.map(point => point.x); const minX = Math.min(...xValues); const maxX = Math.max(...xValues);
  const enoughData = points.length >= 3 && Number.isFinite(candidate) && Number.isFinite(actualResult);
  const inRange = enoughData && candidate >= minX && candidate <= maxX;
  const nearest = [...points].sort((a, b) => Math.abs(a.x - candidate) - Math.abs(b.x - candidate)).slice(0, 3);
  const estimate = inRange && nearest.length === 3 ? nearest.reduce((sum, point) => sum + point.y / (Math.abs(point.x - candidate) + Math.max((maxX - minX) * .02, 1e-9)), 0) / nearest.reduce((sum, point) => sum + 1 / (Math.abs(point.x - candidate) + Math.max((maxX - minX) * .02, 1e-9)), 0) : null;
  const chartMinX = Math.min(minX, candidate); const chartMaxX = Math.max(maxX, candidate);
  const yValues = [...points.map(point => point.y), ...(Number.isFinite(actualResult) ? [actualResult] : []), ...(estimate === null ? [] : [estimate])];
  const minY = Math.min(...yValues); const maxY = Math.max(...yValues);
  return <section className="card historical-simulation-card">
    <div className="card-head"><div><div className="card-title">{t('Historical-run analog simulator')}</div><div className="card-sub">{t('Hold out one recorded run, estimate it from the other nearby runs, and compare with its reported result.')}</div></div><span className="simulation-state-pill partial-pill">{activeGroup?.referenceOnly ? t('Literature references · validation') : t('Recorded runs · holdout check')}</span></div>
    {groups.length ? <>
      <div className="historical-simulation-controls">
        <label>{t('Process version')}<select value={activeGroup?.key ?? ''} onChange={event => { setGroupKey(event.target.value); setTargetRunId(null); }}>
          {groups.map(group => <option key={group.key} value={group.key}>{group.label}{group.referenceOnly ? ` · ${t('literature')}` : ''}</option>)}
        </select></label>
        <label>{t('Hold out this run')}<select value={target?.id ?? ''} onChange={event => setTargetRunId(Number(event.target.value))}>{runs.map(run => <option key={run.id} value={run.id}>{run.code} · {run.name}</option>)}</select></label>
        <label>{t('Condition to evaluate')}<select value={activeVariable} onChange={event => setVariable(event.target.value)}>{variableOptions.map(option => <option key={option} value={option}>{option.replace('::', ' · ')}</option>)}</select></label>
        <label>{t('Outcome to estimate')}<select value={outcomeKey} onChange={event => setSelectedOutcome(event.target.value)}>{outcomes.map(option => <option key={option} value={option}>{t(option.replaceAll('_', ' '))}</option>)}</select></label>
      </div>
      {points.length < 3 ? <div className="empty-hint">{t('At least three other runs with this condition and result are needed.')}</div> : !inRange ? <div className="simulation-range-note">{t('The held-out condition is outside the remaining runs’ range, so this check does not extrapolate.')}</div> : null}
      {estimate !== null && <div className="historical-simulation-result">
        <div className="historical-sim-summary"><span><small>{t('Estimated from other runs')}</small><b>{Number(estimate.toPrecision(5))} {points[0]?.outcomeUnit}</b></span><span><small>{t('Reported held-out result')}</small><b>{actualResult} {target?.results.find(item => item.key === outcomeKey)?.unit}</b></span><span><small>{t('Absolute error')}</small><b>{Number(Math.abs(estimate - actualResult).toPrecision(4))} {points[0]?.outcomeUnit}</b></span></div>
        <svg className="historical-sim-chart" viewBox="0 0 620 240" role="img" aria-label={t('Historical run outcome distribution')}>
          <path d="M48 24H600 M48 75H600 M48 126H600 M48 177H600 M48 194H600" className="outcome-gridline" />
          {points.map(point => { const x = 48 + (point.x - chartMinX) / (chartMaxX - chartMinX || 1) * 552; const y = 194 - (point.y - minY) / (maxY - minY || 1) * 170; return <circle key={point.run.id} cx={x} cy={y} r="5" className="outcome-point reference"><title>{point.run.code} · {point.x} {point.unit} → {point.y} {point.outcomeUnit} · {t('Training reference')}</title></circle>; })}
          <path d={`M${48 + (candidate - chartMinX) / (chartMaxX - chartMinX || 1) * 552} 24V194`} className="simulation-candidate-line" />
          <path d={`M${48 + (candidate - chartMinX) / (chartMaxX - chartMinX || 1) * 552 - 6} ${194 - (estimate - minY) / (maxY - minY || 1) * 170} l6 -7 l6 7 l-6 7 z`} className="simulation-candidate-point"><title>{t('Holdout estimate')}: {estimate}</title></path>
          <text x="324" y="224" textAnchor="middle" className="outcome-date">{variable.replace('::', ' · ')}{points[0]?.unit ? ` (${points[0].unit})` : ''}</text><text transform="translate(13 110) rotate(-90)" textAnchor="middle" className="outcome-date">{t(outcomeKey.replaceAll('_', ' '))}{points[0]?.outcomeUnit ? ` (${points[0].outcomeUnit})` : ''}</text>
        </svg>
        <p className="simulation-caveat">{t('This one-factor nearest-neighbor check holds out one run, but does not control other changing process conditions. It is not a causal claim, validated physical simulation, confidence interval, or success probability.')}</p>
      </div>}
    </> : <div className="empty-hint">{t('No non-demo process records are available for this check.')}</div>}
  </section>;
}
