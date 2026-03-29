import { reactive, ref, onMounted, onUnmounted } from "vue";
import { useWebSocket } from "./useWebSocket";
import type { OverviewData, ToolCallEvent } from "@/interfaces";

function defaultOverview(): OverviewData {
    return {
        repos: [],
        libraries: [],
        total_symbols: 0,
        total_files: 0,
        total_sections: 0,
        total_repos: 0,
        total_libraries: 0,
        efficiency: {
            total_returned: 0,
            total_equivalent: 0,
            reduction_percent: 0,
            by_category: {},
        },
        alltime_efficiency: {
            total_returned: 0,
            total_equivalent: 0,
            total_calls: 0,
            reduction_percent: 0,
        },
        tool_calls: 0,
        uptime: "0s",
    };
}

function formatUptime(seconds: number): string {
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    if (days > 0) return `${days}d ${hours}h ${minutes}m`;
    if (hours > 0) return `${hours}h ${minutes}m ${secs}s`;
    if (minutes > 0) return `${minutes}m ${secs}s`;
    return `${secs}s`;
}

const MAX_RECENT = 10;

export function useOverview() {
    const data = reactive<OverviewData>(defaultOverview());
    const recentCalls = reactive<ToolCallEvent[]>([]);
    const loading = ref(true);
    const error = ref<string | null>(null);

    const { request, on, off } = useWebSocket();

    let uptimeBase = 0;
    let uptimeFetchedAt = 0;
    let uptimeTimer: ReturnType<typeof setInterval> | null = null;

    function tickUptime() {
        const elapsed = Math.floor((Date.now() - uptimeFetchedAt) / 1000);
        data.uptime = formatUptime(uptimeBase + elapsed);
    }

    function onToolCall(eventData: unknown) {
        const d = eventData as Record<string, unknown>;
        if (d.efficiency) Object.assign(data.efficiency, d.efficiency);
        if (d.session) {
            const s = d.session as Record<string, number>;
            data.tool_calls = s.tool_calls ?? data.tool_calls;
        }
        recentCalls.unshift({
            name: d.name as string,
            timestamp: d.timestamp as string,
            repo: d.repo as string | undefined,
            duration_ms: d.duration_ms as number | undefined,
        });
        if (recentCalls.length > MAX_RECENT) recentCalls.pop();
    }

    async function fetch() {
        loading.value = true;
        error.value = null;
        try {
            const result = await request<OverviewData & { recent_calls?: ToolCallEvent[]; uptime_seconds?: number }>("get_overview");
            const calls = result.recent_calls ?? [];
            const serverUptime = result.uptime_seconds ?? 0;
            delete (result as unknown as Record<string, unknown>).recent_calls;
            delete (result as unknown as Record<string, unknown>).uptime_seconds;
            Object.assign(data, result);
            if (calls.length) {
                recentCalls.splice(0, recentCalls.length, ...calls.slice(0, MAX_RECENT));
            }
            uptimeBase = serverUptime;
            uptimeFetchedAt = Date.now();
            tickUptime();
        } catch (e) {
            error.value = (e as Error).message;
        } finally {
            loading.value = false;
        }
    }

    onMounted(() => {
        fetch();
        on("tool_call", onToolCall);
        uptimeTimer = setInterval(tickUptime, 1000);
    });

    onUnmounted(() => {
        off("tool_call", onToolCall);
        if (uptimeTimer) clearInterval(uptimeTimer);
    });

    return { data, recentCalls, loading, error, refresh: fetch };
}
