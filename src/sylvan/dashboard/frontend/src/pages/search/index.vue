<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted } from "vue";
import { useWebSocket } from "@/composables/useWebSocket";
import CodeBlock from "@/components/CodeBlock.vue";

interface SearchResult {
    symbol_id: string;
    name: string;
    qualified_name: string;
    kind: string;
    language: string;
    file: string;
    signature: string;
    line: number;
    repo: string;
}

interface SymbolSource {
    source: string;
    file: string;
    line_start: number;
    line_end: number;
}

const { request } = useWebSocket();
const query = ref("");
const repoFilter = ref("");
const kindFilter = ref("");
const results = reactive<SearchResult[]>([]);
const repos = reactive<Array<{ name: string }>>([]);
const loading = ref(false);
const searched = ref(false);
const selectedId = ref<string | null>(null);
const sourceData = ref<SymbolSource | null>(null);
const sourceLoading = ref(false);

const kinds = [
    { value: "", label: "All" },
    { value: "function", label: "Functions", icon: "fn", color: "#3572A5" },
    { value: "class", label: "Classes", icon: "C", color: "#E34C26" },
    { value: "method", label: "Methods", icon: "m", color: "#3178C6" },
    { value: "constant", label: "Constants", icon: "K", color: "#F1E05A" },
    { value: "type", label: "Types", icon: "T", color: "#41B883" },
];

const kindColors: Record<string, string> = {
    function: "#3572A5", class: "#E34C26", method: "#3178C6",
    constant: "#F1E05A", type: "#41B883",
};

const kindIcons: Record<string, string> = {
    function: "fn", class: "C", method: "m", constant: "K", type: "T",
};

const langColors: Record<string, string> = {
    python: "#3572A5", typescript: "#3178C6", javascript: "#F1E05A",
    go: "#00ADD8", rust: "#DEA584", java: "#B07219", php: "#4F5D95",
    vue: "#41B883", css: "#563D7C", html: "#E34C26",
};

const filtered = computed(() => {
    if (!kindFilter.value) return results;
    return results.filter(r => r.kind === kindFilter.value);
});

const grouped = computed(() => {
    const groups: Record<string, SearchResult[]> = {};
    for (const r of filtered.value) {
        const key = r.repo || "unknown";
        if (!groups[key]) groups[key] = [];
        groups[key].push(r);
    }
    return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b));
});

const kindCounts = computed(() => {
    const counts: Record<string, number> = {};
    for (const r of results) {
        counts[r.kind] = (counts[r.kind] || 0) + 1;
    }
    return counts;
});

let debounceTimer: ReturnType<typeof setTimeout> | null = null;

function onInput() {
    if (debounceTimer) clearTimeout(debounceTimer);
    if (!query.value || query.value.length < 2) {
        results.splice(0, results.length);
        searched.value = false;
        return;
    }
    debounceTimer = setTimeout(search, 250);
}

async function search() {
    if (!query.value || query.value.length < 2) return;
    loading.value = true;
    searched.value = true;
    selectedId.value = null;
    sourceData.value = null;
    try {
        const result = await request<{ results: SearchResult[] }>(
            "search_symbols",
            { query: query.value, repo: repoFilter.value || undefined },
        );
        results.splice(0, results.length, ...result.results);
    } finally {
        loading.value = false;
    }
}

async function selectSymbol(sym: SearchResult) {
    if (selectedId.value === sym.symbol_id) {
        selectedId.value = null;
        sourceData.value = null;
        return;
    }
    selectedId.value = sym.symbol_id;
    sourceLoading.value = true;
    try {
        const result = await request<SymbolSource>("get_symbol_source", { symbol_id: sym.symbol_id });
        sourceData.value = result;
    } catch {
        sourceData.value = null;
    } finally {
        sourceLoading.value = false;
    }
}

async function loadRepos() {
    try {
        const result = await request<{ repos: Array<{ name: string }> }>("get_repositories");
        repos.splice(0, repos.length, ...result.repos);
    } catch {
        // ignore
    }
}

watch(repoFilter, () => {
    if (query.value.length >= 2) search();
});

onMounted(loadRepos);
</script>

