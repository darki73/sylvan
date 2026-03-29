<script setup lang="ts">
import { ref, reactive, onMounted, computed, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useWebSocket } from "@/composables/useWebSocket";
import { useQueue } from "@/composables/useQueue";
import FileTreeNode from "@/components/FileTreeNode.vue";
import ActivityHeatmap from "@/components/ActivityHeatmap.vue";

interface DirEntry {
    name: string;
    type: "dir" | "file";
    language?: string;
    size?: number;
    file_count?: number;
    children?: DirEntry[];
}

interface SymbolEntry {
    symbol_id: string;
    name: string;
    kind: string;
    signature: string;
    line_start: number;
    line_end: number;
    children?: SymbolEntry[];
}

interface RepoData {
    id: number;
    name: string;
    source_path: string;
    files: number;
    symbols: number;
    sections: number;
    indexed_at: string;
    git_head: string;
    github_url: string;
    repo_type: string;
    languages: Record<string, number>;
    kind_breakdown: Record<string, number>;
    file_tree: DirEntry[];
    usage_map: Record<string, number>;
    load_ms: number;
}

const langColors: Record<string, string> = {
    python: "#3572A5", typescript: "#3178C6", javascript: "#F1E05A",
    go: "#00ADD8", rust: "#DEA584", java: "#B07219", php: "#4F5D95",
    ruby: "#CC342D", c: "#555555", cpp: "#F34B7D", swift: "#F05138",
    kotlin: "#A97BFF", vue: "#41B883", tsx: "#3178C6", css: "#563D7C",
    html: "#E34C26", yaml: "#CB171E", toml: "#9C4121", json: "#A0A0A0",
    markdown: "#083FA1", sql: "#E38C00", bash: "#89E051",
};

const kindIcons: Record<string, string> = {
    function: "fn", class: "C", method: "m", constant: "K", type: "T",
};

const kindColors: Record<string, string> = {
    function: "#3572A5", class: "#E34C26", method: "#3178C6",
    constant: "#F1E05A", type: "#41B883",
};

function getColor(lang: string): string {
    const color = langColors[lang.toLowerCase()];
    if (color) return color;
    let hash = 0;
    for (let i = 0; i < lang.length; i++) hash = lang.charCodeAt(i) + ((hash << 5) - hash);
    return `hsl(${Math.abs(hash) % 360}, 50%, 55%)`;
}

const route = useRoute();
const router = useRouter();
const { request } = useWebSocket();
const repoName = route.params.name as string;

const data = reactive<RepoData>({
    id: 0, name: "", source_path: "", files: 0, symbols: 0, sections: 0,
    indexed_at: "", git_head: "", github_url: "", repo_type: "project",
    languages: {}, kind_breakdown: {}, file_tree: [], usage_map: {}, load_ms: 0,
});
const loading = ref(true);
const loadTime = ref(0);
const confirmDelete = ref(false);
const deleting = ref(false);

const { isProcessing, getActiveJob } = useQueue();
const reindexing = computed(() => isProcessing(repoName));
const currentJob = computed(() => getActiveJob(repoName));
const refreshCountdown = ref(0);
let countdownTimer: ReturnType<typeof setInterval> | null = null;

watch(reindexing, (running, wasRunning) => {
    if (wasRunning && !running) {
        refreshCountdown.value = 3;
        countdownTimer = setInterval(() => {
            refreshCountdown.value--;
            if (refreshCountdown.value <= 0) {
                if (countdownTimer) clearInterval(countdownTimer);
                countdownTimer = null;
                fetch();
            }
        }, 1000);
    }
});

// File browser state
const selectedFile = ref<string | null>(null);
const fileOutline = ref<SymbolEntry[]>([]);
const outlineLoading = ref(false);

const langEntries = computed(() => {
    const entries = Object.entries(data.languages);
    const total = entries.reduce((sum, [, count]) => sum + count, 0);
    return entries.map(([lang, count]) => ({
        lang, count, pct: total > 0 ? Math.round((count / total) * 100) : 0,
    }));
});

const kindEntries = computed(() => {
    const entries = Object.entries(data.kind_breakdown);
    const total = entries.reduce((sum, [, count]) => sum + count, 0);
    return entries.map(([kind, count]) => ({
        kind, count, pct: total > 0 ? Math.round((count / total) * 100) : 0,
    }));
});


