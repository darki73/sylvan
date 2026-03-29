<script setup lang="ts">
import { ref, reactive, computed, onMounted } from "vue";
import { useWebSocket } from "@/composables/useWebSocket";

interface Smell {
    name: string;
    file: string;
    line: number;
    type: string;
    severity: string;
    message: string;
}

interface SecurityFinding {
    file: string;
    line: number;
    rule: string;
    severity: string;
    message: string;
    snippet: string;
}

interface Duplicate {
    hash: string;
    line_count: number;
    instances: Array<{ name: string; file: string; line: number }>;
}

interface QualityData {
    repo: string;
    test_coverage: number;
    uncovered_count: number;
    uncovered_symbols: string[];
    doc_coverage: number;
    type_coverage: number;
    smells: Smell[];
    smells_by_severity: Record<string, number>;
    security: SecurityFinding[];
    security_by_severity: Record<string, number>;
    duplicates: Duplicate[];
    error?: string;
}

interface RepoOption {
    id: number;
    name: string;
}

const { request } = useWebSocket();
const repos = reactive<RepoOption[]>([]);
const selectedRepo = ref("");
const loading = ref(false);
const reposLoading = ref(true);
const data = reactive<QualityData>({
    repo: "", test_coverage: 0, uncovered_count: 0, uncovered_symbols: [],
    doc_coverage: 0, type_coverage: 0, smells: [], smells_by_severity: {},
    security: [], security_by_severity: {}, duplicates: [],
});

const hasData = computed(() => !!data.repo && !data.error);

const severityColors: Record<string, string> = {
    critical: "#E84855",
    high: "#F0A030",
    medium: "#F1E05A",
    low: "#5BA4F5",
};

function parseSymbolId(sid: string): { name: string; file: string; kind: string } {
    // Format: "path/to/file.py::SymbolName#kind"
    const [filePart, rest] = sid.split("::");
    const [name, kind] = (rest || "").split("#");
    return { name: name || sid, file: filePart || "", kind: kind || "" };
}

function coverageColor(pct: number): string {
    if (pct >= 80) return "#3DD68C";
    if (pct >= 50) return "#F0A030";
    return "#E84855";
}

async function loadRepos() {
    reposLoading.value = true;
    try {
        const result = await request<{ repos: RepoOption[] }>("get_repositories");
        repos.splice(0, repos.length, ...result.repos);
        if (repos.length && !selectedRepo.value) {
            selectedRepo.value = repos[0].name;
            await analyze();
        }
    } finally {
        reposLoading.value = false;
    }
}

async function analyze() {
    if (!selectedRepo.value) return;
    loading.value = true;
    try {
        const result = await request<QualityData>("get_quality", { repo: selectedRepo.value });
        Object.assign(data, result);
    } finally {
        loading.value = false;
    }
}

onMounted(loadRepos);
</script>

