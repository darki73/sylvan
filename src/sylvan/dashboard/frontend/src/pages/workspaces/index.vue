<script setup lang="ts">
import { reactive } from "vue";
import { RouterLink } from "vue-router";
import { useWorkspaces } from "@/composables/useWorkspaces";

const { workspaces, loading } = useWorkspaces();
const expanded = reactive<Record<string, boolean>>({});

function toggle(name: string) {
    expanded[name] = !expanded[name];
}
</script>

<template>
    <div>
        <div class="mb-8 animate-in">
            <h1 class="text-2xl font-bold text-white tracking-tight">Workspaces</h1>
            <p class="text-sm text-text-dim mt-1">
                <span class="font-mono text-accent">{{ workspaces.length }}</span> multi-repo workspaces
            </p>
        </div>

        <div v-if="loading" class="flex items-center gap-3 text-text-dim text-sm py-20 justify-center">
            <div class="w-4 h-4 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
            Loading...
        </div>

        <div v-else-if="!workspaces.length" class="text-center py-20 animate-in">
            <div class="text-text-faint text-sm mb-2">No workspaces configured</div>
            <div class="text-text-faint text-xs">
                Use <span class="font-mono text-text-dim">index_workspace</span> to create one
            </div>
        </div>

        <div v-else class="grid grid-cols-2 gap-4 items-start">
            <div
                v-for="(ws, i) in workspaces"
                :key="ws.name"
                class="rounded-xl bg-surface border border-border transition-all duration-300 animate-in"
                :class="[
                    expanded[ws.name] ? 'border-accent/30 shadow-[0_0_30px_-10px_var(--color-accent-glow)]' : 'hover:border-accent/30 hover:shadow-[0_0_30px_-10px_var(--color-accent-glow)]',
                    'delay-' + Math.min(i + 1, 5),
                ]"
            >
                <div
                    class="p-5 cursor-pointer select-none group"
                    @click="toggle(ws.name)"
                >
                    <div class="flex items-start justify-between mb-3">
                        <div>
                            <div class="flex items-center gap-2">
                                <svg
                                    class="w-3 h-3 text-text-faint transition-transform duration-200"
                                    :class="{ 'rotate-90': expanded[ws.name] }"
                                    fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"
                                >
                                    <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
                                </svg>
                                <span class="font-mono text-sm font-semibold text-white group-hover:text-accent transition-colors">{{ ws.name }}</span>
                            </div>
                            <div v-if="ws.description" class="text-[10px] text-text-faint mt-0.5 ml-5">{{ ws.description }}</div>
                        </div>
                        <span class="text-[10px] font-mono text-text-faint">{{ ws.repo_count }} repos</span>
                    </div>

                    <div class="flex gap-5 text-xs ml-5">
                        <div>
                            <span class="font-mono text-lg font-bold text-white">{{ ws.total_files.toLocaleString() }}</span>
                            <span class="text-text-faint ml-1">files</span>
                        </div>
                        <div>
                            <span class="font-mono text-lg font-bold text-accent">{{ ws.total_symbols.toLocaleString() }}</span>
                            <span class="text-text-faint ml-1">symbols</span>
                        </div>
                        <div>
                            <span class="font-mono text-lg font-bold text-info">{{ ws.total_sections.toLocaleString() }}</span>
                            <span class="text-text-faint ml-1">docs</span>
                        </div>
                    </div>
                </div>

                <div
                    v-if="expanded[ws.name]"
                    class="border-t border-border"
                >
                    <table class="w-full text-xs">
                        <thead>
                            <tr class="text-text-faint">
                                <th class="text-left font-normal px-5 py-2">Repository</th>
                                <th class="text-right font-normal px-3 py-2">Files</th>
                                <th class="text-right font-normal px-3 py-2">Symbols</th>
                                <th class="text-right font-normal px-5 py-2">Docs</th>
                            </tr>
                        </thead>
                        <tbody>
                            <RouterLink
                                v-for="repo in ws.repos"
                                :key="repo.name"
                                :to="`/repositories/${repo.name}`"
                                custom
                                v-slot="{ navigate }"
                            >
                                <tr
                                    class="border-t border-border/50 hover:bg-surface-2/50 transition-colors cursor-pointer group/row"
                                    @click="navigate"
                                >
                                    <td class="px-5 py-2.5 font-mono text-white group-hover/row:text-accent transition-colors">{{ repo.name }}</td>
                                    <td class="text-right px-3 py-2.5 font-mono text-text-dim">{{ repo.files.toLocaleString() }}</td>
                                    <td class="text-right px-3 py-2.5 font-mono text-accent/70">{{ repo.symbols.toLocaleString() }}</td>
                                    <td class="text-right px-5 py-2.5 font-mono text-info/70">{{ repo.sections.toLocaleString() }}</td>
                                </tr>
                            </RouterLink>
                        </tbody>
                    </table>
                    <div class="px-5 py-3 border-t border-border">
                        <RouterLink
                            :to="`/workspaces/${ws.name}`"
                            class="inline-flex items-center gap-1.5 text-xs font-mono text-text-dim hover:text-accent transition-colors"
                        >
                            Manage workspace
                            <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
                            </svg>
                        </RouterLink>
                    </div>
                </div>
            </div>
        </div>
    </div>
</template>
