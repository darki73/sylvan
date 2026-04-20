//! Vue SFC extractor.
//!
//! A Vue single-file component wraps a `<script>` block (optionally
//! `<script setup>`) among `<template>` and `<style>` sections. Symbol
//! extraction only cares about the script block: we locate it with a
//! regex, decide whether it is TypeScript or JavaScript from the `lang`
//! attribute, delegate to the matching extractor, then shift byte
//! offsets back into the original Vue file.
//!
//! Using a regex rather than the `tree-sitter-vue` grammar keeps the
//! code small and identical in spirit to the Python implementation. The
//! returned symbols still carry the appropriate language identifier
//! (`typescript` / `tsx` / `javascript`) so downstream consumers see
//! the effective language of each symbol.

use fancy_regex::Regex;
use once_cell::sync::Lazy;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use super::javascript::JavaScriptExtractor;
use super::typescript::TypeScriptExtractor;

static SCRIPT_BLOCK: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"(?is)<script\b([^>]*)>(.*?)</script>"#).expect("vue script regex compiles")
});

static LANG_ATTR: Lazy<Regex> =
    Lazy::new(|| Regex::new(r#"(?i)\blang\s*=\s*"([^"]+)""#).expect("vue lang regex compiles"));

/// Built-in Vue extractor.
pub struct VueExtractor {
    ts: TypeScriptExtractor,
    js: JavaScriptExtractor,
}

impl VueExtractor {
    /// Construct a fresh instance. The inner TS/JS extractors are
    /// lightweight and lazily materialise their tree-sitter handles.
    pub fn new() -> Self {
        Self {
            ts: TypeScriptExtractor::new(),
            js: JavaScriptExtractor::new(),
        }
    }
}

impl Default for VueExtractor {
    fn default() -> Self {
        Self::new()
    }
}

fn pick_language(attrs: &str) -> &'static str {
    let Ok(Some(m)) = LANG_ATTR.captures(attrs) else {
        return "javascript";
    };
    let Some(val) = m.get(1) else {
        return "javascript";
    };
    match val.as_str().to_ascii_lowercase().as_str() {
        "ts" | "typescript" => "typescript",
        "tsx" => "tsx",
        _ => "javascript",
    }
}

impl LanguageExtractor for VueExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["vue"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        let Ok(Some(m)) = SCRIPT_BLOCK.captures(ctx.source) else {
            return Ok(Vec::new());
        };
        let attrs = m.get(1).map(|g| g.as_str()).unwrap_or("");
        let Some(body) = m.get(2) else {
            return Ok(Vec::new());
        };

        let inner_lang = pick_language(attrs);
        let script_source = body.as_str();
        let byte_offset = body.start() as u32;

        let inner_ctx = ExtractionContext::new(script_source, ctx.filename, inner_lang);
        let mut symbols = match inner_lang {
            "typescript" | "tsx" => self.ts.extract(&inner_ctx)?,
            _ => self.js.extract(&inner_ctx)?,
        };

        if byte_offset > 0 {
            for sym in &mut symbols {
                sym.byte_offset = sym.byte_offset.saturating_add(byte_offset);
            }
        }

        Ok(symbols)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        VueExtractor::new()
            .extract(&ExtractionContext::new(source, "App.vue", "vue"))
            .expect("vue extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_typescript_symbols_from_script_setup() {
        let src = "<template><div>{{ x }}</div></template>\n\
                   <script setup lang=\"ts\">\n\
                   function greet(name: string): string {\n  return name;\n}\n\
                   </script>\n";
        let syms = extract(src);
        assert!(syms
            .iter()
            .any(|s| s.name == "greet" && s.kind == "function"));
    }

    #[test]
    fn defaults_to_javascript_without_lang_attr() {
        let src = "<template><div /></template>\n\
                   <script>\n\
                   export function greet() { return 1; }\n\
                   </script>\n";
        let syms = extract(src);
        assert!(syms.iter().any(|s| s.name == "greet"));
    }

    #[test]
    fn no_script_block_yields_no_symbols() {
        assert!(extract("<template><div /></template>\n").is_empty());
    }

    #[test]
    fn byte_offsets_point_into_the_original_file() {
        let src = "<template>\n<div />\n</template>\n<script lang=\"ts\">\nfunction z() {}\n</script>\n";
        let syms = extract(src);
        let z = syms.iter().find(|s| s.name == "z").expect("found z");
        let script_start = src.find("function z()").expect("needle present");
        assert_eq!(z.byte_offset as usize, script_start);
    }

    #[test]
    fn advertises_vue_language() {
        assert_eq!(VueExtractor::new().languages(), &["vue"]);
    }
}
