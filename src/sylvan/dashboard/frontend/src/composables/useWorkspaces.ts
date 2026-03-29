import { reactive, ref, onMounted } from "vue";
import { useWebSocket } from "./useWebSocket";

export interface WorkspaceRepo {
    name: string;
    files: number;
    symbols: number;
    sections: number;
}

export interface Workspace {
    name: string;
    description: string;
    repo_count: number;
    total_files: number;
    total_symbols: number;
    total_sections: number;
    repos: WorkspaceRepo[];
}

export function useWorkspaces() {
    const workspaces = reactive<Workspace[]>([]);
    const loading = ref(true);

    const { request } = useWebSocket();

    async function fetch() {
        loading.value = true;
        try {
            const result = await request<{ workspaces: Workspace[] }>("get_workspaces");
            workspaces.splice(0, workspaces.length, ...result.workspaces);
        } finally {
            loading.value = false;
        }
    }

    onMounted(fetch);

    return { workspaces, loading, refresh: fetch };
}
