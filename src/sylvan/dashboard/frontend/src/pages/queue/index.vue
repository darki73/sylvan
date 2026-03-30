<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";
import { useWebSocket } from "@/composables/useWebSocket";
import { useQueue } from "@/composables/useQueue";
import type { QueueJob } from "@/composables/useQueue";

const { request, on, off } = useWebSocket();
const { jobs } = useQueue();

interface WorkerStatus {
    job_type: string;
    priority: number;
    pending: number;
    current: {
        job_id: string;
        key: string;
        status: string;
        progress: Record<string, unknown>;
    } | null;
}

interface RecentJob {
    job_id: string;
    job_type: string;
    key: string;
    status: string;
    started_at?: string;
    finished_at?: string;
    duration_ms?: number;
    error?: string;
}

const workers = ref<WorkerStatus[]>([]);
const recent = ref<RecentJob[]>([]);
const loading = ref(true);
const dbSize = ref(0);
const vacuuming = ref(false);
const vacuumResult = ref<{ freed: number } | null>(null);

const totalPending = computed(() => workers.value.reduce((sum, w) => sum + w.pending, 0));

const activeJobs = computed(() => {
    return jobs.filter((j: QueueJob) => j.status === "pending" || j.status === "running");
});

const statusColor: Record<string, string> = {
    pending: "bg-warning/20 text-warning border-warning/30",
    running: "bg-info/20 text-info border-info/30",
    complete: "bg-accent/20 text-accent border-accent/30",
    failed: "bg-danger/20 text-danger border-danger/30",
};

function statusClasses(status: string): string {
    return statusColor[status] ?? "bg-surface-2 text-text-dim border-border";
}

function formatJobType(jobType: string): string {
    return jobType.replace(/_/g, " ");
}

function formatDuration(ms: number | undefined): string {
    if (!ms) return "-";
    if (ms < 1000) return `${ms}ms`;
    const secs = ms / 1000;
    if (secs < 60) return `${secs.toFixed(1)}s`;
    const mins = Math.floor(secs / 60);
    const remaining = Math.floor(secs % 60);
    return `${mins}m ${remaining}s`;
}

function formatProgress(progress: Record<string, unknown> | undefined): string {
    if (!progress) return "";
    const parts: string[] = [];
    for (const [key, val] of Object.entries(progress)) {
        if (key === "job_id" || key === "job_type" || key === "key") continue;
        if (key === "type") continue;
        parts.push(`${key}: ${val}`);
    }
    return parts.join(", ");
}

