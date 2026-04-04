<script setup lang="ts">
import { ref, computed } from "vue";
import { useMemory, usePreferences, useRepoOptions } from "@/composables/useMemory";
import type { MemoryEntry, PreferenceEntry } from "@/composables/useMemory";

const tab = ref<"memories" | "preferences">("memories");

const { memories, loading: memoriesLoading, refresh: refreshMemories, deleteEntry: deleteMemory } = useMemory();
const { preferences, loading: prefsLoading, refresh: refreshPrefs, save: savePref, deleteEntry: deletePref } = usePreferences();
const { repos } = useRepoOptions();

const memoryFilter = ref("");
const filteredMemories = computed(() => {
    if (!memoryFilter.value) return memories;
    const q = memoryFilter.value.toLowerCase();
    return memories.filter(
        m => m.content.toLowerCase().includes(q) || m.repo.toLowerCase().includes(q) || m.tags.some(t => t.toLowerCase().includes(q)),
    );
});

const selectedMemory = ref<MemoryEntry | null>(null);
const selectedPref = ref<PreferenceEntry | null>(null);

const showAddPref = ref(false);
const newKey = ref("");
const newInstruction = ref("");
const newScope = ref("global");
const newScopeId = ref<number | null>(null);
const saving = ref(false);

const scopeOptions = [
    { value: "global", label: "Global" },
    { value: "workspace", label: "Workspace" },
    { value: "repo", label: "Repository" },
];

async function handleSavePref() {
    if (!newKey.value || !newInstruction.value) return;
    saving.value = true;
    try {
        await savePref(newKey.value, newInstruction.value, newScope.value, newScope.value === "global" ? null : newScopeId.value);
        newKey.value = "";
        newInstruction.value = "";
        newScope.value = "global";
        newScopeId.value = null;
        showAddPref.value = false;
    } finally {
        saving.value = false;
    }
}

async function handleDeleteMemory(repo: string, id: number) {
    await deleteMemory(repo, id);
    if (selectedMemory.value?.id === id) selectedMemory.value = null;
}

async function handleDeletePref(p: PreferenceEntry) {
    await deletePref(p.key, p.scope, p.scope_id);
    if (selectedPref.value?.id === p.id) selectedPref.value = null;
}

function formatDate(iso: string): string {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) + " " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function scopeBadgeClass(scope: string): string {
    if (scope === "global") return "bg-accent/15 text-accent";
    if (scope === "workspace") return "bg-info/15 text-info";
    return "bg-warning/15 text-warning";
}
</script>

