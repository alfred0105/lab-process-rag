import { useState } from 'react';
import { BookOpen, Check, FileText, LoaderCircle, Upload, X } from 'lucide-react';
import { useLanguage } from '../language';
import { previewPaperMetadata, savePaperWithMetadata, type PaperMetadataPreview } from '../api/papers';

export default function PaperUploadFlow({ topicId, onSaved }: { topicId: number; onSaved: () => void }) {
  const { t } = useLanguage();
  const [file, setFile] = useState<File | null>(null);
  const [metadata, setMetadata] = useState<PaperMetadataPreview | null>(null);
  const [busy, setBusy] = useState<'extract' | 'save' | ''>('');
  const [error, setError] = useState('');
  const update = (field: keyof PaperMetadataPreview, value: string | number | null) => {
    setMetadata(current => current ? { ...current, [field]: value, metadata_sources: { ...current.metadata_sources, [field]: 'user_edited' } } : current);
  };
  const chooseConflict = (field: string, value: unknown) => {
    const selected = field === 'year' ? (typeof value === 'number' ? value : null) : Array.isArray(value) ? value.join('; ') : value == null ? '' : String(value);
    update(field as keyof PaperMetadataPreview, selected);
  };
  const select = async (next: File) => {
    setFile(next); setMetadata(null); setError(''); setBusy('extract');
    try { setMetadata(await previewPaperMetadata(next)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(''); }
  };
  const save = async () => {
    if (!file || !metadata || !metadata.title.trim()) return;
    setBusy('save'); setError('');
    try { await savePaperWithMetadata(file, topicId, metadata); setFile(null); setMetadata(null); onSaved(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(''); }
  };
  return <>
    <div className="upload-icon"><Upload/></div>
    <div className="card-title">{t('Add a research paper')}</div>
    <div className="card-sub">{t('Choose a PDF to extract and review its metadata before indexing.')}</div>
    <label className="button primary paper-pick-button"><Upload size={14}/>{t('Choose PDF')}<input type="file" accept="application/pdf" hidden onChange={event => { const next = event.target.files?.[0]; if (next) void select(next); event.currentTarget.value = ''; }}/></label>
    <small className="paper-upload-limit">{t('PDF up to 50 MB and 500 pages')}</small>
    {busy === 'extract' && <div className="paper-extract-state"><LoaderCircle size={16} className="spin"/>{t('Reading PDF and checking DOI metadata…')}</div>}
    {error && <div className="error paper-flow-error" role="alert">{t('Could not read or save the PDF')}: {error}</div>}
    {metadata && file && <div className="paper-review-backdrop" role="presentation">
      <section className="paper-review-dialog" role="dialog" aria-modal="true" aria-labelledby="paper-review-title">
        <header><span className="paper-review-mark"><BookOpen size={18}/></span><div><h2 id="paper-review-title">{t('Review paper details')}</h2><small>{file.name} · {t('Extracted fields are editable before saving')}</small></div><button type="button" aria-label={t('Close')} className="paper-close" onClick={() => { setFile(null); setMetadata(null); setError(''); }}><X size={18}/></button></header>
        {!!metadata.warnings.length && <div className="paper-review-warnings"><b>{t('Review needed')}</b>{metadata.warnings.map((warning, index) => <p key={index}>{t(warning)}</p>)}</div>}
        {!!Object.keys(metadata.conflicts).length && <div className="paper-review-warnings"><b>{t('PDF and Crossref values differ')}</b>{Object.entries(metadata.conflicts).map(([key, values]) => <div className="paper-conflict" key={key}><p><strong>{t(key)}:</strong> PDF · {String(values.pdf)} / Crossref · {String(values.crossref)}</p><div><button type="button" onClick={() => chooseConflict(key, values.pdf)}>{t('Use PDF value')}</button><button type="button" onClick={() => chooseConflict(key, values.crossref)}>{t('Use Crossref value')}</button></div></div>)}</div>}
        <div className="paper-meta-grid">
          <label className="paper-meta-field paper-meta-wide"><span>{t('Title')} <em>*</em></span><input value={metadata.title} onChange={event => update('title', event.target.value)} required/>{metadata.metadata_sources.title && <small>{t('Source')}: {t(metadata.metadata_sources.title)}</small>}</label>
          <label className="paper-meta-field paper-meta-wide"><span>{t('Authors')}</span><input value={metadata.authors} onChange={event => update('authors', event.target.value)} placeholder={t('Authors not found')}/>{metadata.metadata_sources.authors && <small>{t('Source')}: {t(metadata.metadata_sources.authors)}</small>}</label>
          <label className="paper-meta-field"><span>{t('Publication year')}</span><input type="number" min="1500" max="2100" value={metadata.year ?? ''} onChange={event => update('year', event.target.value ? Number(event.target.value) : null)} placeholder="—"/>{metadata.metadata_sources.year && <small>{t('Source')}: {t(metadata.metadata_sources.year)}</small>}</label>
          <label className="paper-meta-field"><span>DOI</span><input value={metadata.doi ?? ''} onChange={event => update('doi', event.target.value)} placeholder="10.xxxx/..."/>{metadata.metadata_sources.doi && <small>{t('Source')}: {t(metadata.metadata_sources.doi)}</small>}</label>
          <label className="paper-meta-field paper-meta-wide"><span>{t('Original abstract')}</span><textarea rows={6} value={metadata.abstract ?? ''} onChange={event => update('abstract', event.target.value)} placeholder={t('Abstract not found in the PDF or Crossref record')}/>{metadata.metadata_sources.abstract && <small>{t('Source')}: {t(metadata.metadata_sources.abstract)} · {t('Original text, separate from the AI summary')}</small>}</label>
        </div>
        <footer><span><FileText size={14}/>{t('The PDF will be indexed and linked to this research topic.')}</span><button type="button" className="button outline" disabled={busy !== ''} onClick={() => { setFile(null); setMetadata(null); }}>{t('Cancel')}</button><button type="button" className="button primary" disabled={busy !== '' || !metadata.title.trim()} onClick={() => void save()}>{busy === 'save' ? <LoaderCircle size={14} className="spin"/> : <Check size={14}/>} {busy === 'save' ? t('Saving paper…') : t('Save and index paper')}</button></footer>
      </section>
    </div>}
  </>;
}
