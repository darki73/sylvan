<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { useRouter } from "vue-router";
import { useLibraries } from "@/composables/useLibraries";
import { useWebSocket } from "@/composables/useWebSocket";
import LibraryCard from "@/components/LibraryCard.vue";

const router = useRouter();
const { libraries, raw, loading, refresh } = useLibraries();
const { request } = useWebSocket();

const filter = ref("");
const managerFilter = ref("all");
const showAdd = ref(false);
const addManager = ref("pip");
const addName = ref("");
const addVersion = ref("");
const adding = ref(false);

const showMappings = ref(false);
const mappings = ref<{ spec: string; repo_url: string }[]>([]);
const newMappingSpec = ref("");
const newMappingUrl = ref("");
const loadingMappings = ref(false);

const managers = [
    { value: "pip", label: "pip", placeholder: "django" },
    { value: "npm", label: "npm", placeholder: "react" },
    { value: "cargo", label: "cargo", placeholder: "serde" },
    { value: "go", label: "go", placeholder: "github.com/gin-gonic/gin" },
    { value: "composer", label: "composer", placeholder: "laravel/framework" },
];

const availableManagers = computed(() => {
    const seen = new Set(libraries.value.map(l => l.manager));
    return managers.filter(m => seen.has(m.value));
});

const currentManager = computed(() => managers.find(m => m.value === addManager.value)!);

const filtered = computed(() => {
    let result = libraries.value;
    if (managerFilter.value !== "all") {
        result = result.filter(l => l.manager === managerFilter.value);
    }
    if (filter.value) {
        const q = filter.value.toLowerCase();
        result = result.filter(l => l.package.toLowerCase().includes(q));
    }
    return result;
});

const addSpec = computed(() => {
    if (!addName.value) return "";
    const version = addVersion.value ? `@${addVersion.value}` : "";
    return `${addManager.value}/${addName.value}${version}`;
});

async function addLibrary() {
    if (!addSpec.value) return;
    adding.value = true;
    try {
        await request("add_library", { package: addSpec.value });
        showAdd.value = false;
        addName.value = "";
        addVersion.value = "";
        refresh();
    } finally {
        adding.value = false;
    }
}

async function fetchMappings() {
    loadingMappings.value = true;
    try {
        const result = await request<{ mappings: { spec: string; repo_url: string }[] }>("get_library_mappings");
        mappings.value = result.mappings;
    } finally {
        loadingMappings.value = false;
    }
}

async function addMapping() {
    if (!newMappingSpec.value || !newMappingUrl.value) return;
    try {
        await request("add_library_mapping", { spec: newMappingSpec.value, repo_url: newMappingUrl.value });
        newMappingSpec.value = "";
        newMappingUrl.value = "";
        await fetchMappings();
    } catch {
        // request handles errors
    }
}

async function removeMapping(spec: string) {
    try {
        await request("remove_library_mapping", { spec });
        await fetchMappings();
    } catch {
        // request handles errors
    }
}

function goToLibrary(packageName: string) {
    router.push(`/libraries/${encodeURIComponent(packageName)}`);
}

onMounted(fetchMappings);
</script>

