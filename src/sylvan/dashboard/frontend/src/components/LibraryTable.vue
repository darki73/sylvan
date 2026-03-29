<script setup lang="ts">
import type { GroupedLibrary } from "@/interfaces";

defineProps<{
    libraries: GroupedLibrary[];
}>();

const managerStyles: Record<string, string> = {
    pip: "bg-info/15 text-info",
    npm: "bg-danger/15 text-danger",
    go: "bg-accent/15 text-accent",
    cargo: "bg-warning/15 text-warning",
};

function mc(manager: string): string {
    return managerStyles[manager.toLowerCase()] ?? "bg-surface-3 text-text-dim";
}
</script>

<template>
    <div class="rounded-xl border border-border overflow-hidden">
        <table class="w-full text-sm">
            <thead>
                <tr class="bg-surface-2 text-[10px] text-text-faint uppercase tracking-wider">
                    <th class="px-4 py-2 text-left font-medium">Package</th>
                    <th class="px-4 py-2 text-left font-medium">Versions</th>
                    <th class="px-4 py-2 text-right font-medium">Symbols</th>
                    <th class="px-4 py-2 text-right font-medium w-8"></th>
                </tr>
            </thead>
            <tbody>
                <tr
                    v-for="lib in libraries"
                    :key="lib.package"
                    class="border-t border-border hover:bg-surface/80 transition-colors group"
                >
                    <td class="px-4 py-2.5">
                        <div class="flex items-center gap-2">
                            <span class="px-1.5 py-0.5 rounded text-[9px] font-mono font-bold" :class="mc(lib.manager)">
                                {{ lib.manager }}
                            </span>
                            <span class="font-mono text-xs font-medium text-white">{{ lib.package }}</span>
                        </div>
                    </td>
                    <td class="px-4 py-2.5">
                        <div class="flex flex-wrap gap-1">
                            <span
                                v-for="v in lib.versions"
                                :key="v.version"
                                class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-surface-3 text-text-dim"
                            >
                                {{ v.version }}
                            </span>
                        </div>
                    </td>
                    <td class="px-4 py-2.5 text-right font-mono text-xs text-purple font-medium">
                        {{ lib.total_symbols.toLocaleString() }}
                    </td>
                    <td class="px-4 py-2.5 text-right">
                        <a
                            v-if="lib.repo_url"
                            :href="lib.repo_url"
                            target="_blank"
                            class="text-text-faint hover:text-info transition-colors text-xs opacity-0 group-hover:opacity-100"
                            @click.stop
                        >
                            &#8599;
                        </a>
                    </td>
                </tr>
            </tbody>
        </table>
    </div>
</template>
