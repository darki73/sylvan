//! Blade template extractor.
//!
//! Laravel's Blade templates (`*.blade.php`) have no tree-sitter
//! grammar that covers both the directive layer and the embedded PHP.
//! Sylvan handles them the way the original Python implementation did:
//! a set of regex passes for Blade-specific directives, plus a nested
//! parse of any `@php ... @endphp` block via the PHP extractor.
//!
//! Symbol shapes match the Python output exactly so parity holds:
//!
//! - `@section`, `@yield`, `@slot`, `@push`/`@pushOnce`, `@pushIf`
//!   become `function` symbols named by the directive argument.
//! - `@props([...])` and `@aware([...])` emit one `constant` per prop
//!   entry, with qualified names `@props.{name}` / `@aware.{name}`.
//! - `@php` blocks are wrapped in `<?php ... ?>`, parsed with the PHP
//!   extractor, and their byte offsets / line numbers are shifted back
//!   onto the original Blade file so downstream consumers can jump to
//!   the right place.

use std::collections::HashSet;

use fancy_regex::Regex;
use once_cell::sync::Lazy;
use sylvan_core::{
    ExtractionContext, ExtractionError, Import, LanguageExtractor, ResolverContext, Symbol,
    make_symbol_id,
};

use super::php::PhpExtractor;

static SECTION_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r#"@section\s*\(\s*['"]([^'"]+)['"]"#).expect("blade @section regex"));
static YIELD_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r#"@yield\s*\(\s*['"]([^'"]+)['"]"#).expect("blade @yield regex"));
static SLOT_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r#"@slot\s*\(\s*['"]([^'"]+)['"]"#).expect("blade @slot regex"));
static PUSH_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"@(?:push|pushOnce)\s*\(\s*['"]([^'"]+)['"]"#).expect("blade @push regex")
});
static PUSH_IF_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"@pushIf\s*\([^,]+,\s*['"]([^'"]+)['"]"#).expect("blade @pushIf regex")
});
static PROPS_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"(?s)@props\s*\(\s*\[(.*?)\]\s*\)"#).expect("blade @props regex")
});
static AWARE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"(?s)@aware\s*\(\s*\[(.*?)\]\s*\)"#).expect("blade @aware regex")
});
static PHP_BLOCK_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?s)@php\b(.*?)@endphp").expect("blade @php regex"));
static USE_LINE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"^\s*use\s+").expect("blade use-line regex"));
static QUOTED_WORD_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r#"['"](\w+)['"]"#).expect("blade quoted-word regex"));

static EXTENDS_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r#"@extends\s*\(\s*['"]([^'"]+)['"]"#).expect("blade @extends regex"));
static INCLUDE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r#"@include\s*\(\s*['"]([^'"]+)['"]"#).expect("blade @include regex"));
static INCLUDE_IF_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"@includeIf\s*\(\s*['"]([^'"]+)['"]"#).expect("blade @includeIf regex")
});
static INCLUDE_COND_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"@include(?:When|Unless)\s*\([^,]+,\s*['"]([^'"]+)['"]"#)
        .expect("blade @includeWhen/Unless regex")
});
static INCLUDE_FIRST_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"(?s)@includeFirst\s*\(\s*\[(.*?)\]"#).expect("blade @includeFirst regex")
});
static COMPONENT_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"@component\s*\(\s*['"]([^'"]+)['"]"#).expect("blade @component regex")
});
static LIVEWIRE_DIRECTIVE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"@livewire\s*\(\s*['"]([^'"]+)['"]"#).expect("blade @livewire regex")
});
static X_COMPONENT_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"<x-([\w.:/-]+)").expect("blade x-component regex"));
static LIVEWIRE_TAG_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"<livewire:([\w.:/-]+)").expect("blade <livewire:> regex"));
static EACH_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r#"@each\s*\(\s*['"]([^'"]+)['"]"#).expect("blade @each regex"));
static BLADE_USE_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r#"@use\s*\(\s*['"]([^'"]+)['"]"#).expect("blade @use regex"));
static PHP_USE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?m)^\s*use\s+(?:function\s+|const\s+)?([\w\\]+)(?:\s+as\s+\w+)?\s*;")
        .expect("blade php use regex")
});
static QUOTED_STRING_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r#"['"]([^'"]+)['"]"#).expect("blade quoted-string regex"));

