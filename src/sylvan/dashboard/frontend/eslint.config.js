import js from "@eslint/js";
import tseslint from "typescript-eslint";
import pluginVue from "eslint-plugin-vue";

export default tseslint.config(
    js.configs.recommended,
    ...tseslint.configs.recommended,
    ...pluginVue.configs["flat/recommended"],
    {
        files: ["**/*.vue"],
        languageOptions: {
            parserOptions: {
                parser: tseslint.parser,
            },
        },
    },
    {
        rules: {
            indent: ["warn", 4],
            "vue/html-indent": ["warn", 4],
            "vue/script-indent": ["warn", 4, { baseIndent: 0 }],
            "vue/multi-word-component-names": "off",
            "vue/max-attributes-per-line": "off",
            "vue/singleline-html-element-content-newline": "off",
        },
    },
    {
        ignores: ["dist/", "node_modules/", "*.d.ts"],
    },
);
