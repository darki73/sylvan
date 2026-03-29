<script setup lang="ts">
import { ref, reactive, onMounted, computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useWebSocket } from "@/composables/useWebSocket";

interface RepoEntry {
    id: number;
    name: string;
    source_path: string;
    files: number;
    symbols: number;
    sections: number;
}

interface AvailableRepo {
    id: number;
    name: string;
}

interface WorkspaceData {
    id: number;
    name: string;
    description: string;
    created_at: string;
    repo_count: number;
    total_files: number;
    total_symbols: number;
    total_sections: number;
    repos: RepoEntry[];
    available_repos: AvailableRepo[];
}

const route = useRoute();
const router = useRouter();
const { request } = useWebSocket();
const wsName = route.params.name as string;

const data = reactive<WorkspaceData>({
    id: 0, name: "", description: "", created_at: "",
    repo_count: 0, total_files: 0, total_symbols: 0, total_sections: 0,
    repos: [], available_repos: [],
});
const loading = ref(true);
const editing = ref(false);
const editName = ref("");
const editDesc = ref("");
const showAddRepo = ref(false);
const confirmDelete = ref(false);

const sortedRepos = computed(() =>
    [...data.repos].sort((a, b) => a.name.localeCompare(b.name))
);

async function fetch() {
    loading.value = true;
    try {
        const result = await request<WorkspaceData>("get_workspace", { name: wsName });
        Object.assign(data, result);
    } finally {
        loading.value = false;
    }
}

function startEdit() {
    editName.value = data.name;
    editDesc.value = data.description;
    editing.value = true;
}

async function saveEdit() {
    await request("update_workspace", {
        name: wsName,
        new_name: editName.value !== data.name ? editName.value : "",
        description: editDesc.value,
    });
    editing.value = false;
    if (editName.value !== wsName) {
        router.replace(`/workspaces/${editName.value}`);
    }
    await fetch();
}

async function addRepo(repoId: number) {
    await request("workspace_add_repo", { name: data.name, repo_id: repoId });
    showAddRepo.value = false;
    await fetch();
}

async function removeRepo(repoId: number) {
    await request("workspace_remove_repo", { name: data.name, repo_id: repoId });
    await fetch();
}

async function deleteWorkspace() {
    await request("delete_workspace", { name: data.name });
    router.push("/workspaces");
}

onMounted(fetch);
</script>

