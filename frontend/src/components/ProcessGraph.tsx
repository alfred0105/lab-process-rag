import { useMemo } from 'react';
import { Background, Position, ReactFlow, type Edge, type Node } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { Experiment, MethodVersion, Step } from '../types';
import { useLanguage } from '../language';

type ProcessMapStep = { name: string; description: string; step_type?: string };
type TrieNode = { id: string; depth: number; step?: ProcessMapStep; conditionCount?: number; version?: MethodVersion; children: TrieNode[]; parent?: TrieNode };
type Props = { experiment: Experiment | null; processMap?: ProcessMapStep[]; versions?: MethodVersion[]; currentVersionId?: number; onSelect: (step: Step) => void };

export default function ProcessGraph({ experiment, processMap = [], versions = [], currentVersionId, onSelect }: Props) {
  const { t, language } = useLanguage();
  const steps = experiment?.steps ?? [];
  const graphSteps = steps.length ? steps : processMap;
  const versionGraph = versions.length > 0;
  const { nodes, edges, height } = useMemo(() => {
    if (versions.length) {
      const root: TrieNode = { id: 'process-root', depth: 0, children: [] };
      const sortedVersions = [...versions].sort((a, b) => versionDepth(a, versions) - versionDepth(b, versions) || a.version_number - b.version_number);
      let nextId = 0;
      for (const version of sortedVersions) {
        let current = root;
        for (const stage of version.process_map) {
          const stageConditions = version.condition_definitions.filter(item => item.step_name === stage.name).map(item => [item.name, item.unit, item.value_type, item.required]).sort((a, b) => String(a[0]).localeCompare(String(b[0])));
          const signature = JSON.stringify([stage.name, stage.description, stage.step_type, stageConditions]);
          let child = current.children.find(item => item.step && item.id.endsWith(signature));
          if (!child) {
            child = { id: `stage-${nextId++}-${signature}`, depth: current.depth + 1, step: stage, conditionCount: stageConditions.length, children: [], parent: current };
            current.children.push(child);
          }
          current = child;
        }
        const endNode: TrieNode = { id: `version-end-${version.id}`, depth: current.depth + 1, version, children: [], parent: current };
        current.children.push(endNode);
      }

      let leafRow = 0;
      const yById = new Map<string, number>();
      const place = (node: TrieNode): number => {
        if (!node.children.length) { const y = 24 + leafRow++ * 104; yById.set(node.id, y); return y; }
        const childYs = node.children.map(place);
        const y = childYs.reduce((sum, value) => sum + value, 0) / childYs.length;
        yById.set(node.id, y);
        return y;
      };
      place(root);
      const nextNodes: Node[] = [];
      const nextEdges: Edge[] = [];
      const visit = (node: TrieNode) => {
        {
          const isRoot = node === root;
          const isCurrent = node.version?.id === currentVersionId;
          const isForkPoint = node.children.length > 1;
          const x = isRoot ? -194 : Math.max(0, node.depth - 1) * 194;
          const y = yById.get(node.id) ?? 24;
          const data = isRoot ? <div className="graph-tree-root-label">{t('Process start')}</div> : node.version
            ? <div className="graph-version-label"><strong>v{node.version.version_label ?? node.version.version_number}{isCurrent ? ` · ${t('Current main tree')}` : ''}</strong><small>{node.version.parent_version_id ? `${t('Branched from')} v${versions.find(item => item.id === node.version?.parent_version_id)?.version_label ?? versions.find(item => item.id === node.version?.parent_version_id)?.version_number ?? '?'}` : t('Base process')}</small><small>{node.version.created_at ? `${t(node.version.parent_version_id ? 'Branch date' : 'Version date')}: ${new Date(node.version.created_at).toLocaleDateString(language === 'ko' ? 'ko-KR' : 'en-US')}` : ''}</small></div>
            : <div className="graph-node"><span className="graph-step-index">{String(node.depth).padStart(2, '0')}</span><div><strong>{t(node.step?.name ?? '')}</strong><small>{language === 'ko' ? `${node.conditionCount ?? 0}개 조건` : `${node.conditionCount ?? 0} conditions`}</small></div></div>;
          nextNodes.push({ id: node.id, position: { x, y }, sourcePosition: Position.Right, targetPosition: Position.Left, className: isRoot ? 'graph-tree-root' : node.version ? `graph-version-node${isCurrent ? ' current' : ''}` : `graph-version-step${isForkPoint ? ' fork-point' : ''}`, data: { label: data, stepIndex: node.step ? node.depth - 1 : null }, type: 'default' });
        }
        for (const child of node.children) {
          {
            const isBranch = node.children.length > 1;
            nextEdges.push({ id: `tree-edge-${node.id}-${child.id}`, source: node.id, target: child.id, type: isBranch ? 'smoothstep' : 'straight', label: isBranch ? t('Branch') : undefined, labelStyle: isBranch ? { fill: '#8567a8', fontSize: 9, fontWeight: 700 } : undefined, style: isBranch ? { stroke: '#987cbb', strokeWidth: 2.2 } : { stroke: '#91c6b1', strokeWidth: 2 } });
          }
          visit(child);
        }
      };
      visit(root);
      return { nodes: nextNodes, edges: nextEdges, height: Math.max(238, leafRow * 104 + 35) };
    }

    const nextNodes: Node[] = graphSteps.map((step, index) => {
      const variableCount = 'variables' in step ? (step as Step).variables.length : 0;
      return { id: String('id' in step ? step.id : `template-${index}`), position: { x: index * 192, y: 36 }, sourcePosition: Position.Right, targetPosition: Position.Left, data: { label: <div className="graph-node"><span className="graph-step-index">{String(index + 1).padStart(2, '0')}</span><div><strong>{t(step.name)}</strong><small>{language === 'ko' ? `${variableCount}개 조건` : `${variableCount} conditions`}</small></div></div> }, type: 'default' };
    });
    const nextEdges: Edge[] = graphSteps.slice(1).map((_, index) => ({ id: `process-edge-${index}`, source: nextNodes[index].id, target: nextNodes[index + 1].id, type: 'straight', style: { stroke: '#9bcdbb', strokeWidth: 2 } }));
    return { nodes: nextNodes, edges: nextEdges, height: 238 };
  }, [currentVersionId, graphSteps, language, t, versions]);

  return <div className={`graph${versionGraph ? ' graph-version-tree' : ''}`} style={{ height }}>
    <ReactFlow nodes={nodes} edges={edges} fitView fitViewOptions={{ padding: 0.16, minZoom: 0.3, maxZoom: 1 }} nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} minZoom={0.22} maxZoom={1.2} onNodeClick={(_, node) => {
      if (node.id.startsWith('stage-')) {
        if (experiment?.method_version_id === currentVersionId && typeof node.data.stepIndex === 'number') { const step = steps.find(item => item.order_index === node.data.stepIndex); if (step) onSelect(step); }
        return;
      }
      const step = steps.find(item => String(item.id) === node.id);
      if (step) onSelect(step);
    }}>
      <Background color="#e8efec" gap={22} size={1} />
    </ReactFlow>
    {!nodes.length && <div className="graph-empty">{t('Select a process to view its stages.')}</div>}
  </div>;
}

function versionDepth(version: MethodVersion, versions: MethodVersion[]) {
  let depth = 0;
  let current: MethodVersion | undefined = version;
  const seen = new Set<number>();
  while (current?.parent_version_id && depth < versions.length && !seen.has(current.id)) {
    seen.add(current.id);
    current = versions.find(item => item.id === current?.parent_version_id);
    if (current) depth += 1;
  }
  return depth;
}