/// Built-in Blade extractor.
pub struct BladeExtractor {
    php: PhpExtractor,
}

impl BladeExtractor {
    /// Construct a fresh instance. The embedded PHP extractor is cheap;
    /// its tree-sitter language handle is materialised lazily when the
    /// first `@php` block forces a PHP parse.
    pub fn new() -> Self {
        Self {
            php: PhpExtractor::new(),
        }
    }
}

impl Default for BladeExtractor {
    fn default() -> Self {
        Self::new()
    }
}

fn line_number(source: &str, byte_pos: usize) -> u32 {
    let up_to = &source[..byte_pos.min(source.len())];
    (up_to.bytes().filter(|b| *b == b'\n').count() + 1) as u32
}

fn make_directive_symbol(
    filename: &str,
    source: &str,
    start: usize,
    end: usize,
    name: &str,
    directive: &str,
) -> Symbol {
    let qualified = format!("{directive}('{name}')");
    Symbol {
        symbol_id: make_symbol_id(filename, &qualified, "function"),
        name: name.to_string(),
        qualified_name: qualified.clone(),
        kind: "function".to_string(),
        language: "blade".to_string(),
        signature: Some(qualified),
        docstring: None,
        summary: None,
        decorators: Vec::new(),
        keywords: Vec::new(),
        parent_symbol_id: None,
        line_start: Some(line_number(source, start)),
        line_end: Some(line_number(source, start)),
        byte_offset: start as u32,
        byte_length: (end - start) as u32,
        content_hash: None,
        cyclomatic: 0,
        max_nesting: 0,
        param_count: 0,
    }
}

fn make_prop_symbol(
    filename: &str,
    source: &str,
    start: usize,
    end: usize,
    prop: &str,
    directive: &str,
) -> Symbol {
    let qualified = format!("{directive}.{prop}");
    Symbol {
        symbol_id: make_symbol_id(filename, &qualified, "constant"),
        name: prop.to_string(),
        qualified_name: qualified,
        kind: "constant".to_string(),
        language: "blade".to_string(),
        signature: Some(format!("{directive}('{prop}')")),
        docstring: None,
        summary: None,
        decorators: Vec::new(),
        keywords: Vec::new(),
        parent_symbol_id: None,
        line_start: Some(line_number(source, start)),
        line_end: Some(line_number(source, start)),
        byte_offset: start as u32,
        byte_length: (end - start) as u32,
        content_hash: None,
        cyclomatic: 0,
        max_nesting: 0,
        param_count: 0,
    }
}

fn extract_prop_names(array_body: &str) -> Vec<String> {
    let mut names = Vec::new();
    let mut depth = 0i32;
    let mut current = String::new();
    for ch in array_body.chars() {
        match ch {
            '(' | '[' | '{' => {
                depth += 1;
                current.push(ch);
            }
            ')' | ']' | '}' => {
                depth -= 1;
                current.push(ch);
            }
            ',' if depth == 0 => {
                if let Some(name) = prop_name_from_entry(&current) {
                    names.push(name);
                }
                current.clear();
            }
            _ => current.push(ch),
        }
    }
    if let Some(name) = prop_name_from_entry(&current) {
        names.push(name);
    }
    names
}

fn prop_name_from_entry(entry: &str) -> Option<String> {
    let trimmed = entry.trim();
    if trimmed.is_empty() {
        return None;
    }
    let key_part = match trimmed.split_once("=>") {
        Some((k, _)) => k,
        None => trimmed,
    };
    QUOTED_WORD_RE
        .captures(key_part)
        .ok()
        .flatten()
        .and_then(|m| m.get(1).map(|g| g.as_str().to_string()))
}

