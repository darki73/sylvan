<script setup lang="ts">
import { useOverview } from "@/composables/useOverview";
import MetricCard from "@/components/MetricCard.vue";
import EfficiencyRing from "@/components/EfficiencyRing.vue";
import ActivityHeatmap from "@/components/ActivityHeatmap.vue";

const { data, recentCalls, loading } = useOverview();

function timeAgo(iso: string): string {
    const diff = Date.now() - new Date(iso).getTime();
    const secs = Math.floor(diff / 1000);
    if (secs < 60) return `${secs}s ago`;
    const mins = Math.floor(secs / 60);
    if (mins < 60) return `${mins}m ago`;
    return `${Math.floor(mins / 60)}h ago`;
}
</script>

<template>
    <div>
        <div class="flex items-center justify-between mb-8 animate-in">
            <div>
                <h1 class="text-2xl font-bold text-white tracking-tight">Mission Control</h1>
                <p class="text-sm text-text-dim mt-1 uppercase tracking-wider">
                    {{ data.total_repos }} repos &middot;
                    {{ data.total_symbols.toLocaleString() }} symbols &middot;
                    {{ data.total_files.toLocaleString() }} files indexed
                </p>
            </div>
            <div v-if="data.uptime" class="text-right">
                <div class="text-[10px] text-text-faint uppercase tracking-wider">Uptime</div>
                <div class="font-mono text-sm text-white">{{ data.uptime }}</div>
            </div>
        </div>

        <div v-if="loading" class="flex items-center gap-3 text-text-dim text-sm py-20 justify-center">
            <div class="w-4 h-4 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
            Loading dashboard...
        </div>

        <template v-else>
            <div class="flex gap-5 flex-wrap mb-6" v-if="data.efficiency.total_equivalent > 0 || data.alltime_efficiency.total_equivalent > 0">
                <EfficiencyRing
                    v-if="data.efficiency.total_equivalent > 0"
                    :efficiency="data.efficiency"
                    :tool-calls="data.tool_calls"
                    label="This Session"
                    class="flex-1 min-w-[400px] animate-in delay-1"
                />
                <EfficiencyRing
                    v-if="data.alltime_efficiency.total_equivalent > 0"
                    :efficiency="{
                        total_returned: data.alltime_efficiency.total_returned,
                        total_equivalent: data.alltime_efficiency.total_equivalent,
                        reduction_percent: data.alltime_efficiency.reduction_percent,
                        by_category: {},
                    }"
                    :tool-calls="data.alltime_efficiency.total_calls"
                    label="All Time"
                    class="flex-1 min-w-[400px] animate-in delay-2"
                />
            </div>

            <div class="grid grid-cols-5 gap-4 mb-8 animate-in delay-3">
                <MetricCard label="Repositories" :value="data.total_repos" />
                <MetricCard label="Libraries" :value="data.total_libraries" />
                <MetricCard label="Symbols" :value="data.total_symbols.toLocaleString()" accent />
                <MetricCard label="Files" :value="data.total_files.toLocaleString()" />
                <MetricCard label="Sections" :value="data.total_sections.toLocaleString()" />
            </div>

            <div class="grid grid-cols-2 gap-5 animate-in delay-4">
                <div>
                    <div class="flex items-center gap-3 mb-3">
                        <h2 class="text-xs font-bold text-text-dim uppercase tracking-[0.15em]">Recent Activity</h2>
                        <div class="flex-1 h-px bg-border" />
                    </div>
                    <div v-if="recentCalls.length" class="space-y-1">
                        <div
                            v-for="(call, i) in recentCalls"
                            :key="i"
                            class="flex items-center justify-between px-3 py-2 rounded-lg bg-surface border border-border text-xs"
                        >
                            <div class="flex items-center gap-2">
                                <span class="font-mono text-white font-medium">{{ call.name }}</span>
                                <span v-if="call.repo" class="text-text-faint">{{ call.repo }}</span>
                            </div>
                            <div class="flex items-center gap-3 text-text-faint">
                                <span v-if="call.duration_ms != null" class="font-mono">{{ call.duration_ms < 1 ? '<1' : call.duration_ms }}ms</span>
                                <span class="font-mono">{{ timeAgo(call.timestamp) }}</span>
                            </div>
                        </div>
                    </div>
                    <div v-else class="text-xs text-text-faint py-8 text-center bg-surface rounded-lg border border-border">
                        No tool calls yet this session
                    </div>
                </div>

                <div>
                    <div class="flex items-center gap-3 mb-3">
                        <h2 class="text-xs font-bold text-text-dim uppercase tracking-[0.15em]">Cluster</h2>
                        <div class="flex-1 h-px bg-border" />
                    </div>
                    <div class="bg-surface rounded-lg border border-border p-4">
                        <div v-if="data.cluster" class="space-y-3">
                            <div class="flex items-center justify-between">
                                <span class="text-xs text-text-dim">Role</span>
                                <span
                                    class="px-2 py-0.5 text-[10px] font-mono rounded"
                                    :class="data.cluster.role === 'leader' ? 'bg-accent/15 text-accent' : 'bg-info/15 text-info'"
                                >
                                    {{ data.cluster.role }}
                                </span>
                            </div>
                            <div class="flex items-center justify-between">
                                <span class="text-xs text-text-dim">Active nodes</span>
                                <span class="font-mono text-sm text-white">{{ data.cluster.active_count }}</span>
                            </div>
                            <div class="flex items-center justify-between">
                                <span class="text-xs text-text-dim">Session</span>
                                <span class="font-mono text-[10px] text-text-faint">{{ data.cluster.session_id }}</span>
                            </div>
                            <div v-if="data.cluster.nodes?.length" class="pt-2 border-t border-border space-y-1.5">
                                <div
                                    v-for="node in data.cluster.nodes"
                                    :key="node.session_id"
                                    class="flex items-center justify-between text-[10px]"
                                >
                                    <div class="flex items-center gap-1.5">
                                        <div
                                            class="w-1.5 h-1.5 rounded-full"
                                            :class="node.alive ? 'bg-accent' : 'bg-danger'"
                                        />
                                        <span class="font-mono text-text-dim">{{ node.session_id.slice(0, 8) }}</span>
                                    </div>
                                    <span
                                        class="font-mono"
                                        :class="node.role === 'leader' ? 'text-accent' : 'text-text-faint'"
                                    >
                                        {{ node.role }}
                                    </span>
                                </div>
                            </div>
                        </div>
                        <div v-else class="text-xs text-text-faint text-center py-4">
                            Cluster not available
                        </div>
                    </div>
                </div>
            </div>

            <!-- Activity heatmap -->
            <div v-if="data.usage_map && Object.keys(data.usage_map).length" class="mt-6 animate-in">
                <div class="flex items-center gap-3 mb-3">
                    <h2 class="text-xs font-bold text-text-dim uppercase tracking-[0.15em]">Activity</h2>
                    <div class="flex-1 h-px bg-border" />
                </div>
                <div class="bg-surface rounded-lg border border-border p-4">
                    <ActivityHeatmap :data="data.usage_map" label="Tool calls across all repos" />
                </div>
            </div>
        </template>
    </div>
</template>
