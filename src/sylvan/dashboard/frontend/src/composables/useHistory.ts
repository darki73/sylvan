import { reactive, ref, onMounted } from "vue";
import { useWebSocket } from "./useWebSocket";
import type { CodingSession } from "@/interfaces";

interface PaginatedHistory {
    coding_history: CodingSession[];
    total: number;
    page: number;
    per_page: number;
    total_pages: number;
}

export function useHistory(perPage: number = 20) {
    const sessions = reactive<CodingSession[]>([]);
    const loading = ref(true);
    const page = ref(1);
    const total = ref(0);
    const totalPages = ref(1);

    const { request } = useWebSocket();

    async function fetch(p: number = page.value) {
        loading.value = true;
        try {
            const result = await request<PaginatedHistory>("get_history", { page: p, per_page: perPage });
            sessions.splice(0, sessions.length, ...result.coding_history);
            total.value = result.total;
            page.value = result.page;
            totalPages.value = result.total_pages;
        } finally {
            loading.value = false;
        }
    }

    function goToPage(p: number) {
        if (p >= 1 && p <= totalPages.value) {
            fetch(p);
        }
    }

    onMounted(() => fetch(1));

    return { sessions, loading, page, total, totalPages, goToPage, refresh: fetch };
}
