<script setup lang="ts">
import { computed } from "vue";
import type { GroupedLibrary } from "@/interfaces";

const props = defineProps<{
    library: GroupedLibrary;
}>();

const latest = computed(() => props.library.versions[0]);

const managerStyles: Record<string, { color: string }> = {
    pip: { color: "#5BA4F5" },
    npm: { color: "#E84855" },
    go: { color: "#3DD68C" },
    cargo: { color: "#F0A030" },
    composer: { color: "#F28D1A" },
};

const langColors: Record<string, string> = {
    python: "#3572A5", typescript: "#3178C6", javascript: "#F1E05A",
    go: "#00ADD8", rust: "#DEA584", java: "#B07219", php: "#4F5D95",
    ruby: "#CC342D", c: "#555555", cpp: "#F34B7D", vue: "#41B883",
};

function getColor(lang: string): string {
    return langColors[lang.toLowerCase()] || "#888";
}

const ms = computed(() => managerStyles[props.library.manager.toLowerCase()] ?? { color: "#888" });

const MAX_LANGS = 8;

const langEntries = computed(() => {
    const langs = latest.value?.languages;
    if (!langs) return [];
    const entries = Object.entries(langs);
    const total = entries.reduce((sum, [, count]) => sum + count, 0);
    return entries
        .map(([lang, count]) => ({
            lang, count, pct: total > 0 ? Math.round((count / total) * 100) : 0,
        }))
        .filter(e => e.pct > 0)
        .slice(0, MAX_LANGS);
});
</script>

<template>
    <div class="group rounded-xl bg-surface border border-border p-5 transition-all duration-300 hover:border-accent/30 hover:shadow-[0_0_30px_-10px_var(--color-accent-glow)]">
        <div class="flex items-start justify-between mb-3">
            <div>
                <div class="flex items-center gap-2">
                    <span
                        class="px-1.5 py-0.5 rounded text-[9px] font-mono font-bold"
                        :style="{ background: ms.color + '14', color: ms.color }"
                    >
                        {{ library.manager }}
                    </span>
                    <span class="font-mono text-sm font-semibold text-white group-hover:text-accent transition-colors">{{ library.package }}</span>
                </div>
                <div class="text-[10px] text-text-faint mt-0.5">
                    v{{ latest?.version }}
                    <span v-if="library.versions.length > 1" class="ml-1">({{ library.versions.length }} versions)</span>
                </div>
            </div>
            <svg class="w-4 h-4 text-text-faint opacity-0 group-hover:opacity-100 transition-opacity" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
            </svg>
        </div>

        <div class="flex gap-5 text-xs mb-4">
            <div>
                <span class="font-mono text-lg font-bold text-white">{{ (latest?.files ?? 0).toLocaleString() }}</span>
                <span class="text-text-faint ml-1">files</span>
            </div>
            <div>
                <span class="font-mono text-lg font-bold" :style="{ color: ms.color }">{{ (latest?.symbols ?? 0).toLocaleString() }}</span>
                <span class="text-text-faint ml-1">symbols</span>
            </div>
            <div>
                <span class="font-mono text-lg font-bold text-info">{{ (latest?.sections ?? 0).toLocaleString() }}</span>
                <span class="text-text-faint ml-1">docs</span>
            </div>
        </div>

        <div v-if="langEntries.length" class="space-y-2">
            <div class="stacked-bar">
                <div
                    v-for="entry in langEntries"
                    :key="entry.lang"
                    :style="{ width: entry.pct + '%', background: getColor(entry.lang) }"
                />
            </div>
            <div class="flex flex-wrap gap-x-3 gap-y-1">
                <span v-for="entry in langEntries" :key="entry.lang" class="text-[10px] font-mono text-text-faint">
                    <span class="inline-block w-1.5 h-1.5 rounded-full mr-1" :style="{ background: getColor(entry.lang) }" />
                    {{ entry.lang }} {{ entry.pct }}%
                </span>
            </div>
        </div>
    </div>
</template>
