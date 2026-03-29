<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import { useStats } from "@/composables/useStats";
import MetricCard from "@/components/MetricCard.vue";
import EfficiencyRing from "@/components/EfficiencyRing.vue";
import ClusterTable from "@/components/ClusterTable.vue";

const { session, cluster, efficiency, cache, codingHistory, loading } = useStats();

const liveDuration = ref("0s");
let durationBase = 0;
let durationFetchedAt = 0;
let durationTimer: ReturnType<typeof setInterval> | null = null;

function formatDuration(secs: number): string {
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    const s = Math.floor(secs % 60);
    if (h > 0) return `${h}h ${m}m ${s}s`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
}

function tickDuration() {
    const elapsed = Math.floor((Date.now() - durationFetchedAt) / 1000);
    liveDuration.value = formatDuration(durationBase + elapsed);
}

onMounted(() => {
    const checkReady = setInterval(() => {
        if (session.duration_seconds != null && session.duration_seconds > 0) {
            durationBase = session.duration_seconds;
            durationFetchedAt = Date.now();
            tickDuration();
            clearInterval(checkReady);
        }
    }, 200);
    durationTimer = setInterval(tickDuration, 1000);
});

onUnmounted(() => {
    if (durationTimer) clearInterval(durationTimer);
});

const categoryDefs: [string, string, string][] = [
    ["search", "Search", "var(--color-info)"],
    ["retrieval", "Retrieval", "var(--color-accent)"],
    ["analysis", "Analysis", "var(--color-purple)"],
    ["indexing", "Indexing", "var(--color-warning)"],
    ["meta", "Meta", "var(--color-text-faint)"],
];

function catSaved(key: string): number {
    const cat = efficiency.by_category?.[key];
    if (!cat) return 0;
    return cat.equivalent - cat.returned;
}

function catPct(key: string): number {
    const cat = efficiency.by_category?.[key];
    if (!cat || !efficiency.total_equivalent) return 0;
    return Math.round((cat.equivalent / efficiency.total_equivalent) * 100);
}
</script>

