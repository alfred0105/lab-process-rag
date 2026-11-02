import { useEffect, useState } from 'react';
import { ArrowLeft } from 'lucide-react';
import MethodWorkspaceArchive from './MethodWorkspaceArchive';
import ProcessTimeline from './ProcessTimeline';
import { useLanguage } from '../language';
import type { ResearchTopic } from '../types';
export { TopicHome } from './MethodWorkspaceArchive';

type Props = { topic: ResearchTopic; onChanged: () => void; startRun?: boolean; onRunStarted?: () => void; startCreate?: boolean; onCreateStarted?: () => void; activeExperimentId?: number; initialMethodId?: number; initialVersionId?: number; openEditor?: boolean; onEditorOpened?: () => void };

export default function MethodWorkspace(props: Props) {
  const { topic, onChanged, startRun = false, onRunStarted, startCreate = false, onCreateStarted, openEditor = false, onEditorOpened } = props;
  const { t } = useLanguage();
  const [showArchive, setShowArchive] = useState(openEditor);
  const [launchRun, setLaunchRun] = useState(false);
  const [launchCreate, setLaunchCreate] = useState(false);

  useEffect(() => {
    if (startRun) { setShowArchive(true); setLaunchRun(true); }
  }, [startRun]);
  useEffect(() => {
    if (startCreate) { setShowArchive(true); setLaunchCreate(true); }
  }, [startCreate]);

  if (showArchive) return <div className="method-archive-view">
    <div className="method-archive-banner"><div><b>{t('Methods and runs')}</b><small>{t('Edit reusable methods, create versions, and record experiments.')}</small></div><button className="button outline small" onClick={() => { setShowArchive(false); setLaunchRun(false); setLaunchCreate(false); }}><ArrowLeft size={14}/>{t('Return to process timeline')}</button></div>
    <MethodWorkspaceArchive topic={topic} onChanged={onChanged} initialMethodId={props.initialMethodId} initialVersionId={props.initialVersionId} openEditor={openEditor} onEditorOpened={onEditorOpened} startRun={startRun || launchRun} onRunStarted={() => { setLaunchRun(false); onRunStarted?.(); }} startCreate={startCreate || launchCreate} onCreateStarted={() => { setLaunchCreate(false); onCreateStarted?.(); }}/>
  </div>;

  return <ProcessTimeline topic={topic} onArchive={() => setShowArchive(true)} onChanged={onChanged} activeExperimentId={props.activeExperimentId}/>;
}
