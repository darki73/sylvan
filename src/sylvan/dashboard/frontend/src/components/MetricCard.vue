<script setup lang="ts">
defineProps<{
    label: string;
    value: string | number;
    glow?: boolean;
    accent?: boolean;
    icon?: string;
}>();
</script>

<template>
    <div
        class="rounded-xl p-5 text-center transition-all duration-300 hover:scale-[1.02]"
        :class="glow ? 'glow-card glow-pulse bg-accent-dim border border-accent/20' : 'bg-surface border border-border hover:border-border-bright'"
    >
        <div
            class="font-mono text-3xl font-bold mb-2 tracking-tight"
            :class="{
                'text-accent': accent || glow,
                'text-white': !accent && !glow,
            }"
        >
            {{ value }}
        </div>
        <div class="text-[11px] text-text-faint uppercase tracking-widest font-medium">{{ label }}</div>
    </div>
</template>