<template>
    <div>
        <div class="mb-4 animate-in">
            <h1 class="text-2xl font-bold text-white tracking-tight">Search</h1>
            <p class="text-sm text-text-dim mt-1">Find symbols across all indexed repositories</p>
        </div>

        <!-- Search bar -->
        <div class="flex gap-3 mb-4 animate-in">
            <div class="flex-1 relative">
                <input
                    v-model="query"
                    placeholder="Start typing to search..."
                    autofocus
                    class="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-sm font-mono text-white placeholder:text-text-faint/40 focus:border-accent/50 focus:outline-none transition-colors"
                    @input="onInput"
                    @keydown.enter="search"
                />
                <div v-if="loading" class="absolute right-3 top-1/2 -translate-y-1/2">
                    <div class="w-4 h-4 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
                </div>
            </div>
            <select
                v-model="repoFilter"
                class="bg-surface border border-border rounded-lg px-3 py-2 text-sm font-mono text-white focus:border-accent/50 focus:outline-none transition-colors appearance-none cursor-pointer w-48"
            >
                <option value="">All repos</option>
                <option v-for="r in repos" :key="r.name" :value="r.name">{{ r.name }}</option>
            </select>
        </div>

        <!-- Kind filter pills -->
        <div v-if="results.length" class="flex gap-1.5 mb-4 animate-in">
            <button
                v-for="k in kinds"
                :key="k.value"
                class="px-2.5 py-1 text-[11px] font-mono rounded-md transition-all duration-150"
                :class="kindFilter === k.value
                    ? 'bg-surface-2 text-white border border-border-bright'
                    : 'text-text-faint hover:text-text-dim border border-transparent'"
                @click="kindFilter = k.value"
            >
                <span v-if="k.icon" class="font-bold mr-1" :style="{ color: k.color }">{{ k.icon }}</span>
                {{ k.label }}
                <span v-if="k.value && kindCounts[k.value]" class="ml-1 text-text-faint">{{ kindCounts[k.value] }}</span>
                <span v-else-if="!k.value && results.length" class="ml-1 text-text-faint">{{ results.length }}</span>
            </button>
        </div>

        <!-- Results -->
        <div v-if="filtered.length" class="animate-in">
            <div v-for="[repo, syms] in grouped" :key="repo" class="mb-4">
                <div class="text-[10px] font-mono text-text-faint uppercase tracking-wider mb-1.5 px-1">
                    {{ repo }}
                    <span class="text-text-faint/50 ml-1">{{ syms.length }}</span>
                </div>
                <div class="rounded-xl bg-surface border border-border overflow-hidden">
                    <div
                        v-for="(sym, i) in syms"
                        :key="sym.symbol_id"
                    >
                        <div
                            class="flex items-center gap-3 px-4 py-2.5 cursor-pointer transition-colors"
                            :class="[
                                i > 0 ? 'border-t border-border/50' : '',
                                selectedId === sym.symbol_id ? 'bg-accent/5' : 'hover:bg-surface-2/50',
                            ]"
                            @click="selectSymbol(sym)"
                        >
                            <span
                                class="text-[10px] font-mono font-bold w-5 h-5 flex items-center justify-center rounded shrink-0"
                                :style="{ color: kindColors[sym.kind] || '#888', background: (kindColors[sym.kind] || '#888') + '14' }"
                            >
                                {{ kindIcons[sym.kind] || sym.kind[0] }}
                            </span>

                            <div class="min-w-0 flex-1">
                                <div class="flex items-center gap-1.5">
                                    <span class="font-mono text-sm text-white">{{ sym.name }}</span>
                                    <span
                                        v-if="sym.language"
                                        class="w-1.5 h-1.5 rounded-full shrink-0"
                                        :style="{ background: langColors[sym.language] || '#888' }"
                                    />
                                    <span class="text-[10px] font-mono text-text-faint">{{ sym.language }}</span>
                                </div>
                                <div v-if="sym.signature && sym.signature !== sym.name" class="text-[10px] font-mono text-text-faint truncate">
                                    {{ sym.signature }}
                                </div>
                            </div>

                            <div class="shrink-0 text-right">
                                <span class="px-1.5 py-0.5 rounded text-[9px] font-mono bg-surface-2 text-text-dim border border-border">{{ sym.repo }}</span>
                                <div class="text-[10px] font-mono text-text-faint truncate max-w-[200px] mt-0.5">
                                    {{ sym.file }}:{{ sym.line }}
                                </div>
                            </div>
                        </div>

                        <!-- Inline source preview -->
                        <div
                            v-if="selectedId === sym.symbol_id"
                            class="border-t border-border/50 bg-bg/50"
                        >
                            <div v-if="sourceLoading" class="flex items-center gap-2 text-text-dim text-xs py-6 justify-center">
                                <div class="w-3 h-3 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
                            </div>
                            <div v-else-if="sourceData?.source">
                                <CodeBlock
                                    :source="sourceData.source"
                                    :language="sym.language"
                                    :start-line="sourceData.line_start || 1"
                                />
                            </div>
                            <div v-else class="text-xs text-text-faint py-4 text-center">
                                Source not available
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- No results -->
        <div v-else-if="searched && !loading" class="text-center py-16 text-text-faint text-sm">
            No symbols found for "{{ query }}"
        </div>

        <!-- Initial -->
        <div v-else-if="!searched" class="text-center py-16 text-text-faint text-sm">
            Start typing to search across all indexed repositories
        </div>
    </div>
</template>
