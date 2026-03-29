<script setup lang="ts">
import type { EfficiencyStats } from "@/interfaces";
import { computed } from "vue";

const props = defineProps<{
    efficiency: EfficiencyStats;
    label?: string;
    toolCalls?: number;
}>();

const avoided = computed(() => props.efficiency.total_equivalent - props.efficiency.total_returned);
const dashArray = computed(() => `${props.efficiency.reduction_percent * 3.27} 327`);

const categories = computed(() => {
    const cats = props.efficiency.by_category;
    if (!cats) return [];
    const total = props.efficiency.total_equivalent || 1;
    const items: { key: string; label: string; color: string; pct: number }[] = [];
    const defs: [string, string, string][] = [
        ["search", "search", "var(--color-info)"],
        ["retrieval", "retrieval", "var(--color-accent)"],
        ["analysis", "analysis", "var(--color-purple)"],
    ];
    for (const [key, label, color] of defs) {
        const cat = cats[key];
        if (cat && cat.equivalent > 0) {
            items.push({ key, label, color, pct: Math.round((cat.equivalent / total) * 100) });
        }
    }
    return items;
});
</script>

<template>
    <div class="glass rounded-xl p-6">
        <div class="flex items-center gap-8">
            <div class="relative w-[180px] h-[180px] flex-shrink-0">
                <svg viewBox="0 0 120 120" class="w-full h-full -rotate-90">
                    <circle cx="60" cy="60" r="52" fill="none" stroke="var(--color-surface-3)" stroke-width="7" />
                    <circle
                        cx="60" cy="60" r="52" fill="none"
                        stroke="var(--color-accent)" stroke-width="7"
                        stroke-linecap="round"
                        class="ring-animate"
                        :stroke-dasharray="dashArray"
                    />
                </svg>
                <div class="absolute inset-0 flex flex-col items-center justify-center">
                    <span class="font-mono text-4xl font-bold text-white leading-none">{{ efficiency.reduction_percent }}</span>
                    <span class="text-[10px] text-text-faint mt-1">%</span>
                </div>
            </div>
            <div class="flex-1 space-y-3">
                <div v-if="label" class="text-[10px] text-text-faint uppercase tracking-[0.2em] font-semibold">{{ label }}</div>
                <div class="flex justify-between items-baseline">
                    <span class="text-sm text-text-dim">Returned</span>
                    <span class="font-mono text-sm text-accent font-semibold">{{ efficiency.total_returned.toLocaleString() }}</span>
                </div>
                <div class="flex justify-between items-baseline">
                    <span class="text-sm text-text-dim">Equivalent</span>
                    <span class="font-mono text-sm text-white font-semibold">{{ efficiency.total_equivalent.toLocaleString() }}</span>
                </div>
                <div class="flex justify-between items-baseline">
                    <span class="text-sm text-text-dim">Avoided</span>
                    <span class="font-mono text-sm text-accent font-semibold">{{ avoided.toLocaleString() }}</span>
                </div>
                <div v-if="toolCalls !== undefined" class="flex justify-between items-baseline">
                    <span class="text-sm text-text-dim">Tool calls</span>
                    <span class="font-mono text-sm text-white font-semibold">{{ toolCalls }}</span>
                </div>
                <div v-if="categories.length" class="pt-1">
                    <div class="stacked-bar">
                        <div v-for="cat in categories" :key="cat.key" :style="{ width: cat.pct + '%', background: cat.color }" />
                    </div>
                    <div class="flex gap-4 mt-2">
                        <span v-for="cat in categories" :key="cat.key" class="text-[10px] font-mono text-text-faint flex items-center gap-1">
                            <span class="inline-block w-1.5 h-1.5 rounded-full" :style="{ background: cat.color }" />
                            {{ cat.label }}
                        </span>
                    </div>
                </div>
            </div>
        </div>
    </div>
</template>
