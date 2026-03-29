<script setup lang="ts">
import type { ClusterNode } from "@/interfaces";

defineProps<{
    nodes: ClusterNode[];
}>();

const active = (nodes: ClusterNode[]) => nodes.filter((n) => n.alive);
const dead = (nodes: ClusterNode[]) => nodes.filter((n) => !n.alive);
</script>

<template>
    <div>
        <h2 class="text-sm font-semibold text-text-dim uppercase tracking-wider mb-3">
            Cluster Instances ({{ active(nodes).length }} active)
        </h2>
        <div class="rounded-lg border border-border overflow-hidden">
            <table class="w-full text-sm">
                <thead class="bg-surface-2">
                    <tr class="text-left text-xs text-text-faint uppercase tracking-wider">
                        <th class="px-4 py-2">Session</th>
                        <th class="px-4 py-2">Role</th>
                        <th class="px-4 py-2">Status</th>
                        <th class="px-4 py-2 text-right">Calls</th>
                        <th class="px-4 py-2 text-right">Efficiency</th>
                        <th class="px-4 py-2 text-right">Heartbeat</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="node in active(nodes)" :key="node.session_id" class="border-t border-border">
                        <td class="px-4 py-2 font-mono text-xs text-white">{{ node.session_id }}</td>
                        <td class="px-4 py-2">
                            <span
                                class="px-2 py-0.5 text-xs rounded"
                                :class="node.role === 'leader' ? 'bg-accent text-bg' : 'bg-info text-bg'"
                            >
                                {{ node.role }}
                            </span>
                        </td>
                        <td class="px-4 py-2">
                            <span class="px-2 py-0.5 text-xs rounded bg-accent text-bg">active</span>
                        </td>
                        <td class="px-4 py-2 font-mono text-xs text-right">{{ node.tool_calls }}</td>
                        <td class="px-4 py-2 font-mono text-xs text-right text-accent">{{ node.reduction_percent }}%</td>
                        <td class="px-4 py-2 font-mono text-xs text-right text-text-faint">
                            {{ node.last_heartbeat?.slice(0, 19) ?? "--" }}
                        </td>
                    </tr>
                    <tr v-for="node in dead(nodes)" :key="node.session_id" class="border-t border-border opacity-50">
                        <td class="px-4 py-2 font-mono text-xs text-text-dim">{{ node.session_id }}</td>
                        <td class="px-4 py-2">
                            <span class="px-2 py-0.5 text-xs rounded bg-surface-3 text-text-dim">{{ node.role }}</span>
                        </td>
                        <td class="px-4 py-2">
                            <span class="px-2 py-0.5 text-xs rounded bg-danger text-bg">dead</span>
                        </td>
                        <td class="px-4 py-2 font-mono text-xs text-right text-text-dim">{{ node.tool_calls }}</td>
                        <td class="px-4 py-2 font-mono text-xs text-right text-text-dim">{{ node.reduction_percent }}%</td>
                        <td class="px-4 py-2 font-mono text-xs text-right text-text-faint">
                            {{ node.last_heartbeat?.slice(0, 19) ?? "--" }}
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>
</template>
