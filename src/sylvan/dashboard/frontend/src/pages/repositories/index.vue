<script setup lang="ts">
import { ref, computed } from "vue";
import { useRouter } from "vue-router";
import { useRepositories } from "@/composables/useRepositories";
import { useWebSocket } from "@/composables/useWebSocket";
import { useQueue } from "@/composables/useQueue";
import RepoCard from "@/components/RepoCard.vue";

const router = useRouter();
const { repos, loading, refresh } = useRepositories();
const { request } = useWebSocket();
const { isRunning } = useQueue();

const search = ref("");
const showAdd = ref(false);
const addPath = ref("");
const addName = ref("");
const adding = ref(false);

const filtered = computed(() => {
    if (!search.value) return repos;
    const q = search.value.toLowerCase();
    return repos.filter(r => r.name.toLowerCase().includes(q));
});

async function addRepo() {
    if (!addPath.value) return;
    adding.value = true;
    try {
        const path = addPath.value;
        const parts = path.replace(/\\/g, "/").split("/");
        const name = addName.value || parts[parts.length - 1] || "repo";
        await request("reindex_repo", { path, name, force: false });
        router.push(`/repositories/${name}`);
    } finally {
        adding.value = false;
    }
}
</script>

<template>
    <div>
        <div class="mb-6 animate-in">
            <div class="flex items-center justify-between">
                <div>
                    <h1 class="text-2xl font-bold text-white tracking-tight">Repositories</h1>
                    <p class="text-sm text-text-dim mt-1">
                        <span class="font-mono text-accent">{{ repos.length }}</span> indexed repositories
                    </p>
                </div>
                <button
                    class="px-3 py-1.5 text-xs font-mono rounded-lg border border-border text-text-dim hover:text-accent hover:border-accent/30 transition-colors"
                    @click="showAdd = !showAdd"
                >
                    {{ showAdd ? "Cancel" : "Add Repository" }}
                </button>
            </div>
        </div>

        <!-- Add repo form -->
        <div v-if="showAdd" class="rounded-xl bg-surface border border-border p-5 mb-6 animate-in">
            <div class="space-y-3">
                <div>
                    <label class="text-[10px] text-text-faint uppercase tracking-wider block mb-1">Folder path</label>
                    <input
                        v-model="addPath"
                        placeholder="D:\Projects\my-project"
                        class="w-full bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm font-mono text-white placeholder:text-text-faint/40 focus:border-accent/50 focus:outline-none transition-colors"
                        @keydown.enter="addRepo"
                    />
                </div>
                <div>
                    <label class="text-[10px] text-text-faint uppercase tracking-wider block mb-1">Name (optional, defaults to folder name)</label>
                    <input
                        v-model="addName"
                        placeholder="my-project"
                        class="w-full bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm font-mono text-white placeholder:text-text-faint/40 focus:border-accent/50 focus:outline-none transition-colors"
                        @keydown.enter="addRepo"
                    />
                </div>
                <button
                    :disabled="!addPath || adding"
                    class="px-4 py-2 text-xs font-mono rounded-lg bg-accent/10 border border-accent/30 text-accent hover:bg-accent/20 transition-colors disabled:opacity-50"
                    @click="addRepo"
                >
                    {{ adding ? "Indexing..." : "Index" }}
                </button>
            </div>
        </div>

        <!-- Search -->
        <div class="mb-4 animate-in">
            <input
                v-model="search"
                placeholder="Filter repositories..."
                class="w-full bg-surface border border-border rounded-lg px-4 py-2.5 text-sm font-mono text-white placeholder:text-text-faint/40 focus:border-accent/50 focus:outline-none transition-colors"
            />
        </div>

        <div v-if="loading" class="flex items-center gap-3 text-text-dim text-sm py-20 justify-center">
            <div class="w-4 h-4 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
            Loading...
        </div>

        <div v-else-if="!filtered.length && search" class="text-center py-12 text-text-faint text-sm">
            No repositories matching "{{ search }}"
        </div>

        <div v-else class="grid grid-cols-2 gap-4">
            <RepoCard
                v-for="(repo, i) in filtered"
                :key="repo.name"
                :repo="repo"
                class="animate-in"
                :class="'delay-' + Math.min(i + 1, 5)"
            />
        </div>
    </div>
</template>
