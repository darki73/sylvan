<script setup lang="ts">
import { reactive } from "vue";

interface TreeEntry {
    name: string;
    type: "dir" | "file";
    language?: string;
    size?: number;
    file_count?: number;
    children?: TreeEntry[];
}

const props = defineProps<{
    entries: TreeEntry[];
    depth?: number;
    parentPath?: string;
    selectedFile?: string;
    getColor: (lang: string) => string;
}>();

const emit = defineEmits<{
    select: [path: string];
}>();

const expanded = reactive<Record<string, boolean>>({});

function toggle(path: string) {
    expanded[path] = !expanded[path];
}

function nodePath(name: string): string {
    return props.parentPath ? `${props.parentPath}/${name}` : name;
}

function selectFile(name: string) {
    emit("select", nodePath(name));
}
</script>

<template>
    <template v-for="entry in entries" :key="entry.name">
        <div v-if="entry.type === 'dir'">
            <div
                class="flex items-center gap-1.5 py-1 px-2 rounded cursor-pointer hover:bg-surface-2/50 transition-colors"
                @click="toggle(nodePath(entry.name))"
            >
                <svg
                    class="w-3 h-3 text-text-faint transition-transform duration-150 shrink-0"
                    :class="{ 'rotate-90': expanded[nodePath(entry.name)] }"
                    fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"
                >
                    <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
                </svg>
                <span class="text-white text-xs">{{ entry.name }}</span>
                <span class="text-text-faint text-[10px] ml-auto">{{ entry.file_count }}</span>
            </div>
            <div v-if="expanded[nodePath(entry.name)]" class="ml-3">
                <FileTreeNode
                    :entries="entry.children ?? []"
                    :depth="(depth ?? 0) + 1"
                    :parent-path="nodePath(entry.name)"
                    :selected-file="selectedFile"
                    :get-color="getColor"
                    @select="$emit('select', $event)"
                />
            </div>
        </div>
        <div
            v-else
            class="flex items-center gap-2 py-1 px-2 rounded cursor-pointer transition-colors text-xs"
            :class="selectedFile === nodePath(entry.name) ? 'bg-accent/10 text-accent' : 'text-text-dim hover:bg-surface-2/50'"
            @click="selectFile(entry.name)"
        >
            <span
                v-if="entry.language"
                class="w-1.5 h-1.5 rounded-full shrink-0"
                :style="{ background: getColor(entry.language) }"
            />
            <span class="truncate">{{ entry.name }}</span>
        </div>
    </template>
</template>