async function fetch() {
    loading.value = true;
    const t0 = performance.now();
    try {
        const result = await request<RepoData>("get_repository", { name: repoName });
        Object.assign(data, result);
        loadTime.value = Math.round(performance.now() - t0);
    } finally {
        loading.value = false;
    }
}

async function selectFile(path: string) {
    selectedFile.value = path;
    outlineLoading.value = true;
    try {
        const result = await request<{ outline: SymbolEntry[] }>("get_file_outline", { repo: repoName, file_path: path });
        fileOutline.value = result.outline ?? [];
    } catch {
        fileOutline.value = [];
    } finally {
        outlineLoading.value = false;
    }
}

async function reindex(force: boolean = false) {
    await request("reindex_repo", { name: data.name, path: data.source_path, force });
}

async function deleteRepo() {
    deleting.value = true;
    await request("delete_repo", { name: data.name });
    router.push("/repositories");
}

onMounted(fetch);
</script>

<template>
    <div>
        <!-- Header -->
        <div class="mb-4 animate-in">
            <div class="flex items-center gap-3 mb-1">
                <RouterLink to="/repositories" class="text-text-faint hover:text-text-dim transition-colors text-sm">
                    Repositories
                </RouterLink>
                <span class="text-text-faint text-xs">/</span>
                <h1 class="text-2xl font-bold text-white tracking-tight">{{ data.name || repoName }}</h1>
            </div>
            <div class="flex items-center gap-3 mt-1">
                <span v-if="data.source_path" class="text-xs text-text-faint font-mono truncate max-w-[500px]">{{ data.source_path }}</span>
                <span v-if="data.git_head" class="text-[10px] font-mono text-text-faint bg-surface-2 px-1.5 py-0.5 rounded">{{ data.git_head }}</span>
                <a v-if="data.github_url" :href="data.github_url" target="_blank" class="text-xs text-accent hover:underline">GitHub</a>
                <span v-if="data.indexed_at" class="text-[10px] text-text-faint font-mono">indexed {{ data.indexed_at.slice(0, 10) }}</span>
                <span v-if="loadTime" class="text-[10px] text-text-faint font-mono">{{ data.load_ms }}ms</span>
            </div>
        </div>

        <div v-if="loading" class="flex items-center gap-3 text-text-dim text-sm py-20 justify-center">
            <div class="w-4 h-4 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
            Loading...
        </div>

        <template v-else>
            <!-- Stats + Actions -->
            <div class="flex items-center justify-between mb-4 animate-in">
                <div class="flex gap-5 text-xs">
                    <div>
                        <span class="font-mono text-lg font-bold text-white">{{ data.files.toLocaleString() }}</span>
                        <span class="text-text-faint ml-1">files</span>
                    </div>
                    <div>
                        <span class="font-mono text-lg font-bold text-accent">{{ data.symbols.toLocaleString() }}</span>
                        <span class="text-text-faint ml-1">symbols</span>
                    </div>
                    <div>
                        <span class="font-mono text-lg font-bold text-info">{{ data.sections.toLocaleString() }}</span>
                        <span class="text-text-faint ml-1">docs</span>
                    </div>
                </div>
                <div class="flex gap-2">
                    <button
                        :disabled="reindexing"
                        class="px-3 py-1.5 text-xs font-mono rounded-lg border border-border text-text-dim hover:text-accent hover:border-accent/30 transition-colors disabled:opacity-50"
                        @click="reindex(false)"
                    >
                        Re-index
                    </button>
                    <button
                        :disabled="reindexing"
                        class="px-3 py-1.5 text-xs font-mono rounded-lg border border-border text-text-dim hover:text-amber-400 hover:border-amber-400/30 transition-colors disabled:opacity-50"
                        @click="reindex(true)"
                    >
                        Full Re-index
                    </button>
                    <button
                        v-if="!confirmDelete"
                        class="px-3 py-1.5 text-xs font-mono rounded-lg border border-border text-text-dim hover:text-red-400 hover:border-red-400/30 transition-colors"
                        @click="confirmDelete = true"
                    >
                        Delete
                    </button>
                    <div v-else class="flex items-center gap-2">
                        <button
                            :disabled="deleting"
                            class="px-3 py-1.5 text-xs font-mono rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 hover:bg-red-500/20 transition-colors disabled:opacity-50 flex items-center gap-1.5"
                            @click="deleteRepo"
                        >
                            <div v-if="deleting" class="w-3 h-3 border-2 border-red-400/30 border-t-red-400 rounded-full animate-spin" />
                            {{ deleting ? "Deleting..." : "Confirm" }}
                        </button>
                        <button
                            v-if="!deleting"
                            class="px-3 py-1.5 text-xs font-mono rounded-lg border border-border text-text-dim hover:text-white transition-colors"
                            @click="confirmDelete = false"
                        >
                            Cancel
                        </button>
                    </div>
                </div>
            </div>

            <!-- Indexing progress -->
            <div
                v-if="reindexing || refreshCountdown > 0"
                class="rounded-xl bg-accent/5 border border-accent/20 p-4 mb-4 animate-in flex items-center gap-3"
            >
                <div class="w-4 h-4 border-2 border-accent/30 border-t-accent rounded-full animate-spin shrink-0" />
                <div class="text-sm text-accent">
                    <span v-if="currentJob?.job_type === 'index_folder' && currentJob?.progress?.stage === 'discovering'">Discovering files...</span>
                    <span v-else-if="currentJob?.job_type === 'index_folder' && currentJob?.progress?.stage === 'complete'">
                        Indexed {{ currentJob.progress.files_indexed }} files, {{ currentJob.progress.symbols_extracted }} symbols
                    </span>
                    <span v-else-if="currentJob?.job_type === 'index_folder'">Indexing files...</span>
                    <span v-else-if="currentJob?.job_type === 'generate_embeddings' && currentJob?.progress?.stage === 'embedding'">
                        Generating embeddings ({{ currentJob.progress.current }}/{{ currentJob.progress.total }})
                    </span>
                    <span v-else-if="currentJob?.job_type === 'generate_embeddings'">Generating embeddings...</span>
                    <span v-else-if="currentJob?.job_type === 'generate_summaries' && currentJob?.progress?.stage === 'section_summaries'">Generating section summaries...</span>
                    <span v-else-if="currentJob?.job_type === 'generate_summaries'">Generating summaries...</span>
                    <span v-else-if="refreshCountdown > 0">Refreshing in {{ refreshCountdown }}...</span>
                    <span v-else>Processing...</span>
                </div>
            </div>

            <!-- Language + Kind breakdown -->
            <div class="grid grid-cols-2 gap-6 mb-6">
                <div v-if="langEntries.length" class="rounded-xl bg-surface border border-border p-5 animate-in">
                    <h2 class="text-sm font-semibold text-white mb-3">Languages</h2>
                    <div class="stacked-bar mb-3">
                        <div
                            v-for="entry in langEntries"
                            :key="entry.lang"
                            :style="{ width: entry.pct + '%', background: getColor(entry.lang) }"
                        />
                    </div>
                    <div class="flex flex-wrap gap-x-4 gap-y-1.5">
                        <span v-for="entry in langEntries" :key="entry.lang" class="text-xs font-mono text-text-faint">
                            <span class="inline-block w-2 h-2 rounded-full mr-1" :style="{ background: getColor(entry.lang) }" />
                            {{ entry.lang }} {{ entry.pct }}%
                            <span class="text-text-faint/50 ml-0.5">({{ entry.count }})</span>
                        </span>
                    </div>
                </div>

                <div v-if="kindEntries.length" class="rounded-xl bg-surface border border-border p-5 animate-in delay-1">
                    <h2 class="text-sm font-semibold text-white mb-3">Symbol Types</h2>
                    <div class="stacked-bar mb-3">
                        <div
                            v-for="entry in kindEntries"
                            :key="entry.kind"
                            :style="{ width: entry.pct + '%', background: kindColors[entry.kind] || '#666' }"
                        />
                    </div>
                    <div class="flex flex-wrap gap-x-4 gap-y-1.5">
                        <span v-for="entry in kindEntries" :key="entry.kind" class="text-xs font-mono text-text-faint">
                            <span class="inline-block w-2 h-2 rounded-full mr-1" :style="{ background: kindColors[entry.kind] || '#666' }" />
                            {{ entry.kind }} {{ entry.pct }}%
                            <span class="text-text-faint/50 ml-0.5">({{ entry.count.toLocaleString() }})</span>
                        </span>
                    </div>
                </div>
            </div>

            <!-- File browser (GitHub-style) -->
            <div class="flex gap-4 animate-in delay-1" style="min-height: 500px">
                <!-- Sidebar: file tree -->
                <div class="w-72 shrink-0 rounded-xl bg-surface border border-border overflow-hidden">
                    <div class="px-3 py-2 border-b border-border text-xs text-text-faint font-mono">
                        Files ({{ data.files.toLocaleString() }})
                    </div>
                    <div class="overflow-y-auto max-h-[600px] p-1 font-mono">
                        <FileTreeNode
                            :entries="data.file_tree"
                            :selected-file="selectedFile ?? undefined"
                            :get-color="getColor"
                            @select="selectFile"
                        />
                    </div>
                </div>

                <!-- Content: file outline or placeholder -->
                <div class="flex-1 rounded-xl bg-surface border border-border overflow-hidden">
                    <template v-if="selectedFile">
                        <div class="px-4 py-2 border-b border-border flex items-center gap-2">
                            <span class="text-xs font-mono text-white">{{ selectedFile }}</span>
                        </div>
                        <div v-if="outlineLoading" class="flex items-center gap-3 text-text-dim text-sm py-12 justify-center">
                            <div class="w-4 h-4 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
                        </div>
                        <div v-else-if="!fileOutline.length" class="text-xs text-text-faint py-12 text-center">
                            No symbols in this file
                        </div>
                        <div v-else class="overflow-y-auto max-h-[600px] p-2">
                            <div
                                v-for="sym in fileOutline"
                                :key="sym.symbol_id"
                                class="mb-0.5"
                            >
                                <div class="flex items-center gap-2 py-1.5 px-2 rounded hover:bg-surface-2/50 transition-colors">
                                    <span
                                        class="text-[10px] font-mono font-bold w-5 text-center shrink-0 rounded"
                                        :style="{ color: kindColors[sym.kind] || '#888' }"
                                    >
                                        {{ kindIcons[sym.kind] || sym.kind[0] }}
                                    </span>
                                    <span class="text-xs font-mono text-white">{{ sym.name }}</span>
                                    <span v-if="sym.signature && sym.signature !== sym.name" class="text-[10px] font-mono text-text-faint truncate ml-1">
                                        {{ sym.signature.replace(sym.name, '').trim() }}
                                    </span>
                                    <span class="text-[10px] font-mono text-text-faint ml-auto shrink-0">L{{ sym.line_start }}</span>
                                </div>
                                <!-- Children (methods inside class) -->
                                <div v-if="sym.children?.length" class="ml-5">
                                    <div
                                        v-for="child in sym.children"
                                        :key="child.symbol_id"
                                        class="flex items-center gap-2 py-1 px-2 rounded hover:bg-surface-2/50 transition-colors"
                                    >
                                        <span
                                            class="text-[10px] font-mono font-bold w-5 text-center shrink-0"
                                            :style="{ color: kindColors[child.kind] || '#888' }"
                                        >
                                            {{ kindIcons[child.kind] || child.kind[0] }}
                                        </span>
                                        <span class="text-xs font-mono text-text-dim">{{ child.name }}</span>
                                        <span class="text-[10px] font-mono text-text-faint ml-auto shrink-0">L{{ child.line_start }}</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </template>
                    <template v-else>
                        <div class="flex items-center justify-center h-full text-text-faint text-sm py-20">
                            Select a file to view its outline
                        </div>
                    </template>
                </div>
            </div>

            <!-- Activity heatmap -->
            <div v-if="Object.keys(data.usage_map).length" class="rounded-xl bg-surface border border-border p-5 mt-4 animate-in delay-2">
                <h2 class="text-sm font-semibold text-white mb-3">Activity</h2>
                <ActivityHeatmap :data="data.usage_map" label="Tool call activity" />
            </div>
        </template>
    </div>
</template>
