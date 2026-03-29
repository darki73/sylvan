export interface ClusterNode {
  session_id: string;
  coding_session_id: string;
  pid: number;
  role: "leader" | "follower" | string;
  alive: boolean;
  tool_calls: number;
  tokens_returned: number;
  tokens_avoided: number;
  efficiency_returned: number;
  efficiency_equivalent: number;
  reduction_percent: number;
  symbols_retrieved: number;
  queries: number;
  last_heartbeat: string;
}

export interface ClusterState {
  role: string;
  session_id: string;
  coding_session_id: string;
  nodes: ClusterNode[];
  active_count: number;
  total_tool_calls: number;
}

export interface CodingSession {
  id: string;
  started_at: string;
  ended_at: string | null;
  duration: string;
  instances_spawned: number;
  total_tool_calls: number;
  reduction_percent: number;
}
