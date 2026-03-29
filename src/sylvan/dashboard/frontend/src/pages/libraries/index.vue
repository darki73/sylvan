<script setup lang="ts">
import { ref, computed } from "vue";
import { useRouter } from "vue-router";
import { useLibraries } from "@/composables/useLibraries";
import { useWebSocket } from "@/composables/useWebSocket";
import LibraryCard from "@/components/LibraryCard.vue";

const router = useRouter();
const { libraries, raw, loading, refresh } = useLibraries();
const { request } = useWebSocket();

const filter = ref("");
const showAdd = ref(false);
const addManager = ref("pip");
const addName = ref("");
const addVersion = ref("");
const adding = ref(false);

const managers = [
    { value: "pip", label: "pip", placeholder: "django" },
    { value: "npm", label: "npm", placeholder: "react" },
    { value: "cargo", label: "cargo", placeholder: "serde" },
    { value: "go", label: "go", placeholder: "github.com/gin-gonic/gin" },
    { value: "composer", label: "composer", placeholder: "laravel/framework" },
];

const currentManager = computed(() => managers.find(m => m.value === addManager.value)!);

const filtered = computed(() => {
    if (!filter.value) return libraries.value;
    const q = filter.value.toLowerCase();
    return libraries.value.filter((l) => l.package.toLowerCase().includes(q));
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

function goToLibrary(packageName: string) {
    router.push(`/libraries/${encodeURIComponent(packageName)}`);
}
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
                <button
                    class="px-3 py-1.5 text-xs font-mono rounded-lg border border-border text-text-dim hover:text-accent hover:border-accent/30 transition-colors"
                    @click="showAdd = !showAdd"
                >
                    {{ showAdd ? "Cancel" : "Add Library" }}
                </button>
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

        <!-- Search -->
        <div class="mb-4 animate-in">
            <input
                v-model="filter"
                placeholder="Filter libraries..."
                class="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-sm font-mono text-white placeholder:text-text-faint/40 focus:border-accent/50 focus:outline-none transition-colors"
            />
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
