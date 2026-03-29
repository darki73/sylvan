import { reactive, onMounted, onUnmounted } from "vue";
import { useWebSocket } from "./useWebSocket";

export interface QueueJob {
    job_id: string;
    job_type: string;
    key: string | null;
    status: "pending" | "running" | "complete" | "failed";
    progress?: Record<string, unknown>;
    error?: string;
}

const state = reactive({
    jobs: [] as QueueJob[],
});

let initialized = false;

export function useQueue() {
    const { on, off } = useWebSocket();

    function onJobEnqueued(data: unknown) {
        const d = data as Record<string, unknown>;
        state.jobs.push({
            job_id: d.job_id as string,
            job_type: d.job_type as string,
            key: d.key as string | null,
            status: "pending",
        });
    }

    function onJobStarted(data: unknown) {
        const d = data as Record<string, unknown>;
        const job = state.jobs.find(j => j.job_id === d.job_id);
        if (job) {
            job.status = "running";
        }
    }

    function onJobProgress(data: unknown) {
        const d = data as Record<string, unknown>;
        const job = state.jobs.find(j => j.job_id === d.job_id);
        if (job) {
            job.progress = d as Record<string, unknown>;
        }
    }

    function onJobComplete(data: unknown) {
        const d = data as Record<string, unknown>;
        const job = state.jobs.find(j => j.job_id === d.job_id);
        if (job) {
            job.status = "complete";
        }
        setTimeout(() => {
            const idx = state.jobs.findIndex(j => j.job_id === d.job_id);
            if (idx >= 0) state.jobs.splice(idx, 1);
        }, 3000);
    }

    function onJobFailed(data: unknown) {
        const d = data as Record<string, unknown>;
        const job = state.jobs.find(j => j.job_id === d.job_id);
        if (job) {
            job.status = "failed";
            job.error = d.error as string;
        }
        setTimeout(() => {
            const idx = state.jobs.findIndex(j => j.job_id === d.job_id);
            if (idx >= 0) state.jobs.splice(idx, 1);
        }, 10000);
    }

    function isRunning(key: string): boolean {
        return state.jobs.some(j => j.key === key && (j.status === "pending" || j.status === "running"));
    }

    function isProcessing(repoName: string): boolean {
        const keys = [`index:${repoName}`, `embed:${repoName}`, `summarize:${repoName}`];
        return state.jobs.some(j => keys.includes(j.key ?? "") && (j.status === "pending" || j.status === "running"));
    }

    function getActiveJob(repoName: string): QueueJob | undefined {
        const keys = [`index:${repoName}`, `embed:${repoName}`, `summarize:${repoName}`];
        return state.jobs.find(j => keys.includes(j.key ?? "") && (j.status === "pending" || j.status === "running"))
            ?? state.jobs.find(j => keys.includes(j.key ?? "") && j.status === "complete");
    }

    function getJob(key: string): QueueJob | undefined {
        return state.jobs.find(j => j.key === key);
    }

    onMounted(() => {
        if (!initialized) {
            on("job_enqueued", onJobEnqueued);
            on("job_started", onJobStarted);
            on("job_progress", onJobProgress);
            on("job_complete", onJobComplete);
            on("job_failed", onJobFailed);
            initialized = true;
        }
    });

    return { jobs: state.jobs, isRunning, isProcessing, getActiveJob, getJob };
}
