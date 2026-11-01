import { useEffect, useState } from 'react';
import { ArrowLeft } from 'lucide-react';
import MethodWorkspaceArchive from './MethodWorkspaceArchive';
import ProcessTimeline from './ProcessTimeline';
import { useLanguage } from '../language';
import type { ResearchTopic } from '../types';
export { TopicHome } from './MethodWorkspaceArchive';

type Props = { topic: ResearchTopic; onChanged: () => void; startRun?: boolean; onRunStarted?: () => void; startCreate?: boolean; onCreateStarted?: () => void; activeExperimentId?: number };

export default function MethodWorkspace(props: Props) {
  const { topic, onChanged, startRun = false, onRunStarted, startCreate = false, onCreateStarted } = props;
  const { t } = useLanguage();
  const [showArchive, setShowArchive] = useState(false);
  const [launchRun, setLaunchRun] = useState(false);
  const [launchCreate, setLaunchCreate] = useState(false);

  useEffect(() => {
    if (startRun) { setShowArchive(true); setLaunchRun(true); }
  }, [startRun]);
  useEffect(() => {
    if (startCreate) { setShowArchive(true); setLaunchCreate(true); }
  }, [startCreate]);

  if (showArchive) return <div className="method-archive-view">
    <div className="method-archive-banner"><div><b>{t('Archived method screen')}</b><small>{t('This is the previous method and run-entry screen, kept available as an archive.')}</small></div><button className="button outline small" onClick={() => { setShowArchive(false); setLaunchRun(false); setLaunchCreate(false); }}><ArrowLeft size={14}/>{t('Return to process timeline')}</button></div>
    <MethodWorkspaceArchive topic={topic} onChanged={onChanged} startRun={startRun || launchRun} onRunStarted={() => { setLaunchRun(false); onRunStarted?.(); }} startCreate={startCreate || launchCreate} onCreateStarted={() => { setLaunchCreate(false); onCreateStarted?.(); }}/>
  </div>;

  return <ProcessTimeline topic={topic} onArchive={() => setShowArchive(true)} onChanged={onChanged} activeExperimentId={props.activeExperimentId}/>;
}