fn collect_by_directive(
    re: &Regex,
    source: &str,
    filename: &str,
    directive: &str,
    out: &mut Vec<Symbol>,
) {
    for m in re.captures_iter(source).flatten() {
        let Some(name) = m.get(1) else { continue };
        let Some(whole) = m.get(0) else { continue };
        out.push(make_directive_symbol(
            filename,
            source,
            whole.start(),
            whole.end(),
            name.as_str(),
            directive,
        ));
    }
}

impl BladeExtractor {
    fn extract_php_blocks(
        &self,
        ctx: &ExtractionContext<'_>,
        out: &mut Vec<Symbol>,
    ) -> Result<(), ExtractionError> {
        for m in PHP_BLOCK_RE.captures_iter(ctx.source).flatten() {
            let Some(block) = m.get(1) else { continue };
            let php_code = block.as_str();
            if php_code.trim().is_empty() {
                continue;
            }
            // Skip blocks that are only `use` lines (those become imports,
            // not symbols).
            let has_non_use = php_code.lines().any(|line| {
                let t = line.trim();
                !t.is_empty() && !USE_LINE_RE.is_match(line).unwrap_or(false)
            });
            if !has_non_use {
                continue;
            }

            let wrapped = format!("<?php\n{php_code}\n?>");
            let prefix_len = "<?php\n".len() as i64;
            let block_byte_offset = block.start() as i64;
            let block_start_line = line_number(ctx.source, block.start()) as i64;

            let inner_ctx = ExtractionContext::new(&wrapped, ctx.filename, "php");
            let php_symbols = match self.php.extract(&inner_ctx) {
                Ok(s) => s,
                Err(_) => continue,
            };

            for mut sym in php_symbols {
                sym.language = "blade".to_string();
                let adjusted_offset =
                    sym.byte_offset as i64 - prefix_len + block_byte_offset;
                sym.byte_offset = adjusted_offset.max(0) as u32;
                if let Some(ls) = sym.line_start {
                    let adjusted = ls as i64 - 2 + block_start_line;
                    sym.line_start = Some(adjusted.max(1) as u32);
                }
                if let Some(le) = sym.line_end {
                    let adjusted = le as i64 - 2 + block_start_line;
                    sym.line_end = Some(adjusted.max(1) as u32);
                }
                out.push(sym);
            }
        }
        Ok(())
    }
}

