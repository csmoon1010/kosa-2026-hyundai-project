import '@xyflow/react/dist/style.css';

import {
  Background,
  BackgroundVariant,
  BaseEdge,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeChange,
  type NodeProps,
} from '@xyflow/react';
import { useEffect, useState, type DragEvent, type KeyboardEvent } from 'react';

import { NH, NW, VB, geom, key, type GState, type Sel, type View } from './editorModel';
import styles from './graph.module.css';

export const PALETTE_TYPE = 'application/x-graph-state';

type StateData = {
  code: string;
  name: string;
  on: boolean;
  ext: boolean;
  onRemove: (c: string) => void;
  onPick: (c: string) => void;
};
type FlowData = {
  a: { x: number; y: number };
  b: { x: number; y: number };
  both: boolean;
  label: string;
  color: string;
  dash: string;
  on: boolean;
};
type StateNodeT = Node<StateData, 'state'>;
type FlowEdgeT = Edge<FlowData, 'flow'>;

/** 상태 상자 — 코드 · 이름, 고르면 × (캔버스에서 빼기), 오른쪽 ● 을 끌어 화살표 */
function StateNode({ data }: NodeProps<StateNodeT>) {
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      data.onPick(data.code);
    }
  };
  return (
    <div
      className={`${styles.node} ${data.on ? styles.on : ''} ${data.ext ? styles.ext : ''}`}
      role="button"
      tabIndex={0}
      aria-label={`${data.code} ${data.name}`}
      onKeyDown={onKey}
    >
      <Handle type="target" position={Position.Left} className={styles.target} isConnectableStart={false} />
      <b>{data.code}</b>
      <span>{data.name}</span>
      {data.on && (
        <button
          type="button"
          className={`${styles.xbtn} nodrag`}
          title="캔버스에서 빼기 (Delete)"
          aria-label={`${data.code} ${data.name} 캔버스에서 빼기`}
          onClick={(e) => {
            e.stopPropagation();
            data.onRemove(data.code);
          }}
        >
          ×
        </button>
      )}
      <Handle type="source" position={Position.Right} className={styles.port} title="끌어서 화살표 만들기" />
    </div>
  );
}

/** 화살표 — 반대 방향 화살표가 있으면 휘게, 가운데에 업무 이름 */
function FlowEdge({ id, data, markerEnd }: EdgeProps<FlowEdgeT>) {
  if (!data) return null;
  const g = geom(data.a, data.b, data.both);
  return (
    <>
      <BaseEdge
        id={id}
        path={g.d}
        markerEnd={markerEnd}
        interactionWidth={18}
        style={{
          stroke: data.color,
          strokeWidth: data.on ? 3.4 : 1.9,
          strokeDasharray: data.dash || undefined,
        }}
      />
      <text
        x={g.lx}
        y={g.ly + 4}
        textAnchor="middle"
        className={styles.edgeLabel}
        style={{ fill: data.color, fontWeight: data.on ? 700 : 500 }}
      >
        {data.label}
      </text>
    </>
  );
}

const nodeTypes = { state: StateNode };
const edgeTypes = { flow: FlowEdge };

export interface CanvasProps {
  graphId: string;
  s: GState;
  v: View;
  sel: Sel;
  label: string;
  onSelect: (sel: Sel) => void;
  onAdd: (code: string, p: { x: number; y: number }) => void;
  onMove: (code: string, p: { x: number; y: number }, done: boolean) => void;
  onConnect: (a: string, b: string) => void;
  onRemove: (code: string) => void;
}