function formatBytes(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function fetchStatus() {
    try {
        const result = await request<{ workers: WorkerStatus[]; recent: RecentJob[] }>("get_queue_status");
        workers.value = result.workers ?? [];
        recent.value = result.recent ?? [];
        const sizeResult = await request<{ size: number }>("get_database_size");
        dbSize.value = sizeResult.size ?? 0;
    } finally {
        loading.value = false;
    }
}

async function runVacuum() {
    vacuuming.value = true;
    vacuumResult.value = null;
    try {
        const result = await request<{ freed: number; size_after: number }>("vacuum_database");
        vacuumResult.value = { freed: result.freed };
        dbSize.value = result.size_after;
    } finally {
        vacuuming.value = false;
    }
}

function onQueueStatus(data: unknown) {
    const d = data as { workers?: WorkerStatus[]; recent?: RecentJob[] };
    if (d.workers) workers.value = d.workers;
    if (d.recent) recent.value = d.recent;
}

onMounted(() => {
    fetchStatus();
    on("queue_status", onQueueStatus);
});

onUnmounted(() => {
    off("queue_status", onQueueStatus);
});
</script>

<template>
    <div>
        <div class="flex items-center justify-between mb-8 animate-in">
            <div>
                <h1 class="text-2xl font-bold text-white tracking-tight">Queue</h1>
                <p class="text-sm text-text-dim mt-1">
                    <span class="font-mono text-accent">{{ totalPending }}</span> pending jobs,
                    <span class="font-mono">{{ activeJobs.length }}</span> active
                </p>
            </div>
            <button
                class="px-3 py-1.5 text-xs font-mono rounded-lg border border-border text-text-dim hover:text-accent hover:border-accent/30 transition-colors"
                @click="fetchStatus"
            >
                Refresh
            </button>
        </div>

        <div v-if="loading" class="flex items-center gap-3 text-text-dim text-sm py-20 justify-center">
            <div class="w-4 h-4 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
            Loading...
        </div>

        <template v-else>
            <!-- Workers -->
            <div class="mb-8 animate-in delay-1">
                <div class="flex items-center gap-3 mb-3">
                    <h2 class="text-xs font-bold text-text-dim uppercase tracking-[0.15em]">Workers</h2>
                    <div class="flex-1 h-px bg-border" />
                </div>

                <div v-if="!workers.length" class="rounded-xl bg-surface border border-border p-8 text-center">
                    <div class="text-sm text-text-dim">No workers registered</div>
                </div>

                <div v-else class="grid grid-cols-3 gap-4">
                    <div
                        v-for="worker in workers"
                        :key="worker.job_type"
                        class="rounded-xl bg-surface border border-border p-5"
                    >
                        <div class="flex items-center justify-between mb-3">
                            <span class="font-mono text-sm text-white font-medium">{{ formatJobType(worker.job_type) }}</span>
                            <span class="px-2 py-0.5 text-[10px] font-mono rounded bg-surface-2 border border-border text-text-faint">
                                priority {{ worker.priority }}
                            </span>
                        </div>
                        <div class="text-xs text-text-dim mb-3">
                            <span class="font-mono text-accent">{{ worker.pending }}</span> pending
                        </div>
                        <div v-if="worker.current" class="rounded-lg bg-surface-2 border border-border p-3">
                            <div class="flex items-center gap-2 mb-1">
                                <span
                                    class="px-1.5 py-0.5 text-[10px] font-mono rounded border"
                                    :class="statusClasses(worker.current.status)"
                                >
                                    {{ worker.current.status }}
                                </span>
                                <span class="font-mono text-xs text-text-dim truncate">{{ worker.current.key }}</span>
                            </div>
                            <div v-if="worker.current.progress && Object.keys(worker.current.progress).length" class="text-[10px] text-text-faint font-mono mt-1 truncate">
                                {{ formatProgress(worker.current.progress) }}
                            </div>
                        </div>
                        <div v-else class="rounded-lg bg-surface-2 border border-border p-3 text-center">
                            <span class="text-xs text-text-faint">Idle</span>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Active jobs (live from useQueue) -->
            <div v-if="activeJobs.length" class="mb-8 animate-in delay-2">
                <div class="flex items-center gap-3 mb-3">
                    <h2 class="text-xs font-bold text-text-dim uppercase tracking-[0.15em]">Active Jobs</h2>
                    <div class="flex-1 h-px bg-border" />
                </div>
                <div class="rounded-xl border border-border overflow-hidden">
                    <table class="w-full text-sm">
                        <thead>
                            <tr class="bg-surface-2 text-[10px] text-text-faint uppercase tracking-wider">
                                <th class="px-4 py-2 text-left font-medium">Type</th>
                                <th class="px-4 py-2 text-left font-medium">Key</th>
                                <th class="px-4 py-2 text-left font-medium">Status</th>
                                <th class="px-4 py-2 text-left font-medium">Progress</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr
                                v-for="job in activeJobs"
                                :key="job.job_id"
                                class="border-t border-border hover:bg-surface/80 transition-colors"
                            >
                                <td class="px-4 py-2 font-mono text-xs text-white">{{ formatJobType(job.job_type) }}</td>
                                <td class="px-4 py-2 font-mono text-xs text-text-dim">{{ job.key ?? "-" }}</td>
                                <td class="px-4 py-2">
                                    <span
                                        class="px-1.5 py-0.5 text-[10px] font-mono rounded border"
                                        :class="statusClasses(job.status)"
                                    >
                                        {{ job.status }}
                                    </span>
                                </td>
                                <td class="px-4 py-2 font-mono text-[10px] text-text-faint truncate max-w-[300px]">
                                    {{ formatProgress(job.progress) }}
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Recent history -->
            <div class="animate-in delay-3">
                <div class="flex items-center gap-3 mb-3">
                    <h2 class="text-xs font-bold text-text-dim uppercase tracking-[0.15em]">Recent History</h2>
                    <div class="flex-1 h-px bg-border" />
                </div>

                <div v-if="!recent.length" class="rounded-xl bg-surface border border-border p-8 text-center">
                    <div class="text-sm text-text-dim">No completed jobs yet</div>
                </div>

                <div v-else class="rounded-xl border border-border overflow-hidden">
                    <table class="w-full text-sm">
                        <thead>
                            <tr class="bg-surface-2 text-[10px] text-text-faint uppercase tracking-wider">
                                <th class="px-4 py-2 text-left font-medium">Type</th>
                                <th class="px-4 py-2 text-left font-medium">Key</th>
                                <th class="px-4 py-2 text-left font-medium">Status</th>
                                <th class="px-4 py-2 text-right font-medium">Duration</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr
                                v-for="job in recent"
                                :key="job.job_id"
                                class="border-t border-border hover:bg-surface/80 transition-colors"
                            >
                                <td class="px-4 py-2 font-mono text-xs text-white">{{ formatJobType(job.job_type) }}</td>
                                <td class="px-4 py-2 font-mono text-xs text-text-dim">{{ job.key ?? "-" }}</td>
                                <td class="px-4 py-2">
                                    <span
                                        class="px-1.5 py-0.5 text-[10px] font-mono rounded border"
                                        :class="statusClasses(job.status)"
                                    >
                                        {{ job.status }}
                                    </span>
                                </td>
                                <td class="px-4 py-2 font-mono text-xs text-text-dim text-right">{{ formatDuration(job.duration_ms) }}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
            <!-- Database -->
            <div class="mt-8 animate-in delay-4">
                <div class="flex items-center gap-3 mb-3">
                    <h2 class="text-xs font-bold text-text-dim uppercase tracking-[0.15em]">Database</h2>
                    <div class="flex-1 h-px bg-border" />
                </div>
                <div class="rounded-xl bg-surface border border-border p-5">
                    <div class="flex items-center justify-between">
                        <div>
                            <div class="text-sm text-text-dim">
                                Size: <span class="font-mono text-white">{{ formatBytes(dbSize) }}</span>
                            </div>
                            <div v-if="vacuumResult" class="text-xs text-accent mt-1">
                                Freed {{ formatBytes(vacuumResult.freed) }}
                            </div>
                        </div>
                        <button
                            :disabled="vacuuming"
                            class="px-4 py-2 text-xs font-mono rounded-lg border border-border text-text-dim hover:text-accent hover:border-accent/30 transition-colors disabled:opacity-50"
                            @click="runVacuum"
                        >
                            <template v-if="vacuuming">
                                <span class="inline-flex items-center gap-2">
                                    <span class="w-3 h-3 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
                                    Vacuuming...
                                </span>
                            </template>
                            <template v-else>Vacuum</template>
                        </button>
                    </div>
                </div>
            </div>
        </template>
    </div>
</template>
