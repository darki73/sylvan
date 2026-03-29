<script setup lang="ts">
import { ref, reactive, onMounted, computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useWebSocket } from "@/composables/useWebSocket";

interface VersionEntry {
    name: string;
    version: string;
    manager: string;
    repo_url: string;
    source_path: string;
    indexed_at: string;
    files: number;
    symbols: number;
    sections: number;
}

interface LibraryData {
    package: string;
    manager: string;
    repo_url: string;
    versions: VersionEntry[];
}

const managerColors: Record<string, string> = {
    pip: "#5BA4F5",
    npm: "#E84855",
    go: "#3DD68C",
    cargo: "#F0A030",
    composer: "#F28D1A",
};

const route = useRoute();
const router = useRouter();
const { request } = useWebSocket();
const packageName = decodeURIComponent(route.params.name as string);

const data = reactive<LibraryData>({
    package: "", manager: "", repo_url: "", versions: [],
});
const loading = ref(true);
const selectedVersion = ref(0);
const confirmDelete = ref<string | null>(null);
const deleting = ref(false);

const selected = computed(() => data.versions[selectedVersion.value]);
const managerColor = computed(() => managerColors[data.manager] || "#888");

async function fetch() {
    loading.value = true;
    try {
        const result = await request<LibraryData>("get_library", { package: packageName });
        Object.assign(data, result);
    } finally {
        loading.value = false;
    }
}

async function deleteVersion(name: string) {
    deleting.value = true;
    try {
        await request("delete_library", { name });
        if (data.versions.length <= 1) {
            router.push("/libraries");
        } else {
            await fetch();
            selectedVersion.value = 0;
            confirmDelete.value = null;
        }
    } finally {
        deleting.value = false;
    }
}

onMounted(fetch);
</script>

