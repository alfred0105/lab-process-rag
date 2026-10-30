import { useState, type FormEvent } from 'react';
import { Plus } from 'lucide-react';
import { useLanguage } from '../language';
import type { ResearchTopic } from '../types';

export default function TopicHome({ topics, onSelect, onCreate }: { topics: ResearchTopic[]; onSelect: (id: number) => void; onCreate: (name: string, description: string) => Promise<void> }) {
  const { t, language, setLanguage } = useLanguage();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('');
    try { await onCreate(name, description); setName(''); setDescription(''); }
    catch (cause) { setError(String(cause)); }
    finally { setBusy(false); }
  };
  return <main className="topic-home"><div className="topic-home-brand"><span>⚗</span><div><b>Lab Process RAG</b><small>{t('Research spaces')}</small></div><div className="topic-home-language">{t('Choose a research topic to open its methods, runs, and papers.')}</div><button type="button" className="language-toggle" aria-label={t('Language')} onClick={() => setLanguage(language === 'ko' ? 'en' : 'ko')}>{language === 'ko' ? '한국어 · EN' : 'KO · English'}</button></div><div className="topic-home-body"><div className="eyebrow">LAB PROCESS · WORKSPACES</div><h1>{t('Choose a research topic')}</h1><p>{t('Each topic keeps its methods, experiment records, and evidence organized together.')}</p><div className="topic-cards">{topics.map(topic => <button className="topic-card" type="button" key={topic.id} onClick={() => onSelect(topic.id)}><span className="topic-card-mark">⌁</span><b>{topic.name}</b><small>{topic.description || t('Research topic workspace')}</small><span className="topic-card-meta">{topic.methods.length} {t('methods')} · {topic.run_count} {t('runs')}</span></button>)}</div><form className="new-topic-form" onSubmit={submit}><h2>{t('Create a research topic')}</h2><div className="topic-form-row"><input required value={name} onChange={event => setName(event.target.value)} placeholder={t('e.g. ZnO nanowire research')} /><input value={description} onChange={event => setDescription(event.target.value)} placeholder={t('Short description (optional)')} /><button className="button primary" disabled={busy}><Plus size={14}/>{t('Create topic')}</button></div>{error && <div className="error topic-error">{error}</div>}</form></div></main>;
}
