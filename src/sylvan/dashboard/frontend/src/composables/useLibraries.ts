import { reactive, ref, computed, onMounted } from "vue";
import { useWebSocket } from "./useWebSocket";
import type { LibraryVersion, GroupedLibrary } from "@/interfaces";

export function useLibraries() {
    const raw = reactive<LibraryVersion[]>([]);
    const loading = ref(true);

    const { request } = useWebSocket();

    const grouped = computed<GroupedLibrary[]>(() => {
        const groups = new Map<string, GroupedLibrary>();
        for (const lib of raw) {
            const key = lib.package;
            if (!groups.has(key)) {
                groups.set(key, {
                    package: lib.package,
                    manager: lib.manager,
                    repo_url: lib.repo_url,
                    versions: [],
                    total_symbols: 0,
                });
            }
            const group = groups.get(key)!;
            group.versions.push(lib);
            group.total_symbols += lib.symbols;
            if (lib.repo_url && !group.repo_url) group.repo_url = lib.repo_url;
        }
        return [...groups.values()].sort((a, b) => b.total_symbols - a.total_symbols);
    });

    async function fetch() {
        loading.value = true;
        try {
            const result = await request<{ libraries: LibraryVersion[] }>("get_libraries");
            raw.splice(0, raw.length, ...result.libraries);
        } finally {
            loading.value = false;
        }
    }

    onMounted(fetch);

    return { libraries: grouped, raw, loading, refresh: fetch };
}