/** 캔버스 — 상태를 끌어 옮기고, ● 을 끌어 다른 상태에 놓아 화살표, 팔레트에서 끌어다 놓기. 확대 · 미니맵 */
export function Canvas({
  graphId,
  s,
  v,
  sel,
  label,
  onSelect,
  onAdd,
  onMove,
  onConnect,
  onRemove,
}: CanvasProps) {
  const rf = useReactFlow();
  const [over, setOver] = useState(false);
  // 놓인 상태들에 맞춰 보여 준다 (최대 1배) — 없으면 캔버스 전체. 그래프를 바꿀 때마다
  const empty = Object.keys(s.nodes).length === 0;
  useEffect(() => {
    const t = window.setTimeout(() => {
      if (empty) void rf.fitBounds({ x: 0, y: 0, width: VB.w, height: VB.h }, { padding: 0.02 });
      else void rf.fitView({ padding: 0.25, maxZoom: 1 });
    }, 0);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 그래프가 바뀔 때만 (상태를 놓을 때마다 화면이 움직이지 않게)
  }, [graphId]);
  const pick = (c: string) => onSelect({ kind: 'node', id: c });

  const nodes: StateNodeT[] = v.placed().map((c) => ({
    id: c,
    type: 'state',
    position: { x: s.nodes[c]!.x, y: s.nodes[c]!.y },
    width: NW,
    height: NH,
    data: {
      code: c,
      name: v.NAME(c),
      on: sel.kind === 'node' && sel.id === c,
      ext: s.nodes[c]!.role === 'ext',
      onRemove,
      onPick: pick,
    },
  }));
  const edges: FlowEdgeT[] = s.edges
    .filter((e) => s.nodes[e.from] && s.nodes[e.to])
    .map((e) => {
      const k = key(e.from, e.to);
      const ext = v.isExternal(e);
      const [color, dash] = ext
        ? ['var(--muted)', '2 4']
        : !e.name
          ? ['var(--signal)', '6 4']
          : ['var(--accent)', ''];
      return {
        id: k,
        source: e.from,
        target: e.to,
        type: 'flow',
        markerEnd: { type: MarkerType.ArrowClosed, color, width: 14, height: 14 },
        data: {
          a: s.nodes[e.from]!,
          b: s.nodes[e.to]!,
          both: Boolean(v.edgeOf(key(e.to, e.from))),
          label: ext ? '외부' : e.name || '이름 없음',
          color,
          dash,
          on: sel.kind === 'edge' && sel.id === k,
        },
      };
    });

  const onNodesChange = (changes: NodeChange<StateNodeT>[]) => {
    for (const c of changes) if (c.type === 'position' && c.position) onMove(c.id, c.position, !c.dragging);
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    const code = e.dataTransfer.getData(PALETTE_TYPE);
    if (code) onAdd(code, rf.screenToFlowPosition({ x: e.clientX, y: e.clientY }));
  };

  return (
    <div
      className={`${styles.stage} ${over ? styles.over : ''}`}
      onDragOver={(e) => {
        if (!e.dataTransfer.types.includes(PALETTE_TYPE)) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
    >
      {!nodes.length && (
        <div className={styles.emptyhint}>
          <span>
            ① 왼쪽 공통코드에서 상태를 끌어다 놓고
            <br />② 상태 오른쪽 ● 을 끌어 다른 상태에 놓아 화살표를 만들고
            <br />③ 화살표를 눌러 업무에서 부르는 이름을 적으세요
          </span>
        </div>
      )}
      <ReactFlow
        aria-label={label}
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        nodeOrigin={[0.5, 0.5]}
        onNodesChange={onNodesChange}
        onConnect={(c) => c.source && c.target && onConnect(c.source, c.target)}
        onNodeClick={(_, n) => pick(n.id)}
        onEdgeClick={(_, e) => onSelect({ kind: 'edge', id: e.id })}
        onPaneClick={() => onSelect({ kind: 'none' })}
        connectionRadius={30}
        deleteKeyCode={null}
        selectionKeyCode={null}
        multiSelectionKeyCode={null}
        elementsSelectable={false}
        minZoom={0.3}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        colorMode="system"
      >
        <Background variant={BackgroundVariant.Dots} gap={25} size={1.1} />
        <Controls showInteractive={false} />
        <MiniMap
          pannable
          zoomable
          nodeColor="var(--accent-soft)"
          nodeStrokeColor="var(--accent)"
          style={{ width: 140, height: 90 }}
        />
      </ReactFlow>
    </div>
  );
}
