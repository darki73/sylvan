<script setup lang="ts">
import { computed } from "vue";
import { useHistory } from "@/composables/useHistory";

const { sessions, loading, page, total, totalPages, goToPage } = useHistory(20);

const totalCalls = computed(() => sessions.reduce((sum, s) => sum + s.total_tool_calls, 0));
const avgEfficiency = computed(() => {
    const withData = sessions.filter(s => s.reduction_percent > 0);
    if (!withData.length) return 0;
    return Math.round(withData.reduce((sum, s) => sum + s.reduction_percent, 0) / withData.length);
});
const currentSession = computed(() => sessions.find(s => !s.ended_at));

const pageNumbers = computed(() => {
    const pages: number[] = [];
    const start = Math.max(1, page.value - 2);
    const end = Math.min(totalPages.value, page.value + 2);
    for (let i = start; i <= end; i++) pages.push(i);
    return pages;
});
</script>

<template>
    <div>
        <div class="mb-6 animate-in">
            <h1 class="text-2xl font-bold text-white tracking-tight">History</h1>
            <p class="text-sm text-text-dim mt-1">
                <span class="font-mono text-accent">{{ total }}</span> coding sessions
            </p>
        </div>

        <div v-if="loading" class="flex items-center gap-3 text-text-dim text-sm py-20 justify-center">
            <div class="w-4 h-4 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
            Loading...
        </div>

        <template v-else>
            <!-- Current session banner -->
            <div v-if="currentSession" class="rounded-xl bg-accent/5 border border-accent/20 p-4 mb-6 animate-in flex items-center gap-3">
                <div class="w-2 h-2 rounded-full bg-accent animate-pulse shrink-0" />
                <div class="text-sm">
                    <span class="text-accent font-mono">{{ currentSession.id.slice(0, 20) }}</span>
                    <span class="text-text-faint ml-2">active</span>
                    <span class="text-text-faint ml-2 font-mono">{{ currentSession.duration }}</span>
                    <span class="text-text-faint ml-2 font-mono">{{ currentSession.total_tool_calls }} calls</span>
                </div>
            </div>

            <!-- Sessions table -->
            <div class="rounded-xl bg-surface border border-border overflow-hidden animate-in">
                <table class="w-full text-xs">
                    <thead>
                        <tr class="text-text-faint border-b border-border">
                            <th class="px-5 py-2.5 text-left font-normal">Session</th>
                            <th class="px-3 py-2.5 text-left font-normal">Started</th>
                            <th class="px-3 py-2.5 text-right font-normal">Duration</th>
                            <th class="px-3 py-2.5 text-right font-normal">Nodes</th>
                            <th class="px-3 py-2.5 text-right font-normal">Tool Calls</th>
                            <th class="px-5 py-2.5 text-right font-normal">Efficiency</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr
                            v-for="cs in sessions"
                            :key="cs.id"
                            class="border-t border-border/50 hover:bg-surface-2/50 transition-colors"
                        >
                            <td class="px-5 py-2.5 font-mono">
                                <div class="flex items-center gap-2">
                                    <div
                                        v-if="!cs.ended_at"
                                        class="w-1.5 h-1.5 rounded-full bg-accent shrink-0"
                                    />
                                    <span :class="!cs.ended_at ? 'text-accent' : 'text-white'">{{ cs.id.slice(0, 20) }}</span>
                                </div>
                            </td>
                            <td class="px-3 py-2.5 font-mono text-text-dim">
                                {{ cs.started_at?.slice(0, 10) }}
                                <span class="text-text-faint ml-1">{{ cs.started_at?.slice(11, 16) }}</span>
                            </td>
                            <td class="px-3 py-2.5 font-mono text-text-dim text-right">{{ cs.duration }}</td>
                            <td class="px-3 py-2.5 font-mono text-text-dim text-right">{{ cs.instances_spawned }}</td>
                            <td class="px-3 py-2.5 font-mono text-white text-right">{{ cs.total_tool_calls.toLocaleString() }}</td>
                            <td class="px-5 py-2.5 font-mono text-right">
                                <span
                                    v-if="cs.reduction_percent > 0"
                                    class="px-1.5 py-0.5 rounded text-[10px]"
                                    :class="cs.reduction_percent >= 70 ? 'bg-accent/10 text-accent' : cs.reduction_percent >= 40 ? 'bg-amber-500/10 text-amber-400' : 'bg-surface-2 text-text-dim'"
                                >
                                    {{ cs.reduction_percent }}%
                                </span>
                                <span v-else class="text-text-faint">-</span>
                            </td>
                        </tr>
                    </tbody>
                </table>
                <div v-if="!sessions.length" class="text-xs text-text-faint py-8 text-center">
                    No coding sessions recorded
                </div>
            </div>

            <!-- Pagination -->
            <div v-if="totalPages > 1" class="flex items-center justify-between mt-4 animate-in">
                <div class="text-[10px] text-text-faint font-mono">
                    Page {{ page }} of {{ totalPages }} ({{ total }} total)
                </div>
                <div class="flex gap-1">
                    <button
                        :disabled="page <= 1"
                        class="px-2.5 py-1 text-xs font-mono rounded-md border border-border text-text-dim hover:text-white hover:border-border-bright transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                        @click="goToPage(page - 1)"
                    >
                        Prev
                    </button>
                    <button
                        v-for="p in pageNumbers"
                        :key="p"
                        class="w-8 py-1 text-xs font-mono rounded-md transition-colors"
                        :class="p === page
                            ? 'bg-accent/10 text-accent border border-accent/30'
                            : 'text-text-dim hover:text-white border border-border hover:border-border-bright'"
                        @click="goToPage(p)"
                    >
                        {{ p }}
                    </button>
                    <button
                        :disabled="page >= totalPages"
                        class="px-2.5 py-1 text-xs font-mono rounded-md border border-border text-text-dim hover:text-white hover:border-border-bright transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                        @click="goToPage(page + 1)"
                    >
                        Next
                    </button>
                </div>
            </div>
        </template>
    </div>
</template>
