import { reactive, ref, onMounted, onUnmounted } from "vue";
import { useWebSocket } from "./useWebSocket";

export interface MemoryEntry {
    id: number;
    repo: string;
    repo_id: number;
    content: string;
    tags: string[];
    created_at: string;
    updated_at: string;
}

export interface PreferenceEntry {
    id: number;
    scope: string;
    scope_id: number | null;
    scope_name: string;
    key: string;
    instruction: string;
    created_at: string;
    updated_at: string;
}

export interface RepoOption {
    id: number;
    name: string;
}

export function useMemory() {
    const memories = reactive<MemoryEntry[]>([]);
    const loading = ref(true);
    const { request, on, off } = useWebSocket();

    async function fetch(repo: string = "") {
        loading.value = true;
        try {
            const result = await request<{ memories: MemoryEntry[] }>(
                "get_memories",
                repo ? { repo } : undefined,
            );
            memories.splice(0, memories.length, ...result.memories);
        } finally {
            loading.value = false;
        }
    }

    async function deleteEntry(repo: string, memoryId: number) {
        await request("delete_memory_entry", { repo, memory_id: memoryId });
    }

    function onMemoryChanged() {
        fetch();
    }

    onMounted(() => {
        fetch();
        on("memory_changed", onMemoryChanged);
    });

    onUnmounted(() => {
        off("memory_changed", onMemoryChanged);
    });

    return { memories, loading, refresh: fetch, deleteEntry };
}

export function usePreferences() {
    const preferences = reactive<PreferenceEntry[]>([]);
    const loading = ref(true);
    const { request, on, off } = useWebSocket();

    async function fetch() {
        loading.value = true;
        try {
            const result = await request<{ preferences: PreferenceEntry[]; count: number }>(
                "get_all_preferences",
            );
            preferences.splice(0, preferences.length, ...result.preferences);
        } finally {
            loading.value = false;
        }
    }

    async function save(key: string, instruction: string, scope: string, scopeId: number | null) {
        await request("save_preference_entry", {
            key,
            instruction,
            scope,
            scope_id: scopeId,
        });
    }

    async function deleteEntry(key: string, scope: string, scopeId: number | null) {
        await request("delete_preference_entry", {
            key,
            scope,
            scope_id: scopeId,
        });
    }

    function onPreferenceChanged() {
        fetch();
    }

    onMounted(() => {
        fetch();
        on("preference_changed", onPreferenceChanged);
    });

    onUnmounted(() => {
        off("preference_changed", onPreferenceChanged);
    });

    return { preferences, loading, refresh: fetch, save, deleteEntry };
}

export function useRepoOptions() {
    const repos = reactive<RepoOption[]>([]);
    const { request } = useWebSocket();

    async function fetch() {
        const result = await request<{ repos: RepoOption[] }>("get_repos_for_select");
        repos.splice(0, repos.length, ...result.repos);
    }

    onMounted(fetch);

    return { repos, refresh: fetch };
}