<template>
    <div>
        <div class="mb-6 animate-in">
            <div class="flex items-center justify-between">
                <div>
                    <h1 class="text-2xl font-bold text-white tracking-tight">Libraries</h1>
                    <p class="text-sm text-text-dim mt-1">
                        <span class="font-mono text-accent">{{ libraries.length }}</span> packages,
                        <span class="font-mono">{{ raw.length }}</span> versions indexed
                    </p>
                </div>
                <div class="flex gap-2">
                    <button
                        class="px-3 py-1.5 text-xs font-mono rounded-lg border border-border text-text-dim hover:text-accent hover:border-accent/30 transition-colors"
                        @click="showMappings = !showMappings"
                    >
                        {{ showMappings ? "Hide Mappings" : "Mappings" }}
                    </button>
                    <button
                        class="px-3 py-1.5 text-xs font-mono rounded-lg border border-border text-text-dim hover:text-accent hover:border-accent/30 transition-colors"
                        @click="showAdd = !showAdd"
                    >
                        {{ showAdd ? "Cancel" : "Add Library" }}
                    </button>
                </div>
            </div>
        </div>

        <!-- Add library form -->
        <div v-if="showAdd" class="rounded-xl bg-surface border border-border p-5 mb-6 animate-in">
            <div class="flex gap-3 items-end">
                <div class="w-36">
                    <label class="text-[10px] text-text-faint uppercase tracking-wider block mb-1">Manager</label>
                    <select
                        v-model="addManager"
                        class="w-full bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm font-mono text-white focus:border-accent/50 focus:outline-none transition-colors appearance-none cursor-pointer"
                    >
                        <option v-for="m in managers" :key="m.value" :value="m.value">{{ m.label }}</option>
                    </select>
                </div>
                <div class="flex-1">
                    <label class="text-[10px] text-text-faint uppercase tracking-wider block mb-1">Package name</label>
                    <input
                        v-model="addName"
                        :placeholder="currentManager.placeholder"
                        class="w-full bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm font-mono text-white placeholder:text-text-faint/40 focus:border-accent/50 focus:outline-none transition-colors"
                        @keydown.enter="addLibrary"
                    />
                </div>
                <div class="w-32">
                    <label class="text-[10px] text-text-faint uppercase tracking-wider block mb-1">Version</label>
                    <input
                        v-model="addVersion"
                        placeholder="latest"
                        class="w-full bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm font-mono text-white placeholder:text-text-faint/40 focus:border-accent/50 focus:outline-none transition-colors"
                        @keydown.enter="addLibrary"
                    />
                </div>
                <button
                    :disabled="!addName || adding"
                    class="px-4 py-2 text-xs font-mono rounded-lg bg-accent/10 border border-accent/30 text-accent hover:bg-accent/20 transition-colors disabled:opacity-50 shrink-0"
                    @click="addLibrary"
                >
                    {{ adding ? "Indexing..." : "Index" }}
                </button>
            </div>
            <div v-if="addSpec" class="text-[10px] text-text-faint font-mono mt-2">
                {{ addSpec }}
            </div>
        </div>

        <!-- Mappings section -->
        <div v-if="showMappings" class="rounded-xl bg-surface border border-border p-5 mb-6 animate-in">
            <h2 class="text-sm font-mono text-text-dim mb-3">Package Mappings</h2>

            <div v-if="loadingMappings" class="flex items-center gap-3 text-text-dim text-sm py-4 justify-center">
                <div class="w-4 h-4 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
                Loading...
            </div>

            <template v-else>
                <div v-if="!mappings.length" class="text-sm text-text-faint py-4 text-center">
                    No package mappings configured
                </div>

                <div v-else class="space-y-1 mb-4">
                    <div
                        v-for="m in mappings"
                        :key="m.spec"
                        class="flex items-center gap-3 px-3 py-2 rounded-lg bg-surface-2 border border-border group"
                    >
                        <span class="font-mono text-sm text-white shrink-0">{{ m.spec }}</span>
                        <span class="font-mono text-xs text-text-dim truncate flex-1">{{ m.repo_url }}</span>
                        <button
                            class="text-text-faint hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100 shrink-0"
                            @click="removeMapping(m.spec)"
                        >
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                            </svg>
                        </button>
                    </div>
                </div>

                <div class="flex gap-3 items-end">
                    <div class="flex-1">
                        <label class="text-[10px] text-text-faint uppercase tracking-wider block mb-1">Spec</label>
                        <input
                            v-model="newMappingSpec"
                            placeholder="pip/package"
                            class="w-full bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm font-mono text-white placeholder:text-text-faint/40 focus:border-accent/50 focus:outline-none transition-colors"
                            @keydown.enter="addMapping"
                        />
                    </div>
                    <div class="flex-1">
                        <label class="text-[10px] text-text-faint uppercase tracking-wider block mb-1">Repository URL</label>
                        <input
                            v-model="newMappingUrl"
                            placeholder="https://github.com/owner/repo"
                            class="w-full bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm font-mono text-white placeholder:text-text-faint/40 focus:border-accent/50 focus:outline-none transition-colors"
                            @keydown.enter="addMapping"
                        />
                    </div>
                    <button
                        :disabled="!newMappingSpec || !newMappingUrl"
                        class="px-4 py-2 text-xs font-mono rounded-lg bg-accent/10 border border-accent/30 text-accent hover:bg-accent/20 transition-colors disabled:opacity-50 shrink-0"
                        @click="addMapping"
                    >
                        Add
                    </button>
                </div>
            </template>
        </div>

        <!-- Search + manager filter -->
        <div class="mb-4 animate-in">
            <input
                v-model="filter"
                placeholder="Filter libraries..."
                class="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-sm font-mono text-white placeholder:text-text-faint/40 focus:border-accent/50 focus:outline-none transition-colors"
            />
            <div v-if="availableManagers.length > 1" class="flex gap-2 mt-3">
                <button
                    class="px-3 py-1 text-xs font-mono rounded-lg border transition-colors"
                    :class="managerFilter === 'all'
                        ? 'border-accent/50 bg-accent/10 text-accent'
                        : 'border-border text-text-dim hover:text-accent hover:border-accent/30'"
                    @click="managerFilter = 'all'"
                >
                    All
                </button>
                <button
                    v-for="m in availableManagers"
                    :key="m.value"
                    class="px-3 py-1 text-xs font-mono rounded-lg border transition-colors"
                    :class="managerFilter === m.value
                        ? 'border-accent/50 bg-accent/10 text-accent'
                        : 'border-border text-text-dim hover:text-accent hover:border-accent/30'"
                    @click="managerFilter = m.value"
                >
                    {{ m.label }}
                </button>
            </div>
        </div>

        <div v-if="loading" class="flex items-center gap-3 text-text-dim text-sm py-20 justify-center">
            <div class="w-4 h-4 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
            Loading...
        </div>

        <div v-else-if="!filtered.length && filter" class="text-center py-12 text-text-faint text-sm">
            No libraries matching "{{ filter }}"
        </div>

        <div v-else class="grid grid-cols-3 gap-4">
            <LibraryCard
                v-for="lib in filtered"
                :key="lib.package"
                :library="lib"
                class="animate-in cursor-pointer"
                @click="goToLibrary(lib.package)"
            />
        </div>
    </div>
</template>
