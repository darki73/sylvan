<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
    data: Record<string, number>;
    weeks?: number;
    label?: string;
}>();

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const numWeeks = computed(() => props.weeks ?? 52);

const cells = computed(() => {
    const today = new Date();
    const result: Array<{ date: string; count: number; day: number; week: number }> = [];

    const totalDays = numWeeks.value * 7;
    const startDate = new Date(today);
    startDate.setDate(startDate.getDate() - totalDays + 1);

    const startDay = startDate.getDay();
    const offset = startDay === 0 ? 6 : startDay - 1;
    startDate.setDate(startDate.getDate() - offset);

    const d = new Date(startDate);
    let week = 0;
    let day = 0;

    while (d <= today) {
        const key = d.toISOString().slice(0, 10);
        result.push({ date: key, count: props.data[key] ?? 0, day, week });
        day++;
        if (day >= 7) { day = 0; week++; }
        d.setDate(d.getDate() + 1);
    }
    return result;
});

const cellMap = computed(() => {
    const map: Record<string, { date: string; count: number }> = {};
    for (const c of cells.value) map[`${c.week}:${c.day}`] = c;
    return map;
});

const maxCount = computed(() => Math.max(...cells.value.map(c => c.count), 1));
const totalWeeks = computed(() => {
    const last = cells.value[cells.value.length - 1];
    return last ? last.week + 1 : 0;
});

const months = computed(() => {
    const result: Array<{ label: string; col: number }> = [];
    let lastMonth = -1;
    for (const cell of cells.value) {
        const d = new Date(cell.date);
        const m = d.getMonth();
        if (m !== lastMonth && cell.day === 0) {
            result.push({ label: d.toLocaleString("en", { month: "short" }), col: cell.week });
            lastMonth = m;
        }
    }
    return result;
});

function getCell(week: number, day: number) {
    return cellMap.value[`${week}:${day}`];
}

function intensity(count: number): string {
    if (count === 0) return "var(--color-surface-2)";
    const ratio = count / maxCount.value;
    if (ratio < 0.25) return "#0e4429";
    if (ratio < 0.5) return "#006d32";
    if (ratio < 0.75) return "#26a641";
    return "#39d353";
}

function monthCol(col: number): string {
    return `${col + 2}`;
}
</script>

<template>
    <div>
        <div
            class="grid gap-[3px]"
            :style="{
                gridTemplateColumns: `28px repeat(${totalWeeks}, 1fr)`,
                gridTemplateRows: `16px repeat(7, 16px)`,
            }"
        >
            <!-- Month labels row -->
            <div></div>
            <div
                v-for="m in months"
                :key="m.label + m.col"
                class="text-[10px] text-text-faint font-mono"
                :style="{ gridColumn: monthCol(m.col), gridRow: '1' }"
            >
                {{ m.label }}
            </div>

            <!-- Day labels + cells -->
            <template v-for="d in 7" :key="d">
                <div
                    class="text-[10px] text-text-faint font-mono text-right pr-1 flex items-center justify-end"
                    :style="{ gridColumn: '1', gridRow: `${d + 1}` }"
                >
                    {{ DAYS[d - 1] }}
                </div>
                <template v-for="w in totalWeeks" :key="w">
                    <div
                        v-if="getCell(w - 1, d - 1)"
                        class="rounded-sm group/cell relative"
                        :style="{
                            background: intensity(getCell(w - 1, d - 1)!.count),
                            gridColumn: `${w + 1}`,
                            gridRow: `${d + 1}`,
                        }"
                    >
                        <div class="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 px-2 py-1 rounded bg-bg border border-border text-[10px] font-mono text-white whitespace-nowrap opacity-0 group-hover/cell:opacity-100 pointer-events-none z-10 transition-opacity duration-75">
                            {{ getCell(w - 1, d - 1)!.count }} calls - {{ getCell(w - 1, d - 1)!.date }}
                        </div>
                    </div>
                </template>
            </template>
        </div>

        <!-- Legend -->
        <div class="flex items-center gap-1.5 mt-2">
            <span v-if="label" class="text-[10px] text-text-faint mr-auto">{{ label }}</span>
            <span class="text-[10px] text-text-faint">Less</span>
            <div class="w-[10px] h-[10px] rounded-sm" style="background: var(--color-surface-2)" />
            <div class="w-[10px] h-[10px] rounded-sm" style="background: #0e4429" />
            <div class="w-[10px] h-[10px] rounded-sm" style="background: #006d32" />
            <div class="w-[10px] h-[10px] rounded-sm" style="background: #26a641" />
            <div class="w-[10px] h-[10px] rounded-sm" style="background: #39d353" />
            <span class="text-[10px] text-text-faint">More</span>
        </div>
    </div>
</template>