<template>
    <div>
        <!-- Header -->
        <div class="mb-6 animate-in">
            <div class="flex items-center gap-3 mb-1">
                <RouterLink to="/libraries" class="text-text-faint hover:text-text-dim transition-colors text-sm">
                    Libraries
                </RouterLink>
                <span class="text-text-faint text-xs">/</span>
                <span
                    v-if="data.manager"
                    class="px-1.5 py-0.5 rounded text-[9px] font-mono font-bold"
                    :style="{ background: managerColor + '14', color: managerColor }"
                >
                    {{ data.manager }}
                </span>
                <h1 class="text-2xl font-bold text-white tracking-tight">{{ data.package || packageName }}</h1>
            </div>
            <div class="flex items-center gap-3 mt-1">
                <a v-if="data.repo_url" :href="data.repo_url" target="_blank" class="text-xs text-accent hover:underline">
                    {{ data.repo_url.replace("https://github.com/", "") }}
                </a>
                <span class="text-[10px] text-text-faint font-mono">{{ data.versions.length }} version{{ data.versions.length !== 1 ? "s" : "" }} indexed</span>
            </div>
        </div>

        <div v-if="loading" class="flex items-center gap-3 text-text-dim text-sm py-20 justify-center">
            <div class="w-4 h-4 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
            Loading...
        </div>

        <template v-else-if="data.versions.length">
            <!-- Version selector -->
            <div class="flex gap-2 mb-6 animate-in">
                <button
                    v-for="(v, i) in data.versions"
                    :key="v.name"
                    class="px-3 py-1.5 text-xs font-mono rounded-lg transition-all duration-200"
                    :class="i === selectedVersion
                        ? 'bg-surface-2 text-white border border-border-bright shadow-sm'
                        : 'text-text-faint border border-transparent hover:text-text-dim hover:border-border'"
                    @click="selectedVersion = i"
                >
                    v{{ v.version }}
                </button>
            </div>

            <!-- Selected version stats -->
            <div v-if="selected" class="animate-in">
                <div class="flex items-center justify-between mb-6">
                    <div class="flex gap-6">
                        <div>
                            <span class="font-mono text-2xl font-bold text-white">{{ selected.files.toLocaleString() }}</span>
                            <span class="text-text-faint text-sm ml-1.5">files</span>
                        </div>
                        <div>
                            <span class="font-mono text-2xl font-bold" :style="{ color: managerColor }">{{ selected.symbols.toLocaleString() }}</span>
                            <span class="text-text-faint text-sm ml-1.5">symbols</span>
                        </div>
                        <div>
                            <span class="font-mono text-2xl font-bold text-info">{{ selected.sections.toLocaleString() }}</span>
                            <span class="text-text-faint text-sm ml-1.5">docs</span>
                        </div>
                    </div>
                    <div class="flex gap-2">
                        <button
                            v-if="confirmDelete !== selected.name"
                            class="px-3 py-1.5 text-xs font-mono rounded-lg border border-border text-text-dim hover:text-red-400 hover:border-red-400/30 transition-colors"
                            @click="confirmDelete = selected.name"
                        >
                            Delete version
                        </button>
                        <div v-else class="flex items-center gap-2">
                            <span class="text-xs text-red-400">Delete v{{ selected.version }}?</span>
                            <button
                                :disabled="deleting"
                                class="px-3 py-1.5 text-xs font-mono rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 hover:bg-red-500/20 transition-colors disabled:opacity-50 flex items-center gap-1.5"
                                @click="deleteVersion(selected.name)"
                            >
                                <div v-if="deleting" class="w-3 h-3 border-2 border-red-400/30 border-t-red-400 rounded-full animate-spin" />
                                {{ deleting ? "Deleting..." : "Confirm" }}
                            </button>
                            <button
                                v-if="!deleting"
                                class="px-3 py-1.5 text-xs font-mono rounded-lg border border-border text-text-dim hover:text-white transition-colors"
                                @click="confirmDelete = null"
                            >
                                Cancel
                            </button>
                        </div>
                    </div>
                </div>

                <!-- Info card -->
                <div class="rounded-xl bg-surface border border-border p-5 animate-in">
                    <div class="grid grid-cols-2 gap-4 text-xs">
                        <div>
                            <span class="text-text-faint">Name</span>
                            <div class="font-mono text-white mt-0.5">{{ selected.name }}</div>
                        </div>
                        <div>
                            <span class="text-text-faint">Version</span>
                            <div class="font-mono text-white mt-0.5">{{ selected.version }}</div>
                        </div>
                        <div>
                            <span class="text-text-faint">Indexed</span>
                            <div class="font-mono text-white mt-0.5">{{ selected.indexed_at?.slice(0, 10) || "-" }}</div>
                        </div>
                        <div>
                            <span class="text-text-faint">Source</span>
                            <div class="font-mono text-text-dim mt-0.5 truncate">{{ selected.source_path || "-" }}</div>
                        </div>
                    </div>
                </div>

                <!-- Version comparison table (if multiple versions) -->
                <div v-if="data.versions.length > 1" class="rounded-xl bg-surface border border-border mt-4 animate-in delay-1">
                    <table class="w-full text-xs">
                        <thead>
                            <tr class="text-text-faint border-b border-border">
                                <th class="text-left font-normal px-5 py-2.5">Version</th>
                                <th class="text-right font-normal px-3 py-2.5">Files</th>
                                <th class="text-right font-normal px-3 py-2.5">Symbols</th>
                                <th class="text-right font-normal px-3 py-2.5">Docs</th>
                                <th class="text-right font-normal px-5 py-2.5">Indexed</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr
                                v-for="(v, i) in data.versions"
                                :key="v.name"
                                class="border-t border-border/50 cursor-pointer transition-colors"
                                :class="i === selectedVersion ? 'bg-accent/5' : 'hover:bg-surface-2/50'"
                                @click="selectedVersion = i"
                            >
                                <td class="px-5 py-2.5 font-mono text-white">v{{ v.version }}</td>
                                <td class="text-right px-3 py-2.5 font-mono text-text-dim">{{ v.files.toLocaleString() }}</td>
                                <td class="text-right px-3 py-2.5 font-mono" :style="{ color: managerColor }">{{ v.symbols.toLocaleString() }}</td>
                                <td class="text-right px-3 py-2.5 font-mono text-info/70">{{ v.sections.toLocaleString() }}</td>
                                <td class="text-right px-5 py-2.5 font-mono text-text-faint">{{ v.indexed_at?.slice(0, 10) || "-" }}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </template>
    </div>
</template>
