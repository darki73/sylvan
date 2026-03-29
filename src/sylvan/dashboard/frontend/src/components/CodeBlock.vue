<script setup lang="ts">
import { computed } from "vue";
import Prism from "prismjs";
import "prismjs/components/prism-markup";
import "prismjs/components/prism-css";
import "prismjs/components/prism-clike";
import "prismjs/components/prism-javascript";
import "prismjs/components/prism-typescript";
import "prismjs/components/prism-python";
import "prismjs/components/prism-go";
import "prismjs/components/prism-rust";
import "prismjs/components/prism-java";
import "prismjs/components/prism-c";
import "prismjs/components/prism-cpp";
import "prismjs/components/prism-csharp";
import "prismjs/components/prism-markup-templating";
import "prismjs/components/prism-php";
import "prismjs/components/prism-ruby";
import "prismjs/components/prism-bash";
import "prismjs/components/prism-yaml";
import "prismjs/components/prism-json";
import "prismjs/components/prism-sql";
import "prismjs/components/prism-toml";
import "prismjs/components/prism-kotlin";
import "prismjs/components/prism-swift";
import "prismjs/components/prism-lua";

const props = defineProps<{
    source: string;
    language?: string;
    startLine?: number;
}>();

const langMap: Record<string, string> = {
    python: "python", typescript: "typescript", javascript: "javascript",
    go: "go", rust: "rust", java: "java", php: "php", ruby: "ruby",
    bash: "bash", yaml: "yaml", json: "json", css: "css",
    html: "markup", vue: "typescript", tsx: "typescript", jsx: "javascript",
    sql: "sql", toml: "toml", kotlin: "kotlin", swift: "swift",
    c: "c", cpp: "cpp", c_sharp: "csharp", lua: "lua",
    markdown: "markup",
};

const prismLang = computed(() => {
    const lang = props.language?.toLowerCase() || "";
    return langMap[lang] || "";
});

const highlightedLines = computed(() => {
    const grammar = prismLang.value ? Prism.languages[prismLang.value] : null;
    if (grammar) {
        const html = Prism.highlight(props.source, grammar, prismLang.value);
        return html.split("\n");
    }
    return props.source.split("\n").map(line =>
        line.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    );
});

const start = computed(() => props.startLine ?? 1);
const lineDigits = computed(() => String(start.value + highlightedLines.value.length).length);
</script>

<template>
    <div class="overflow-x-auto text-[13px] leading-[22px] font-mono">
        <table class="w-full border-collapse">
            <tbody>
                <tr
                    v-for="(line, i) in highlightedLines"
                    :key="i"
                    class="hover:bg-white/[0.03]"
                >
                    <td
                        class="text-text-faint/30 select-none text-right pr-4 pl-4 py-0 align-top"
                        :style="{ width: lineDigits * 8 + 24 + 'px' }"
                    >
                        {{ start + i }}
                    </td>
                    <!-- eslint-disable-next-line vue/no-v-html -->
                    <td class="py-0 pr-4 whitespace-pre" v-html="line || '&nbsp;'" />
                </tr>
            </tbody>
        </table>
    </div>
</template>

<style>
.token.comment, .token.prolog, .token.doctype, .token.cdata { color: #6a737d; font-style: italic; }
.token.keyword, .token.tag { color: #ff7b72; }
.token.string, .token.attr-value { color: #a5d6ff; }
.token.function { color: #d2a8ff; }
.token.number { color: #79c0ff; }
.token.operator { color: #ff7b72; }
.token.class-name { color: #ffa657; }
.token.punctuation { color: #8b949e; }
.token.builtin { color: #79c0ff; }
.token.decorator, .token.annotation { color: #d2a8ff; }
.token.boolean, .token.constant { color: #79c0ff; }
.token.property { color: #c9d1d9; }
.token.parameter { color: #ffa657; }
.token.attr-name { color: #79c0ff; }
.token.selector { color: #7ee787; }
</style>
