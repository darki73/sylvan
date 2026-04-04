<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import { useRoute } from "vue-router";
import { useWebSocket } from "@/composables/useWebSocket";

defineProps<{
    connected: boolean;
}>();

const route = useRoute();
const { request } = useWebSocket();

const links = [
    { to: "/", label: "Overview" },
    { to: "/workspaces", label: "Workspaces" },
    { to: "/repositories", label: "Repositories" },
    { to: "/libraries", label: "Libraries" },
    { to: "/queue", label: "Queue" },
    { to: "/session", label: "Session" },
    { to: "/quality", label: "Quality" },
    { to: "/memory", label: "Memory" },
    { to: "/search", label: "Search" },
    { to: "/history", label: "History" },
];

function isActive(path: string): boolean {
    if (path === "/") return route.path === "/";
    return route.path.startsWith(path);
}

const isPeak = ref(false);
const peakLabel = ref("");
let peakTimer: ReturnType<typeof setInterval> | null = null;

function updatePeak() {
    const now = new Date();
    const utcHour = now.getUTCHours();
    const utcDay = now.getUTCDay();
    const isWeekend = utcDay === 0 || utcDay === 6;
    isPeak.value = !isWeekend && utcHour >= 13 && utcHour < 19;
    peakLabel.value = isPeak.value ? "peak" : "off-peak";
}

const version = ref("");
const updateAvailable = ref(false);
const latestVersion = ref("");
const upgradeCommand = ref("");

async function fetchVersion() {
    try {
        const result = await request<{
            version: string;
            latest: string | null;
            upgrade: string | null;
            update_available: boolean;
        }>("get_version_info");
        version.value = result.version;
        updateAvailable.value = result.update_available;
        latestVersion.value = result.latest || "";
        upgradeCommand.value = result.upgrade || "";
    } catch {
        // silent
    }
}

onMounted(() => {
    updatePeak();
    peakTimer = setInterval(updatePeak, 30000);
    fetchVersion();
});

onUnmounted(() => {
    if (peakTimer) clearInterval(peakTimer);
});
</script>

<template>
    <nav class="border-b border-border bg-bg/80 backdrop-blur-md sticky top-0 z-50">
        <div class="max-w-6xl mx-auto px-6 flex items-center h-11 gap-6">
            <RouterLink to="/" class="font-mono font-bold text-sm tracking-wider text-accent hover:text-white transition-colors">
                sylvan
            </RouterLink>
            <div class="flex items-center gap-0.5">
                <RouterLink
                    v-for="link in links"
                    :key="link.to"
                    :to="link.to"
                    class="px-3 py-1 text-[11px] font-medium rounded-md transition-all duration-200"
                    :class="isActive(link.to)
                        ? 'bg-surface-2 text-white shadow-sm'
                        : 'text-text-dim hover:text-white hover:bg-surface/50'"
                >
                    {{ link.label }}
                </RouterLink>
            </div>
            <div class="ml-auto flex items-center gap-4">
                <div v-if="version" class="flex items-center gap-1.5 group relative">
                    <span class="text-[10px] font-mono" :class="updateAvailable ? 'text-warning' : 'text-text-faint'">
                        v{{ version }}
                    </span>
                    <div
                        v-if="updateAvailable"
                        class="w-1.5 h-1.5 rounded-full bg-warning shadow-[0_0_6px_var(--color-warning)] animate-pulse"
                    />
                    <div
                        v-if="updateAvailable"
                        class="absolute top-full right-0 mt-2 w-56 rounded-lg bg-surface border border-border shadow-xl p-3 opacity-0 pointer-events-none group-hover:opacity-100 group-hover:pointer-events-auto transition-opacity z-50"
                    >
                        <div class="text-[10px] text-text-dim mb-2">
                            <span class="text-warning font-mono">v{{ latestVersion }}</span> available
                        </div>
                        <code class="text-[10px] font-mono text-accent bg-bg/50 px-2 py-1 rounded block">{{ upgradeCommand }}</code>
                    </div>
                </div>
                <div class="flex items-center gap-1.5">
                    <div
                        class="w-1.5 h-1.5 rounded-full transition-colors"
                        :class="isPeak ? 'bg-warning shadow-[0_0_6px_var(--color-warning)]' : 'bg-accent shadow-[0_0_6px_var(--color-accent)]'"
                    />
                    <span class="text-[10px] font-mono" :class="isPeak ? 'text-warning' : 'text-text-faint'">{{ peakLabel }}</span>
                </div>
                <div class="flex items-center gap-1.5">
                    <div
                        class="w-1.5 h-1.5 rounded-full transition-colors"
                        :class="connected ? 'bg-accent shadow-[0_0_6px_var(--color-accent)]' : 'bg-danger shadow-[0_0_6px_var(--color-danger)]'"
                    />
                    <span class="text-[10px] font-mono text-text-faint">{{ connected ? "live" : "offline" }}</span>
                </div>
            </div>
        </div>
    </nav>
</template>