impl LanguageExtractor for BladeExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["blade"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        let mut out: Vec<Symbol> = Vec::new();
        let source = ctx.source;
        let filename = ctx.filename;

        collect_by_directive(&SECTION_RE, source, filename, "@section", &mut out);
        collect_by_directive(&YIELD_RE, source, filename, "@yield", &mut out);
        collect_by_directive(&SLOT_RE, source, filename, "@slot", &mut out);
        collect_by_directive(&PUSH_RE, source, filename, "@push", &mut out);
        collect_by_directive(&PUSH_IF_RE, source, filename, "@push", &mut out);

        for m in PROPS_RE.captures_iter(source).flatten() {
            let Some(body) = m.get(1) else { continue };
            let Some(whole) = m.get(0) else { continue };
            for prop in extract_prop_names(body.as_str()) {
                out.push(make_prop_symbol(
                    filename,
                    source,
                    whole.start(),
                    whole.end(),
                    &prop,
                    "@props",
                ));
            }
        }

        for m in AWARE_RE.captures_iter(source).flatten() {
            let Some(body) = m.get(1) else { continue };
            let Some(whole) = m.get(0) else { continue };
            for prop in extract_prop_names(body.as_str()) {
                out.push(make_prop_symbol(
                    filename,
                    source,
                    whole.start(),
                    whole.end(),
                    &prop,
                    "@aware",
                ));
            }
        }

        self.extract_php_blocks(ctx, &mut out)?;

        Ok(out)
    }

    fn supports_imports(&self) -> bool {
        true
    }

    fn extract_imports(
        &self,
        ctx: &ExtractionContext<'_>,
    ) -> Result<Vec<Import>, ExtractionError> {
        let source = ctx.source;
        let mut imports: Vec<Import> = Vec::new();
        let mut seen: HashSet<String> = HashSet::new();

        let add = |spec: String, imports: &mut Vec<Import>, seen: &mut HashSet<String>| {
            if spec.is_empty() || seen.contains(&spec) {
                return;
            }
            seen.insert(spec.clone());
            imports.push(Import {
                specifier: spec,
                names: Vec::new(),
            });
        };

        let capture_specifiers = |re: &Regex, src: &str| -> Vec<String> {
            let mut specs = Vec::new();
            for cap in re.captures_iter(src).flatten() {
                if let Some(m) = cap.get(1) {
                    specs.push(m.as_str().to_string());
                }
            }
            specs
        };

        for s in capture_specifiers(&EXTENDS_RE, source) {
            add(s, &mut imports, &mut seen);
        }
        for s in capture_specifiers(&INCLUDE_RE, source) {
            add(s, &mut imports, &mut seen);
        }
        for s in capture_specifiers(&INCLUDE_IF_RE, source) {
            add(s, &mut imports, &mut seen);
        }
        for s in capture_specifiers(&INCLUDE_COND_RE, source) {
            add(s, &mut imports, &mut seen);
        }
        for cap in INCLUDE_FIRST_RE.captures_iter(source).flatten() {
            if let Some(body) = cap.get(1) {
                for inner in QUOTED_STRING_RE.captures_iter(body.as_str()).flatten() {
                    if let Some(m) = inner.get(1) {
                        add(m.as_str().to_string(), &mut imports, &mut seen);
                    }
                }
            }
        }
        for s in capture_specifiers(&COMPONENT_RE, source) {
            add(s, &mut imports, &mut seen);
        }
        for s in capture_specifiers(&LIVEWIRE_DIRECTIVE_RE, source) {
            add(format!("livewire.{s}"), &mut imports, &mut seen);
        }
        for s in capture_specifiers(&X_COMPONENT_RE, source) {
            add(
                format!("components.{}", s.replace('/', ".")),
                &mut imports,
                &mut seen,
            );
        }
        for s in capture_specifiers(&LIVEWIRE_TAG_RE, source) {
            add(
                format!("livewire.{}", s.replace('/', ".")),
                &mut imports,
                &mut seen,
            );
        }
        for s in capture_specifiers(&EACH_RE, source) {
            add(s, &mut imports, &mut seen);
        }
        for s in capture_specifiers(&BLADE_USE_RE, source) {
            add(s, &mut imports, &mut seen);
        }
        for block in PHP_BLOCK_RE.captures_iter(source).flatten() {
            let Some(body) = block.get(1) else { continue };
            for use_cap in PHP_USE_RE.captures_iter(body.as_str()).flatten() {
                if let Some(m) = use_cap.get(1) {
                    add(m.as_str().to_string(), &mut imports, &mut seen);
                }
            }
        }

        Ok(imports)
    }

    fn supports_resolution(&self) -> bool {
        true
    }

    fn generate_candidates(
        &self,
        specifier: &str,
        source_path: &str,
        context: &ResolverContext,
    ) -> Vec<String> {
        // PHP namespace: delegate to PHP resolver.
        if specifier.contains('\\') {
            return self.php.generate_candidates(specifier, source_path, context);
        }

        // Namespaced view: "ns::view.name"
        if let Some((namespace, view)) = specifier.split_once("::") {
            let view_path = view.replace('.', "/");
            return vec![
                format!("resources/views/vendor/{namespace}/{view_path}.blade.php"),
                format!("vendor/{namespace}/resources/views/{view_path}.blade.php"),
            ];
        }

        // Plain dot-notation view.
        let path_base = specifier.replace('.', "/");
        let mut candidates = vec![
            format!("resources/views/{path_base}.blade.php"),
            format!("resources/views/{path_base}/index.blade.php"),
        ];
        if let Some(component) = path_base.strip_prefix("livewire/") {
            let pascal: String = component
                .split('-')
                .map(|part| {
                    let mut chars = part.chars();
                    match chars.next() {
                        Some(c) => c.to_uppercase().collect::<String>() + chars.as_str(),
                        None => String::new(),
                    }
                })
                .collect();
            candidates.push(format!("app/Livewire/{pascal}.php"));
        }
        candidates
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        BladeExtractor::new()
            .extract(&ExtractionContext::new(source, "view.blade.php", "blade"))
            .expect("blade extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_sections_and_yields() {
        let src = "@extends('layouts.app')\n@section('content')\n<div>hi</div>\n@endsection\n@yield('header')\n";
        let syms = extract(src);
        assert!(syms
            .iter()
            .any(|s| s.name == "content" && s.kind == "function"));
        assert!(syms.iter().any(|s| s.name == "header"));
    }

    #[test]
    fn extracts_props_as_constants() {
        let src = "@props(['name', 'age' => 18])\n<div>{{ $name }}</div>\n";
        let syms = extract(src);
        let names: Vec<_> = syms
            .iter()
            .filter(|s| s.kind == "constant")
            .map(|s| s.name.clone())
            .collect();
        assert!(names.contains(&"name".to_string()));
        assert!(names.contains(&"age".to_string()));
        let n = syms.iter().find(|s| s.name == "name").unwrap();
        assert_eq!(n.qualified_name, "@props.name");
    }

    #[test]
    fn extracts_aware_as_constants() {
        let src = "@aware(['theme'])\n";
        let syms = extract(src);
        let t = syms
            .iter()
            .find(|s| s.name == "theme")
            .expect("aware entry");
        assert_eq!(t.qualified_name, "@aware.theme");
    }

    #[test]
    fn extracts_push_variants() {
        let src = "@push('scripts')\n<script></script>\n@endpush\n@pushIf($cond, 'styles')\n";
        let syms = extract(src);
        assert!(syms.iter().any(|s| s.name == "scripts"));
        assert!(syms.iter().any(|s| s.name == "styles"));
    }

    #[test]
    fn extracts_php_block_symbols_as_blade_language() {
        let src =
            "@php\nfunction helper() { return 1; }\nclass Widget {}\n@endphp\n";
        let syms = extract(src);
        let helper = syms.iter().find(|s| s.name == "helper").expect("helper fn");
        assert_eq!(helper.language, "blade");
        assert_eq!(helper.kind, "function");
        assert!(syms.iter().any(|s| s.name == "Widget" && s.kind == "class"));
    }

    #[test]
    fn skips_use_only_php_blocks() {
        let src = "@php\nuse App\\Models\\User;\n@endphp\n";
        let syms = extract(src);
        assert!(syms.is_empty());
    }

    #[test]
    fn advertises_blade_language() {
        assert_eq!(BladeExtractor::new().languages(), &["blade"]);
    }

    fn imports(src: &str) -> Vec<Import> {
        BladeExtractor::new()
            .extract_imports(&ExtractionContext::new(src, "view.blade.php", "blade"))
            .expect("blade imports")
    }

    fn candidates(specifier: &str) -> Vec<String> {
        let ctx = ResolverContext::default();
        BladeExtractor::new().generate_candidates(specifier, "view.blade.php", &ctx)
    }

    #[test]
    fn extends_directive_becomes_import() {
        let imps = imports("@extends('layouts.app')\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "layouts.app");
        assert!(imps[0].names.is_empty());
    }

    #[test]
    fn include_family_extracted() {
        let src = "@include('partials.header')\n@includeIf('partials.maybe')\n@includeWhen($cond, 'partials.when')\n@includeUnless($cond, 'partials.unless')\n";
        let imps = imports(src);
        let specs: Vec<_> = imps.iter().map(|i| i.specifier.clone()).collect();
        assert!(specs.contains(&"partials.header".to_string()));
        assert!(specs.contains(&"partials.maybe".to_string()));
        assert!(specs.contains(&"partials.when".to_string()));
        assert!(specs.contains(&"partials.unless".to_string()));
    }

    #[test]
    fn include_first_unpacks_array() {
        let src = "@includeFirst(['custom.header', 'partials.header'])\n";
        let imps = imports(src);
        let specs: Vec<_> = imps.iter().map(|i| i.specifier.clone()).collect();
        assert_eq!(specs, vec!["custom.header", "partials.header"]);
    }

    #[test]
    fn component_and_each_directives() {
        let src = "@component('alerts.error')\n@each('view.name', $jobs, 'job')\n";
        let specs: Vec<_> = imports(src).into_iter().map(|i| i.specifier).collect();
        assert!(specs.contains(&"alerts.error".to_string()));
        assert!(specs.contains(&"view.name".to_string()));
    }

    #[test]
    fn livewire_directive_gets_livewire_prefix() {
        let imps = imports("@livewire('counter')\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "livewire.counter");
    }

    #[test]
    fn x_component_converts_to_dotted_specifier() {
        let imps = imports("<x-forms/input />\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "components.forms.input");
    }

    #[test]
    fn livewire_tag_converts_slash_to_dot() {
        let imps = imports("<livewire:nav/menu />\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "livewire.nav.menu");
    }

    #[test]
    fn blade_use_directive_extracted() {
        let imps = imports("@use('App\\Support\\Str')\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "App\\Support\\Str");
    }

    #[test]
    fn duplicate_specifiers_deduplicated() {
        let src = "@extends('layouts.app')\n@include('layouts.app')\n";
        let imps = imports(src);
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "layouts.app");
    }

    #[test]
    fn php_block_use_line_becomes_import() {
        let src = "@php\nuse App\\Models\\User;\n@endphp\n";
        let imps = imports(src);
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "App\\Models\\User");
    }

    #[test]
    fn php_block_use_with_function_and_alias() {
        let src = "@php\nuse function App\\Helpers\\format_date as fmt;\n@endphp\n";
        let imps = imports(src);
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "App\\Helpers\\format_date");
    }

    #[test]
    fn namespaced_view_produces_two_candidates() {
        let c = candidates("mail::message");
        assert_eq!(
            c,
            vec![
                "resources/views/vendor/mail/message.blade.php",
                "vendor/mail/resources/views/message.blade.php",
            ]
        );
    }

    #[test]
    fn plain_view_produces_two_candidates() {
        let c = candidates("layouts.app");
        assert_eq!(
            c,
            vec![
                "resources/views/layouts/app.blade.php",
                "resources/views/layouts/app/index.blade.php",
            ]
        );
    }

    #[test]
    fn livewire_view_adds_pascal_component_path() {
        let c = candidates("livewire.user-profile");
        assert_eq!(c.len(), 3);
        assert_eq!(c[0], "resources/views/livewire/user-profile.blade.php");
        assert_eq!(
            c[1],
            "resources/views/livewire/user-profile/index.blade.php"
        );
        assert_eq!(c[2], "app/Livewire/UserProfile.php");
    }

    #[test]
    fn backslash_specifier_delegates_to_php_resolver() {
        // Without PSR-4 mappings, PHP resolver falls back to naive
        // namespace-to-path candidates. Exact output comes from php.rs —
        // the assertion we care about is "did not produce blade view
        // candidates".
        let c = candidates("App\\Models\\User");
        assert!(
            !c.iter().any(|p| p.starts_with("resources/views/")),
            "expected PHP resolver delegation, got {c:?}"
        );
    }
}