<template>
    <div>
        <div class="mb-8 animate-in">
            <h1 class="text-2xl font-bold text-white tracking-tight">Memory</h1>
            <p class="text-sm text-text-dim mt-1">
                <span class="font-mono text-accent">{{ memories.length }}</span> memories,
                <span class="font-mono text-info">{{ preferences.length }}</span> preferences
            </p>
        </div>

        <div class="flex items-center gap-1 mb-6 animate-in delay-1">
            <button
                v-for="t in ([['memories', 'Memories'], ['preferences', 'Preferences']] as const)"
                :key="t[0]"
                class="px-4 py-1.5 text-xs font-medium rounded-lg transition-all duration-200"
                :class="tab === t[0]
                    ? 'bg-surface-2 text-white shadow-sm'
                    : 'text-text-dim hover:text-white hover:bg-surface/50'"
                @click="tab = t[0]"
            >
                {{ t[1] }}
            </button>
        </div>

        <!-- Memories Tab -->
        <div v-if="tab === 'memories'">
            <div class="mb-4 animate-in delay-2">
                <input
                    v-model="memoryFilter"
                    type="text"
                    placeholder="Filter memories..."
                    class="w-full max-w-sm px-3 py-1.5 text-xs bg-surface border border-border rounded-lg text-white placeholder-text-faint focus:outline-none focus:border-accent/50 transition-colors"
                />
            </div>

            <div v-if="memoriesLoading" class="flex items-center gap-3 text-text-dim text-sm py-20 justify-center">
                <div class="w-4 h-4 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
                Loading...
            </div>

            <div v-else-if="!filteredMemories.length" class="text-center py-20 animate-in">
                <div class="text-text-faint text-sm mb-2">No memories stored</div>
                <div class="text-text-faint text-xs">
                    Agents save memories via <span class="font-mono text-text-dim">save_memory</span>
                </div>
            </div>

            <div v-else class="space-y-3">
                <div
                    v-for="(m, i) in filteredMemories"
                    :key="m.id"
                    class="rounded-xl bg-surface border border-border p-4 transition-all duration-300 animate-in hover:border-accent/20 cursor-pointer"
                    :class="'delay-' + Math.min(i + 1, 5)"
                    @click="selectedMemory = m"
                >
                    <div class="flex items-start justify-between mb-2">
                        <div class="flex items-center gap-2">
                            <span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-warning/15 text-warning">{{ m.repo }}</span>
                            <span v-for="tag in m.tags" :key="tag" class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-surface-2 text-text-faint">{{ tag }}</span>
                        </div>
                        <div class="flex items-center gap-3">
                            <span class="text-[10px] font-mono text-text-faint">{{ formatDate(m.updated_at) }}</span>
                            <button
                                class="text-[10px] font-mono text-text-faint hover:text-danger transition-colors"
                                @click.stop="handleDeleteMemory(m.repo, m.id)"
                            >
                                delete
                            </button>
                        </div>
                    </div>
                    <div class="text-xs text-text-dim leading-relaxed line-clamp-2">{{ m.content }}</div>
                </div>
            </div>
        </div>

        <!-- Memory Detail Dialog -->
        <Teleport to="body">
            <div
                v-if="selectedMemory"
                class="fixed inset-0 z-[100] flex items-center justify-center"
                @click.self="selectedMemory = null"
            >
                <div class="absolute inset-0 bg-black/60 backdrop-blur-sm" @click="selectedMemory = null" />
                <div class="relative w-full max-w-2xl mx-4 rounded-xl bg-surface border border-border shadow-2xl animate-in">
                    <div class="flex items-start justify-between p-5 border-b border-border">
                        <div class="flex items-center gap-2 flex-wrap">
                            <span class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-warning/15 text-warning">{{ selectedMemory.repo }}</span>
                            <span v-for="tag in selectedMemory.tags" :key="tag" class="text-[10px] font-mono px-1.5 py-0.5 rounded bg-surface-2 text-text-faint">{{ tag }}</span>
                            <span class="text-[10px] font-mono text-text-faint ml-2">id: {{ selectedMemory.id }}</span>
                        </div>
                        <button
                            class="text-text-faint hover:text-white transition-colors ml-4"
                            @click="selectedMemory = null"
                        >
                            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                            </svg>
                        </button>
                    </div>
                    <div class="p-5">
                        <div class="text-sm text-text-dim leading-relaxed whitespace-pre-wrap">{{ selectedMemory.content }}</div>
                    </div>
                    <div class="flex items-center justify-between px-5 py-3 border-t border-border">
                        <div class="flex items-center gap-4 text-[10px] font-mono text-text-faint">
                            <span>created {{ formatDate(selectedMemory.created_at) }}</span>
                            <span>updated {{ formatDate(selectedMemory.updated_at) }}</span>
                        </div>
                        <button
                            class="text-[10px] font-mono text-text-faint hover:text-danger transition-colors"
                            @click="handleDeleteMemory(selectedMemory!.repo, selectedMemory!.id)"
                        >
                            delete
                        </button>
                    </div>
                </div>
            </div>
        </Teleport>

        <!-- Preference Detail Dialog -->
        <Teleport to="body">
            <div
                v-if="selectedPref"
                class="fixed inset-0 z-[100] flex items-center justify-center"
                @click.self="selectedPref = null"
            >
                <div class="absolute inset-0 bg-black/60 backdrop-blur-sm" @click="selectedPref = null" />
                <div class="relative w-full max-w-2xl mx-4 rounded-xl bg-surface border border-border shadow-2xl animate-in">
                    <div class="flex items-start justify-between p-5 border-b border-border">
                        <div class="flex items-center gap-2">
                            <span class="font-mono text-sm font-semibold text-white">{{ selectedPref.key }}</span>
                            <span
                                class="text-[10px] font-mono px-1.5 py-0.5 rounded"
                                :class="scopeBadgeClass(selectedPref.scope)"
                            >
                                {{ selectedPref.scope }}
                            </span>
                            <span v-if="selectedPref.scope_name" class="text-[10px] font-mono text-text-faint">{{ selectedPref.scope_name }}</span>
                        </div>
                        <button
                            class="text-text-faint hover:text-white transition-colors ml-4"
                            @click="selectedPref = null"
                        >
                            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                            </svg>
                        </button>
                    </div>
                    <div class="p-5">
                        <div class="text-sm text-text-dim leading-relaxed whitespace-pre-wrap">{{ selectedPref.instruction }}</div>
                    </div>
                    <div class="flex items-center justify-between px-5 py-3 border-t border-border">
                        <div class="flex items-center gap-4 text-[10px] font-mono text-text-faint">
                            <span>created {{ formatDate(selectedPref.created_at) }}</span>
                            <span>updated {{ formatDate(selectedPref.updated_at) }}</span>
                        </div>
                        <button
                            class="text-[10px] font-mono text-text-faint hover:text-danger transition-colors"
                            @click="handleDeletePref(selectedPref!)"
                        >
                            delete
                        </button>
                    </div>
                </div>
            </div>
        </Teleport>

        <!-- Preferences Tab -->
        <div v-if="tab === 'preferences'">
            <div class="mb-4 flex items-center gap-3 animate-in delay-2">
                <button
                    class="px-3 py-1.5 text-xs font-mono rounded-lg transition-all duration-200"
                    :class="showAddPref
                        ? 'bg-accent/15 text-accent'
                        : 'bg-surface border border-border text-text-dim hover:text-white hover:border-accent/30'"
                    @click="showAddPref = !showAddPref"
                >
                    + add preference
                </button>
            </div>

            <!-- Add Preference Form -->
            <div
                v-if="showAddPref"
                class="rounded-xl bg-surface border border-accent/20 p-5 mb-6 animate-in"
            >
                <div class="grid grid-cols-2 gap-4 mb-4">
                    <div>
                        <label class="text-[10px] font-mono text-text-faint mb-1 block">Key</label>
                        <input
                            v-model="newKey"
                            type="text"
                            placeholder="e.g. test_style, commit_format"
                            class="w-full px-3 py-1.5 text-xs bg-bg border border-border rounded-lg text-white placeholder-text-faint focus:outline-none focus:border-accent/50 transition-colors"
                        />
                    </div>
                    <div class="flex gap-3">
                        <div class="flex-1">
                            <label class="text-[10px] font-mono text-text-faint mb-1 block">Scope</label>
                            <select
                                v-model="newScope"
                                class="w-full px-3 py-1.5 text-xs bg-bg border border-border rounded-lg text-white focus:outline-none focus:border-accent/50 transition-colors"
                            >
                                <option v-for="s in scopeOptions" :key="s.value" :value="s.value">{{ s.label }}</option>
                            </select>
                        </div>
                        <div v-if="newScope !== 'global'" class="flex-1">
                            <label class="text-[10px] font-mono text-text-faint mb-1 block">Target</label>
                            <select
                                v-model="newScopeId"
                                class="w-full px-3 py-1.5 text-xs bg-bg border border-border rounded-lg text-white focus:outline-none focus:border-accent/50 transition-colors"
                            >
                                <option :value="null" disabled>Select...</option>
                                <option v-for="r in repos" :key="r.id" :value="r.id">{{ r.name }}</option>
                            </select>
                        </div>
                    </div>
                </div>
                <div class="mb-4">
                    <label class="text-[10px] font-mono text-text-faint mb-1 block">Instruction</label>
                    <textarea
                        v-model="newInstruction"
                        rows="3"
                        placeholder="Actionable instruction for the agent..."
                        class="w-full px-3 py-2 text-xs bg-bg border border-border rounded-lg text-white placeholder-text-faint focus:outline-none focus:border-accent/50 transition-colors resize-none"
                    />
                </div>
                <div class="flex items-center gap-3">
                    <button
                        class="px-4 py-1.5 text-xs font-mono rounded-lg bg-accent/15 text-accent hover:bg-accent/25 transition-colors disabled:opacity-50"
                        :disabled="!newKey || !newInstruction || saving"
                        @click="handleSavePref"
                    >
                        {{ saving ? "saving..." : "save" }}
                    </button>
                    <button
                        class="px-4 py-1.5 text-xs font-mono rounded-lg text-text-faint hover:text-white transition-colors"
                        @click="showAddPref = false"
                    >
                        cancel
                    </button>
                </div>
            </div>

            <div v-if="prefsLoading" class="flex items-center gap-3 text-text-dim text-sm py-20 justify-center">
                <div class="w-4 h-4 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
                Loading...
            </div>

            <div v-else-if="!preferences.length" class="text-center py-20 animate-in">
                <div class="text-text-faint text-sm mb-2">No preferences configured</div>
                <div class="text-text-faint text-xs">
                    Agents save preferences via <span class="font-mono text-text-dim">save_preference</span> or use the form above
                </div>
            </div>

            <div v-else>
                <table class="w-full text-xs animate-in delay-2">
                    <thead>
                        <tr class="text-text-faint border-b border-border">
                            <th class="text-left font-normal px-4 py-2">Key</th>
                            <th class="text-left font-normal px-4 py-2">Instruction</th>
                            <th class="text-left font-normal px-4 py-2">Scope</th>
                            <th class="text-right font-normal px-4 py-2">Updated</th>
                            <th class="w-16" />
                        </tr>
                    </thead>
                    <tbody>
                        <tr
                            v-for="p in preferences"
                            :key="p.id"
                            class="border-b border-border/50 hover:bg-surface/50 transition-colors group cursor-pointer"
                            @click="selectedPref = p"
                        >
                            <td class="px-4 py-3 font-mono text-white whitespace-nowrap">{{ p.key }}</td>
                            <td class="px-4 py-3 text-text-dim max-w-md">
                                <div class="truncate">{{ p.instruction }}</div>
                            </td>
                            <td class="px-4 py-3 whitespace-nowrap">
                                <span
                                    class="text-[10px] font-mono px-1.5 py-0.5 rounded"
                                    :class="scopeBadgeClass(p.scope)"
                                >
                                    {{ p.scope }}
                                </span>
                                <span v-if="p.scope_name" class="text-[10px] font-mono text-text-faint ml-1">{{ p.scope_name }}</span>
                            </td>
                            <td class="px-4 py-3 text-right font-mono text-text-faint whitespace-nowrap">{{ formatDate(p.updated_at) }}</td>
                            <td class="px-4 py-3 text-right">
                                <button
                                    class="text-[10px] font-mono text-text-faint hover:text-danger transition-colors opacity-0 group-hover:opacity-100"
                                    @click.stop="handleDeletePref(p)"
                                >
                                    delete
                                </button>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</template>
