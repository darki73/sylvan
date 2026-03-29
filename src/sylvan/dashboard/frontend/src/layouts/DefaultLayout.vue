<script setup lang="ts">
import NavBar from "@/components/NavBar.vue";

defineProps<{
    connected: boolean;
}>();
</script>

<template>
    <div class="min-h-screen bg-bg">
        <NavBar :connected="connected" />
        <main class="max-w-6xl mx-auto px-6 py-8">
            <slot />
        </main>
    </div>
</template>
