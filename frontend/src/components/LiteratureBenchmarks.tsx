import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { BenchmarkDataset, BenchmarkRecord, BenchmarkSummary } from '../types';

const pretty = (value: string) => value.replaceAll('_', ' ');
const show = (value: unknown) => typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value);

export default function LiteratureBenchmarks() {
  const [datasets, setDatasets] = useState<BenchmarkDataset[]>([]);
  const [selected, setSelected] = useState('');
  const [records, setRecords] = useState<BenchmarkRecord[]>([]);
  const [summary, setSummary] = useState<BenchmarkSummary | null>(null);
  const [objective, setObjective] = useState<'maximize' | 'minimize'>('maximize');
  const [outcomeKey, setOutcomeKey] = useState('');
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    api.benchmarkCatalog().then(items => {
      setDatasets(items);
      setSelected(items[0]?.dataset_id ?? '');
    }).catch(reason => setError(String(reason))).finally(() => setBusy(false));
  }, []);

  useEffect(() => {
    if (!selected || !outcomeKey) return;
    setBusy(true);
    Promise.all([api.benchmarkRecords(selected), api.benchmarkSummary(selected, outcomeKey, objective)])
      .then(([rows, stats]) => { setRecords(rows); setSummary(stats); setError(''); })
      .catch(reason => setError(String(reason)))
      .finally(() => setBusy(false));
  }, [selected, objective, outcomeKey]);

  const current = datasets.find(item => item.dataset_id === selected);
  useEffect(() => { setOutcomeKey(current?.outcome_names[0] ?? ''); }, [selected, datasets]);
  return <div className="benchmarks-layout">
    <section className="card">
      <div className="card-head"><div><div className="card-title">Literature process datasets</div><div className="card-sub">{datasets.length} separate process families · {datasets.reduce((sum, item) => sum + item.run_count, 0)} reported runs</div></div></div>
      <p className="benchmark-notice">Each dataset stays in its own material and process family. The comparison below summarizes reported measurements; it does not estimate success probability or prove causation.</p>
      {error && <div className="error">{error}</div>}
      <div className="benchmark-dataset-list">{datasets.map(item => <button type="button" key={item.dataset_id} className={`benchmark-dataset ${selected === item.dataset_id ? 'active' : ''}`} onClick={() => setSelected(item.dataset_id)}>
        <span><b>{item.material_or_system}</b><small>{item.domain} · {item.process_family}</small></span><strong>{item.run_count} runs</strong>
      </button>)}</div>
    </section>
    {current && <section className="card">
      <div className="card-head"><div><div className="card-title">{current.material_or_system}</div><div className="card-sub">{current.process_family} · {records.length} records from {records[0]?.source_location}</div></div>
        <label className="benchmark-objective">Measure<select value={outcomeKey} onChange={event => setOutcomeKey(event.target.value)}>{current.outcome_names.map(name => <option key={name} value={name}>{pretty(name)}</option>)}</select></label><label className="benchmark-objective">Observed best<select value={objective} onChange={event => setObjective(event.target.value as 'maximize' | 'minimize')}><option value="maximize">Highest value</option><option value="minimize">Lowest value</option></select></label>
      </div>
      {summary && <><div className="benchmark-stats">{Object.entries(summary.outcomes).filter(([name]) => name === summary.selected_outcome).map(([name, stats]) => <article className="benchmark-stat" key={name}><small>{pretty(name)} · n={stats.n}</small><b>{stats.min} – {stats.max}</b><span>mean {Number(stats.mean.toFixed(4))} · median {Number(stats.median.toFixed(4))}</span><small>{objective === 'maximize' ? 'Highest observed' : 'Lowest observed'}: run {(stats.best_observed_runs ?? []).map(run => run.run_id).join(', ')}</small></article>)}</div><small className="benchmark-caution">{summary.notice}</small></>}
      <div className="benchmark-factors"><b>Conditions recorded</b>{current.factor_names.map(name => <span key={name}>{pretty(name)}</span>)}</div>
      <div className="table-wrap benchmark-table-wrap"><table><thead><tr><th>RUN</th><th>PROCESS CONDITIONS</th><th>MEASURED OUTCOME</th><th>SOURCE</th></tr></thead><tbody>{records.map(record => <tr key={`${record.dataset_id}-${record.run_id}`}>
        <td>{record.run_id}</td><td>{Object.entries(record.factors).map(([key, value]) => `${pretty(key)}: ${show(value)}`).join(' · ')}</td><td>{Object.entries(record.outcomes).map(([key, value]) => `${pretty(key)}: ${show(value)}`).join(' · ')}</td><td>{record.source_location} · <a href={record.source_url} target="_blank" rel="noreferrer">paper</a></td>
      </tr>)}</tbody></table></div>
      {busy && <div className="empty-hint">Loading literature records…</div>}
    </section>}
  </div>;
}