<template>
    <div>
        <div class="mb-6 animate-in">
            <h1 class="text-2xl font-bold text-white tracking-tight">Quality</h1>
            <p class="text-sm text-text-dim mt-1">Code quality analysis per repository</p>
        </div>

        <!-- Repo selector -->
        <div class="flex items-center gap-3 mb-6 animate-in">
            <select
                v-model="selectedRepo"
                class="bg-surface border border-border rounded-lg px-4 py-2 text-sm font-mono text-white focus:border-accent/50 focus:outline-none transition-colors appearance-none cursor-pointer flex-1 max-w-xs"
                @change="analyze"
            >
                <option v-for="r in repos" :key="r.name" :value="r.name">{{ r.name }}</option>
            </select>
            <button
                :disabled="loading || !selectedRepo"
                class="px-4 py-2 text-xs font-mono rounded-lg bg-accent/10 border border-accent/30 text-accent hover:bg-accent/20 transition-colors disabled:opacity-50"
                @click="analyze"
            >
                {{ loading ? "Analyzing..." : "Analyze" }}
            </button>
        </div>

        <div v-if="loading" class="flex items-center gap-3 text-text-dim text-sm py-20 justify-center">
            <div class="w-4 h-4 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
            Analyzing...
        </div>

        <template v-else-if="hasData">
            <!-- Coverage cards -->
            <div class="grid grid-cols-3 gap-4 mb-6 animate-in">
                <div class="rounded-xl bg-surface border border-border p-5">
                    <div class="text-[10px] text-text-faint uppercase tracking-wider mb-2">Test Coverage</div>
                    <div class="flex items-baseline gap-2">
                        <span class="font-mono text-3xl font-bold" :style="{ color: coverageColor(data.test_coverage) }">
                            {{ data.test_coverage }}%
                        </span>
                    </div>
                    <div v-if="data.uncovered_count" class="text-[10px] text-text-faint mt-1">
                        {{ data.uncovered_count }} untested symbols
                    </div>
                </div>

                <div class="rounded-xl bg-surface border border-border p-5">
                    <div class="text-[10px] text-text-faint uppercase tracking-wider mb-2">Documentation</div>
                    <div class="flex items-baseline gap-2">
                        <span class="font-mono text-3xl font-bold" :style="{ color: coverageColor(data.doc_coverage) }">
                            {{ data.doc_coverage }}%
                        </span>
                    </div>
                    <div class="text-[10px] text-text-faint mt-1">symbols with docstrings</div>
                </div>

                <div class="rounded-xl bg-surface border border-border p-5">
                    <div class="text-[10px] text-text-faint uppercase tracking-wider mb-2">Type Coverage</div>
                    <div class="flex items-baseline gap-2">
                        <span class="font-mono text-3xl font-bold" :style="{ color: coverageColor(data.type_coverage) }">
                            {{ data.type_coverage }}%
                        </span>
                    </div>
                    <div class="text-[10px] text-text-faint mt-1">symbols with type hints</div>
                </div>
            </div>

            <!-- Smells + Security -->
            <div class="grid grid-cols-2 gap-6 mb-6">
                <!-- Code smells -->
                <div class="rounded-xl bg-surface border border-border p-5 animate-in">
                    <div class="flex items-center justify-between mb-3">
                        <h2 class="text-sm font-semibold text-white">Code Smells</h2>
                        <div class="flex gap-2">
                            <span v-for="(count, sev) in data.smells_by_severity" :key="sev" class="text-[10px] font-mono px-1.5 py-0.5 rounded" :style="{ color: severityColors[sev as string] || '#888', background: (severityColors[sev as string] || '#888') + '14' }">
                                {{ count }} {{ sev }}
                            </span>
                        </div>
                    </div>
                    <div v-if="!data.smells.length" class="text-xs text-text-faint py-4 text-center">No code smells detected</div>
                    <div v-else class="space-y-1 max-h-[400px] overflow-y-auto">
                        <div
                            v-for="(smell, i) in data.smells"
                            :key="i"
                            class="flex items-start gap-2 py-1.5 px-2 rounded hover:bg-surface-2/50 transition-colors text-xs"
                        >
                            <span class="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0" :style="{ background: severityColors[smell.severity] || '#888' }" />
                            <div class="min-w-0">
                                <div class="text-white font-mono truncate">{{ smell.name }}</div>
                                <div class="text-text-faint truncate">{{ smell.message }}</div>
                                <div class="text-text-faint font-mono text-[10px]">{{ smell.file }}:{{ smell.line }}</div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Security -->
                <div class="rounded-xl bg-surface border border-border p-5 animate-in delay-1">
                    <div class="flex items-center justify-between mb-3">
                        <h2 class="text-sm font-semibold text-white">Security</h2>
                        <div class="flex gap-2">
                            <span v-for="(count, sev) in data.security_by_severity" :key="sev" class="text-[10px] font-mono px-1.5 py-0.5 rounded" :style="{ color: severityColors[sev as string] || '#888', background: (severityColors[sev as string] || '#888') + '14' }">
                                {{ count }} {{ sev }}
                            </span>
                        </div>
                    </div>
                    <div v-if="!data.security.length" class="text-xs text-text-faint py-4 text-center">No security issues found</div>
                    <div v-else class="space-y-1 max-h-[400px] overflow-y-auto">
                        <div
                            v-for="(finding, i) in data.security"
                            :key="i"
                            class="flex items-start gap-2 py-1.5 px-2 rounded hover:bg-surface-2/50 transition-colors text-xs"
                        >
                            <span class="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0" :style="{ background: severityColors[finding.severity] || '#888' }" />
                            <div class="min-w-0">
                                <div class="text-white font-mono">{{ finding.rule }}</div>
                                <div class="text-text-faint truncate">{{ finding.message }}</div>
                                <div class="text-text-faint font-mono text-[10px]">{{ finding.file }}:{{ finding.line }}</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Duplicates -->
            <div v-if="data.duplicates.length" class="rounded-xl bg-surface border border-border p-5 animate-in delay-2">
                <h2 class="text-sm font-semibold text-white mb-3">Duplicated Code</h2>
                <div class="space-y-3">
                    <div
                        v-for="dup in data.duplicates"
                        :key="dup.hash"
                        class="rounded-lg bg-surface-2/50 p-3"
                    >
                        <div class="text-[10px] text-text-faint font-mono mb-2">
                            {{ dup.line_count }} lines, {{ dup.instances.length }} instances
                        </div>
                        <div class="space-y-0.5">
                            <div
                                v-for="inst in dup.instances"
                                :key="inst.file + inst.line"
                                class="text-xs font-mono text-text-dim"
                            >
                                <span class="text-white">{{ inst.name }}</span>
                                <span class="text-text-faint ml-2">{{ inst.file }}:{{ inst.line }}</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Uncovered symbols -->
            <div v-if="data.uncovered_symbols.length" class="rounded-xl bg-surface border border-border p-5 mt-6 animate-in delay-3">
                <h2 class="text-sm font-semibold text-white mb-3">
                    Untested Symbols
                    <span class="text-text-faint font-normal ml-2 text-xs">({{ data.uncovered_count }} total, showing {{ data.uncovered_symbols.length }})</span>
                </h2>
                <div class="space-y-0.5 max-h-[300px] overflow-y-auto">
                    <div
                        v-for="sid in data.uncovered_symbols"
                        :key="sid"
                        class="flex items-center gap-2 py-1 px-2 rounded hover:bg-surface-2/50 transition-colors text-xs"
                    >
                        <span class="text-[10px] font-mono text-text-faint w-12 shrink-0">{{ parseSymbolId(sid).kind }}</span>
                        <span class="font-mono text-white">{{ parseSymbolId(sid).name }}</span>
                        <span class="font-mono text-text-faint ml-auto text-[10px] truncate max-w-[300px]">{{ parseSymbolId(sid).file }}</span>
                    </div>
                </div>
            </div>
        </template>
    </div>
</template>
