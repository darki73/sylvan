import type { EfficiencyStats } from "./session";
import type { ClusterNode } from "./cluster";

export interface RepoStats {
    name: string;
    files: number;
    symbols: number;
    sections: number;
    indexed_at: string;
    git_head: string;
    languages?: Record<string, number>;
}

export interface LibraryVersion {
    name: string;
    package: string;
    manager: string;
    version: string;
    files: number;
    symbols: number;
    sections: number;
    repo_url: string;
    indexed_at: string;
    languages: Record<string, number>;
}

export interface GroupedLibrary {
    package: string;
    manager: string;
    repo_url: string;
    versions: LibraryVersion[];
    total_symbols: number;
}

export interface AlltimeStats {
    total_returned: number;
    total_equivalent: number;
    total_calls: number;
    reduction_percent: number;
}

export interface ClusterMini {
    role: string;
    session_id: string;
    nodes: ClusterNode[];
    active_count: number;
}

export interface ToolCallEvent {
    name: string;
    timestamp: string;
    repo?: string;
    duration_ms?: number;
}

export interface OverviewData {
    repos: RepoStats[];
    libraries: LibraryVersion[];
    total_symbols: number;
    total_files: number;
    total_sections: number;
    total_repos: number;
    total_libraries: number;
    efficiency: EfficiencyStats;
    alltime_efficiency: AlltimeStats;
    tool_calls: number;
    cluster?: ClusterMini;
    uptime?: string;
    uptime_seconds?: number;
    usage_map?: Record<string, number>;
}
