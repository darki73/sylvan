<script setup lang="ts">
import type { RepoStats } from "@/interfaces";
import { computed } from "vue";

const props = defineProps<{
    repo: RepoStats;
}>();

const MAX_LANGS = 8;

const langEntries = computed(() => {
    if (!props.repo.languages) return [];
    const entries = Object.entries(props.repo.languages);
    const total = entries.reduce((sum, [, count]) => sum + count, 0);
    return entries
        .map(([lang, count]) => ({
            lang,
            count,
            pct: total > 0 ? Math.round((count / total) * 100) : 0,
        }))
        .filter(e => e.pct > 0)
        .slice(0, MAX_LANGS);
});

const langColors: Record<string, string> = {
    python: "#3572A5",
    typescript: "#3178C6",
    javascript: "#F1E05A",
    go: "#00ADD8",
    rust: "#DEA584",
    java: "#B07219",
    php: "#4F5D95",
    ruby: "#CC342D",
    c: "#555555",
    cpp: "#F34B7D",
    c_sharp: "#178600",
    swift: "#F05138",
    kotlin: "#A97BFF",
    scala: "#C22D40",
    dart: "#00B4AB",
    elixir: "#6E4A7E",
    lua: "#000080",
    perl: "#0298C3",
    haskell: "#5e5086",
    erlang: "#B83998",
    bash: "#89E051",
    sql: "#E38C00",
    css: "#563D7C",
    html: "#E34C26",
    vue: "#41B883",
    tsx: "#3178C6",
    yaml: "#CB171E",
    toml: "#9C4121",
    json: "#A0A0A0",
    markdown: "#083FA1",
    graphql: "#E10098",
    proto: "#4285F4",
    nix: "#7E7EFF",
    hcl: "#844FBA",
    gdscript: "#355570",
    groovy: "#4298B8",
    fortran: "#734F96",
    r: "#198CE7",
    julia: "#9558B2",
    objc: "#438EFF",
};

function getColor(lang: string): string {
    const color = langColors[lang.toLowerCase()];
    if (color) return color;
    let hash = 0;
    for (let i = 0; i < lang.length; i++) hash = lang.charCodeAt(i) + ((hash << 5) - hash);
    const h = Math.abs(hash) % 360;
    return `hsl(${h}, 50%, 55%)`;
}
</script>

<template>
    <RouterLink
        :to="`/repositories/${repo.name}`"
        class="group block rounded-xl bg-surface border border-border p-5 transition-all duration-300 hover:border-accent/30 hover:shadow-[0_0_30px_-10px_var(--color-accent-glow)]"
    >
        <div class="flex items-start justify-between mb-3">
            <div>
                <div class="font-mono text-sm font-semibold text-white group-hover:text-accent transition-colors">{{ repo.name }}</div>
                <div class="text-[10px] text-text-faint mt-0.5">
                    indexed {{ repo.indexed_at?.slice(0, 10) ?? "never" }}
                    <span v-if="repo.git_head" class="ml-2 font-mono">{{ repo.git_head }}</span>
                </div>
            </div>
            <svg class="w-4 h-4 text-text-faint opacity-0 group-hover:opacity-100 transition-opacity" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
            </svg>
        </div>

        <div class="flex gap-5 text-xs mb-4">
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
    </RouterLink>
</template>
