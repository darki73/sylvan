<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from "vue";
import { useRoute } from "vue-router";

defineProps<{
    connected: boolean;
}>();

const route = useRoute();

const links = [
    { to: "/", label: "Overview" },
    { to: "/workspaces", label: "Workspaces" },
    { to: "/repositories", label: "Repositories" },
    { to: "/libraries", label: "Libraries" },
    { to: "/queue", label: "Queue" },
    { to: "/session", label: "Session" },
    { to: "/quality", label: "Quality" },
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

onMounted(() => {
    updatePeak();
    peakTimer = setInterval(updatePeak, 30000);
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
