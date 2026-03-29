<script setup>
import { useWebSocket } from "@/composables/useWebSocket";
import DefaultLayout from "@/layouts/DefaultLayout.vue";

const { connected } = useWebSocket();
</script>

<template>
    <DefaultLayout :connected="connected">
        <RouterView />
    </DefaultLayout>
</template>