<template>
    <div>
        <div class="flex items-center justify-between mb-8 animate-in">
            <div>
                <h1 class="text-2xl font-bold text-white tracking-tight">Session</h1>
                <p class="text-sm text-text-dim mt-1 uppercase tracking-wider">
                    Live MCP session metrics
                    <template v-if="cluster.role">
                        - {{ cluster.role }}
                        <span v-if="cluster.session_id">({{ cluster.session_id }})</span>
                    </template>
                </p>
            </div>
            <span
                v-if="cluster.role"
                class="px-3 py-1 text-xs font-mono font-bold rounded"
                :class="cluster.role === 'leader' ? 'bg-accent text-bg' : 'bg-info text-bg'"
            >
                {{ cluster.role }}
            </span>
        </div>

        <div class="grid grid-cols-4 gap-4 mb-8 animate-in delay-1">
            <MetricCard
                label="Tool Calls"
                :value="cluster.active_count > 1 ? (cluster.total_tool_calls ?? 0) : (session.tool_calls ?? 0)"
                glow
            />
            <MetricCard label="Duration" :value="liveDuration" />
            <MetricCard label="Tokens Saved" :value="(session.tokens_avoided ?? 0).toLocaleString()" accent />
            <MetricCard label="Search Queries" :value="session.queries ?? 0" />
        </div>

        <div v-if="efficiency.total_equivalent > 0" class="mb-8 animate-in delay-2">
            <EfficiencyRing :efficiency="efficiency" label="Token Efficiency This Session" />
        </div>
        <div v-else class="rounded-xl bg-surface border border-border p-8 text-center mb-8 animate-in delay-2">
            <div class="text-[10px] text-text-faint uppercase tracking-widest mb-1">Token Efficiency</div>
            <div class="text-sm text-text-dim">No tool calls with token data yet this session</div>
        </div>

        <div v-if="efficiency.by_category && Object.keys(efficiency.by_category).length" class="mb-8 animate-in delay-3">
            <div class="flex items-center gap-3 mb-3">
                <h2 class="text-xs font-bold text-text-dim uppercase tracking-[0.15em]">Efficiency by Category</h2>
                <div class="flex-1 h-px bg-border" />
            </div>
            <div class="rounded-xl bg-surface border border-border p-5 space-y-4">
                <template v-for="[key, label, color] in categoryDefs" :key="key">
                    <div v-if="efficiency.by_category[key]?.calls > 0" class="flex items-center gap-4">
                        <div class="w-20 font-mono text-xs font-medium" :style="{ color }">{{ label }}</div>
                        <div class="flex-1">
                            <div class="h-2 rounded-full bg-surface-3 overflow-hidden">
                                <div
                                    class="h-full rounded-full transition-all duration-700"
                                    :style="{ width: catPct(key) + '%', background: color }"
                                />
                            </div>
                        </div>
                        <div class="min-w-[160px] text-right">
                            <span class="font-mono text-xs text-text-dim">{{ efficiency.by_category[key].calls }} calls</span>
                            <span class="font-mono text-xs ml-2" :style="{ color }">{{ catSaved(key).toLocaleString() }} saved</span>
                        </div>
                    </div>
                </template>
            </div>
        </div>

        <ClusterTable v-if="cluster.nodes?.length" :nodes="cluster.nodes" class="mb-8 animate-in delay-4" />

        <div v-if="codingHistory.length" class="mb-8 animate-in delay-5">
            <div class="flex items-center gap-3 mb-3">
                <h2 class="text-xs font-bold text-text-dim uppercase tracking-[0.15em]">Coding Session History</h2>
                <div class="flex-1 h-px bg-border" />
            </div>
            <div class="rounded-xl border border-border overflow-hidden">
                <table class="w-full text-sm">
                    <thead>
                        <tr class="bg-surface-2 text-[10px] text-text-faint uppercase tracking-wider">
                            <th class="px-4 py-2 text-left font-medium">Session</th>
                            <th class="px-4 py-2 text-left font-medium">Date</th>
                            <th class="px-4 py-2 text-right font-medium">Duration</th>
                            <th class="px-4 py-2 text-right font-medium">Instances</th>
                            <th class="px-4 py-2 text-right font-medium">Calls</th>
                            <th class="px-4 py-2 text-right font-medium">Efficiency</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr
                            v-for="cs in codingHistory"
                            :key="cs.id"
                            class="border-t border-border hover:bg-surface/80 transition-colors"
                            :class="!cs.ended_at ? 'text-accent' : ''"
                        >
                            <td class="px-4 py-2 font-mono text-xs">{{ cs.id.slice(0, 20) }}</td>
                            <td class="px-4 py-2 font-mono text-xs text-text-dim">{{ cs.started_at?.slice(0, 10) }}</td>
                            <td class="px-4 py-2 font-mono text-xs text-right">{{ cs.duration }}</td>
                            <td class="px-4 py-2 font-mono text-xs text-right">{{ cs.instances_spawned }}</td>
                            <td class="px-4 py-2 font-mono text-xs text-right">{{ cs.total_tool_calls }}</td>
                            <td class="px-4 py-2 font-mono text-xs text-right" :class="cs.reduction_percent > 0 ? 'text-accent' : 'text-text-faint'">
                                {{ cs.reduction_percent }}%
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>

        <div v-if="cache" class="animate-in delay-5">
            <div class="flex items-center gap-3 mb-3">
                <h2 class="text-xs font-bold text-text-dim uppercase tracking-[0.15em]">Query Cache</h2>
                <div class="flex-1 h-px bg-border" />
            </div>
            <div class="grid grid-cols-4 gap-4">
                <MetricCard label="Hits" :value="cache.hits ?? 0" />
                <MetricCard label="Misses" :value="cache.misses ?? 0" />
                <MetricCard label="Entries" :value="cache.size ?? 0" />
                <MetricCard label="Hit Rate" :value="`${cache.hit_rate ?? 0}%`" :accent="(cache.hit_rate ?? 0) > 50" />
            </div>
        </div>
    </div>
</template>
