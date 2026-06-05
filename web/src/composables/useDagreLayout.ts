import type { Edge, Node } from '@vue-flow/core'
import dagre from 'dagre'

export interface DagreLayoutOptions {
  rankdir?: 'TB' | 'BT' | 'LR' | 'RL'
  ranksep?: number
  nodesep?: number
  marginx?: number
  marginy?: number
}

const NODE_WIDTH = 240
const NODE_HEIGHT = 100

export function useDagreLayout() {
  function applyLayout(
    nodes: Node[],
    edges: Edge[],
    options: DagreLayoutOptions = {},
  ): Node[] {
    const {
      rankdir = 'TB',
      ranksep = 60,
      nodesep = 40,
      marginx = 20,
      marginy = 20,
    } = options

    const g = new dagre.graphlib.Graph()
    g.setDefaultEdgeLabel(() => ({}))
    g.setGraph({ rankdir, ranksep, nodesep, marginx, marginy })

    for (const node of nodes) {
      g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT })
    }

    for (const edge of edges) {
      if (edge.source && edge.target) {
        g.setEdge(edge.source, edge.target)
      }
    }

    dagre.layout(g)

    return nodes.map((node) => {
      const pos = g.node(node.id)
      if (!pos) {
        return node
      }
      return {
        ...node,
        position: {
          x: pos.x - NODE_WIDTH / 2,
          y: pos.y - NODE_HEIGHT / 2,
        },
      }
    })
  }

  return { applyLayout }
}
