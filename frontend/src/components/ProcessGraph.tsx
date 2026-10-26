import { useMemo } from 'react';
import { Background, ReactFlow, type Edge, type Node } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { Experiment, Step } from '../types';
import { useLanguage } from '../language';

type ProcessMapStep = { name: string; description: string; step_type?: string };

export default function ProcessGraph({ experiment, processMap = [], onSelect }: { experiment: Experiment | null; processMap?: ProcessMapStep[]; onSelect: (step: Step) => void }) {
  const { t, language } = useLanguage();
  const steps = experiment?.steps ?? [];
  const graphSteps = steps.length ? steps : processMap;
  const { nodes, edges } = useMemo(() => {
    const nextNodes: Node[] = graphSteps.map((step, index) => {
      const variableCount = 'variables' in step ? (step as Step).variables.length : 0;
      return {
        id: String('id' in step ? step.id : `template-${index}`),
        position: { x: index * 192, y: 36 },
        data: { label: <div className="graph-node"><span className="graph-step-index">{String(index + 1).padStart(2, '0')}</span><div><strong>{step.name}</strong><small>{language === 'ko' ? `${variableCount}개 조건` : `${variableCount} conditions`}</small></div></div> },
        type: 'default',
      };
    });
    const nextEdges: Edge[] = graphSteps.slice(1).map((_, index) => ({
      id: `process-edge-${index}`,
      source: nextNodes[index].id,
      target: nextNodes[index + 1].id,
      type: 'smoothstep',
      animated: false,
      style: { stroke: '#9bcdbb', strokeWidth: 2 },
    }));
    return { nodes: nextNodes, edges: nextEdges };
  }, [graphSteps, language]);

  return <div className="graph">
    <ReactFlow nodes={nodes} edges={edges} fitView fitViewOptions={{ padding: 0.18 }} nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} minZoom={0.35} maxZoom={1.2} onNodeClick={(_, node) => {
      const step = steps.find(item => String(item.id) === node.id);
      if (step) onSelect(step);
    }}>
      <Background color="#e8efec" gap={22} size={1} />
    </ReactFlow>
    {!nodes.length && <div className="graph-empty">{t('Select a process to view its stages.')}</div>}
  </div>;
}
