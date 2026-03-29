import { reactive, onMounted, onUnmounted } from "vue";
import { useWebSocket } from "./useWebSocket";
import type { SessionStats, EfficiencyStats, CacheStats, ClusterState, CodingSession } from "@/interfaces";

function defaultSession(): SessionStats {
    return {
        tool_calls: 0,
        duration: "0s",
        duration_seconds: 0,
        symbols_retrieved: 0,
        sections_retrieved: 0,
        queries: 0,
        start_time: "",
        tokens_returned: 0,
        tokens_avoided: 0,
    };
}

function defaultEfficiency(): EfficiencyStats {
    return {
        total_returned: 0,
        total_equivalent: 0,
        reduction_percent: 0,
        by_category: {},
    };
}

function defaultCache(): CacheStats {
    return { hits: 0, misses: 0, size: 0, hit_rate: 0 };
}

function defaultCluster(): ClusterState {
    return {
        role: "",
        session_id: "",
        coding_session_id: "",
        nodes: [],
        active_count: 0,
        total_tool_calls: 0,
    };
}

export function useStats() {
    const session = reactive<SessionStats>(defaultSession());
    const efficiency = reactive<EfficiencyStats>(defaultEfficiency());
    const cache = reactive<CacheStats>(defaultCache());
    const cluster = reactive<ClusterState>(defaultCluster());
    const codingHistory = reactive<CodingSession[]>([]);
    const loading = reactive({ value: true });

    const { request, on, off } = useWebSocket();

    function applyStats(data: unknown) {
        const d = data as Record<string, unknown>;
        if (d.session) Object.assign(session, d.session);
        if (d.efficiency) Object.assign(efficiency, d.efficiency);
        if (d.cache) Object.assign(cache, d.cache);
        if (d.cluster) Object.assign(cluster, d.cluster);
        if (d.coding_history) {
            codingHistory.splice(0, codingHistory.length, ...(d.coding_history as CodingSession[]));
        }
    }

    function onToolCall(data: unknown) {
        const d = data as Record<string, unknown>;
        if (d.session) Object.assign(session, d.session);
        if (d.efficiency) Object.assign(efficiency, d.efficiency);
    }

    async function fetch() {
        try {
            const data = await request("get_stats");
            applyStats(data);
        } finally {
            loading.value = false;
        }
    }

    onMounted(() => {
        fetch();
        on("tool_call", onToolCall);
        on("stats_update", applyStats);
    });

    onUnmounted(() => {
        off("tool_call", onToolCall);
        off("stats_update", applyStats);
    });

    return { session, efficiency, cache, cluster, codingHistory, loading };
}