<template>
    <div>
        <div class="mb-8 animate-in">
            <div class="flex items-center gap-3 mb-1">
                <RouterLink to="/workspaces" class="text-text-faint hover:text-text-dim transition-colors text-sm">
                    Workspaces
                </RouterLink>
                <span class="text-text-faint text-xs">/</span>
                <h1 class="text-2xl font-bold text-white tracking-tight">{{ data.name || wsName }}</h1>
            </div>
            <p v-if="data.description && !editing" class="text-sm text-text-dim mt-1">{{ data.description }}</p>
            <p v-if="data.created_at" class="text-[10px] text-text-faint mt-1 font-mono">
                created {{ data.created_at.slice(0, 10) }}
            </p>
        </div>

        <div v-if="loading" class="flex items-center gap-3 text-text-dim text-sm py-20 justify-center">
            <div class="w-4 h-4 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
            Loading...
        </div>

        <template v-else>
            <!-- Stats bar -->
            <div class="flex gap-6 mb-6 animate-in">
                <div>
                    <span class="font-mono text-2xl font-bold text-white">{{ data.total_files.toLocaleString() }}</span>
                    <span class="text-text-faint text-sm ml-1.5">files</span>
                </div>
                <div>
                    <span class="font-mono text-2xl font-bold text-accent">{{ data.total_symbols.toLocaleString() }}</span>
                    <span class="text-text-faint text-sm ml-1.5">symbols</span>
                </div>
                <div>
                    <span class="font-mono text-2xl font-bold text-info">{{ data.total_sections.toLocaleString() }}</span>
                    <span class="text-text-faint text-sm ml-1.5">docs</span>
                </div>
                <div>
                    <span class="font-mono text-2xl font-bold text-white">{{ data.repo_count }}</span>
                    <span class="text-text-faint text-sm ml-1.5">repos</span>
                </div>
            </div>

            <!-- Actions -->
            <div class="flex gap-2 mb-6 animate-in">
                <button
                    v-if="!editing"
                    class="px-3 py-1.5 text-xs font-mono rounded-lg border border-border text-text-dim hover:text-white hover:border-border-bright transition-colors"
                    @click="startEdit"
                >
                    Edit
                </button>
                <button
                    class="px-3 py-1.5 text-xs font-mono rounded-lg border border-border text-text-dim hover:text-accent hover:border-accent/30 transition-colors"
                    @click="showAddRepo = !showAddRepo"
                >
                    Add repo
                </button>
                <button
                    v-if="!confirmDelete"
                    class="px-3 py-1.5 text-xs font-mono rounded-lg border border-border text-text-dim hover:text-red-400 hover:border-red-400/30 transition-colors"
                    @click="confirmDelete = true"
                >
                    Delete
                </button>
                <div v-else class="flex items-center gap-2">
                    <span class="text-xs text-red-400">Delete workspace?</span>
                    <button
                        class="px-3 py-1.5 text-xs font-mono rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 hover:bg-red-500/20 transition-colors"
                        @click="deleteWorkspace"
                    >
                        Confirm
                    </button>
                    <button
                        class="px-3 py-1.5 text-xs font-mono rounded-lg border border-border text-text-dim hover:text-white transition-colors"
                        @click="confirmDelete = false"
                    >
                        Cancel
                    </button>
                </div>
            </div>

            <!-- Edit form -->
            <div v-if="editing" class="rounded-xl bg-surface border border-border p-5 mb-6 animate-in">
                <div class="space-y-3">
                    <div>
                        <label class="text-[10px] text-text-faint uppercase tracking-wider block mb-1">Name</label>
                        <input
                            v-model="editName"
                            class="w-full bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm font-mono text-white focus:border-accent/50 focus:outline-none transition-colors"
                        />
                    </div>
                    <div>
                        <label class="text-[10px] text-text-faint uppercase tracking-wider block mb-1">Description</label>
                        <input
                            v-model="editDesc"
                            class="w-full bg-surface-2 border border-border rounded-lg px-3 py-2 text-sm text-white focus:border-accent/50 focus:outline-none transition-colors"
                        />
                    </div>
                    <div class="flex gap-2">
                        <button
                            class="px-3 py-1.5 text-xs font-mono rounded-lg bg-accent/10 border border-accent/30 text-accent hover:bg-accent/20 transition-colors"
                            @click="saveEdit"
                        >
                            Save
                        </button>
                        <button
                            class="px-3 py-1.5 text-xs font-mono rounded-lg border border-border text-text-dim hover:text-white transition-colors"
                            @click="editing = false"
                        >
                            Cancel
                        </button>
                    </div>
                </div>
            </div>

            <!-- Add repo dropdown -->
            <div v-if="showAddRepo && data.available_repos.length" class="rounded-xl bg-surface border border-border p-4 mb-6 animate-in">
                <div class="text-[10px] text-text-faint uppercase tracking-wider mb-2">Available repositories</div>
                <div class="flex flex-wrap gap-2">
                    <button
                        v-for="repo in data.available_repos"
                        :key="repo.id"
                        class="px-3 py-1.5 text-xs font-mono rounded-lg border border-border text-text-dim hover:text-accent hover:border-accent/30 transition-colors"
                        @click="addRepo(repo.id)"
                    >
                        + {{ repo.name }}
                    </button>
                </div>
            </div>
            <div v-else-if="showAddRepo" class="rounded-xl bg-surface border border-border p-4 mb-6 animate-in">
                <div class="text-xs text-text-faint">All indexed repos are already in this workspace</div>
            </div>

            <!-- Repo cards -->
            <div class="grid grid-cols-2 gap-4 items-start">
                <div
                    v-for="(repo, i) in sortedRepos"
                    :key="repo.id"
                    class="group rounded-xl bg-surface border border-border p-5 transition-all duration-300 hover:border-accent/30 hover:shadow-[0_0_30px_-10px_var(--color-accent-glow)] animate-in"
                    :class="'delay-' + Math.min(i + 1, 5)"
                >
                    <div class="flex items-start justify-between mb-3">
                        <div>
                            <div class="font-mono text-sm font-semibold text-white group-hover:text-accent transition-colors">{{ repo.name }}</div>
                            <div v-if="repo.source_path" class="text-[10px] text-text-faint mt-0.5 truncate max-w-[280px]">{{ repo.source_path }}</div>
                        </div>
                        <button
                            class="text-text-faint hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100 text-xs"
                            title="Remove from workspace"
                            @click.stop="removeRepo(repo.id)"
                        >
                            &times;
                        </button>
                    </div>

                    <div class="flex gap-5 text-xs">
                        <div>
                            <span class="font-mono text-lg font-bold text-white">{{ repo.files }}</span>
                            <span class="text-text-faint ml-1">files</span>
                        </div>
                        <div>
                            <span class="font-mono text-lg font-bold text-accent">{{ repo.symbols }}</span>
                            <span class="text-text-faint ml-1">symbols</span>
                        </div>
                        <div>
                            <span class="font-mono text-lg font-bold text-info">{{ repo.sections }}</span>
                            <span class="text-text-faint ml-1">docs</span>
                        </div>
                    </div>
                </div>
            </div>
        </template>
    </div>
</template>
