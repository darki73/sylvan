import { reactive, ref, onMounted } from "vue";
import { useWebSocket } from "./useWebSocket";
import type { RepoStats } from "@/interfaces";

export function useRepositories() {
    const repos = reactive<RepoStats[]>([]);
    const loading = ref(true);

    const { request } = useWebSocket();

    async function fetch() {
        loading.value = true;
        try {
            const result = await request<{ repos: RepoStats[] }>("get_repositories");
            repos.splice(0, repos.length, ...result.repos);
        } finally {
            loading.value = false;
        }
    }

    onMounted(fetch);

    return { repos, loading, refresh: fetch };
}
