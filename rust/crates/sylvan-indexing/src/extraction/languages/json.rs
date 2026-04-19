//! JSON extractor.
//!
//! Tree-sitter-free, unlike the other language extractors — JSON has
//! enough structure that `serde_json` plus a regex-driven line map is
//! both simpler and faster than parsing twice (once for structure,
//! once for line offsets). Port of `sylvan.indexing.source_code.json_extractor`.
//!
//! Dispatches on basename:
//!
//! - `package.json` → name/version/scripts/dependencies/exports/engines
//! - `tsconfig.json` / `jsconfig.json` → extends + compilerOptions
//! - everything else → generic one-level-deep key walk
//!
//! Improvements over the Python: the line map is built once and shared
//! across all three paths; each path is a free function operating on
//! the parsed [`serde_json::Value`], which is test-friendlier than
//! the original module-level calls.

use std::collections::HashMap;
use std::path::Path;

use fancy_regex::Regex;
use once_cell::sync::Lazy;
use serde_json::Value;
use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol, make_symbol_id};

static KEY_PATTERN: Lazy<Regex> =
    Lazy::new(|| Regex::new(r#""([^"\\]+)"\s*:"#).expect("key regex compiles"));

/// Built-in JSON extractor.
pub struct JsonExtractor;

impl JsonExtractor {
    /// Construct a fresh instance. Stateless — cheap to build.
    pub fn new() -> Self {
        Self
    }
}

impl Default for JsonExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for JsonExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["json"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        let data: Value = match serde_json::from_str(ctx.source) {
            Ok(v) => v,
            Err(_) => return Ok(Vec::new()),
        };
        let Value::Object(root) = data else {
            return Ok(Vec::new());
        };

        let basename = basename_lowercase(ctx.filename);
        let line_map = build_line_map(ctx.source);
        let byte_length = ctx.source_bytes.len() as u32;

        let symbols = match basename.as_str() {
            "package.json" => extract_package_json(&root, ctx.filename, byte_length, &line_map),
            "tsconfig.json" | "jsconfig.json" => {
                extract_tsconfig(&root, ctx.filename, byte_length, &line_map)
            }
            _ => extract_generic(&root, ctx.filename, byte_length, &line_map),
        };

        Ok(symbols)
    }
}

fn basename_lowercase(path: &str) -> String {
    Path::new(path)
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_ascii_lowercase()
}

type LineMap = HashMap<String, Vec<u32>>;

fn build_line_map(content: &str) -> LineMap {
    let mut map: LineMap = HashMap::new();
    for (idx, line) in content.lines().enumerate() {
        if let Ok(Some(m)) = KEY_PATTERN.captures(line)
            && let Some(group) = m.get(1)
        {
            map.entry(group.as_str().to_string())
                .or_default()
                .push((idx + 1) as u32);
        }
    }
    map
}

fn find_line(map: &LineMap, key: &str) -> u32 {
    map.get(key).and_then(|v| v.first().copied()).unwrap_or(1)
}

fn find_nested_line(map: &LineMap, parent: &str, child: &str) -> u32 {
    let Some(child_lines) = map.get(child) else {
        return 1;
    };
    let Some(parent_lines) = map.get(parent) else {
        return child_lines.first().copied().unwrap_or(1);
    };
    let parent_line = parent_lines.first().copied().unwrap_or(0);
    child_lines
        .iter()
        .copied()
        .find(|&l| l > parent_line)
        .unwrap_or_else(|| child_lines.first().copied().unwrap_or(1))
}

fn extract_package_json(
    data: &serde_json::Map<String, Value>,
    filename: &str,
    byte_length: u32,
    line_map: &LineMap,
) -> Vec<Symbol> {
    let mut out = Vec::new();

    for field in ["name", "version", "description", "main", "module", "types"] {
        if let Some(Value::String(value)) = data.get(field) {
            out.push(make_symbol(
                filename,
                field,
                field,
                "constant",
                &format!("\"{value}\""),
                find_line(line_map, field),
                byte_length,
            ));
        }
    }

    if let Some(Value::Object(scripts)) = data.get("scripts") {
        for (name, command) in scripts {
            let signature = match command {
                Value::String(s) => format!("{name}: {s}"),
                _ => name.clone(),
            };
            out.push(make_symbol(
                filename,
                name,
                &format!("scripts.{name}"),
                "function",
                &signature,
                find_nested_line(line_map, "scripts", name),
                byte_length,
            ));
        }
    }

    for section in [
        "dependencies",
        "devDependencies",
        "peerDependencies",
        "optionalDependencies",
    ] {
        if let Some(Value::Object(deps)) = data.get(section) {
            for (pkg, ver) in deps {
                let signature = match ver {
                    Value::String(s) => format!("{pkg}@{s}"),
                    _ => pkg.clone(),
                };
                out.push(make_symbol(
                    filename,
                    pkg,
                    &format!("{section}.{pkg}"),
                    "constant",
                    &signature,
                    find_nested_line(line_map, section, pkg),
                    byte_length,
                ));
            }
        }
    }

    if let Some(Value::Object(exports)) = data.get("exports") {
        for (entry, target) in exports {
            let signature = format!("{entry}: {}", value_signature(target));
            out.push(make_symbol(
                filename,
                entry,
                &format!("exports.{entry}"),
                "constant",
                &signature,
                find_nested_line(line_map, "exports", entry),
                byte_length,
            ));
        }
    }

    if let Some(Value::Object(engines)) = data.get("engines") {
        for (engine, constraint) in engines {
            let signature = match constraint {
                Value::String(s) => format!("{engine}: {s}"),
                _ => engine.clone(),
            };
            out.push(make_symbol(
                filename,
                engine,
                &format!("engines.{engine}"),
                "type",
                &signature,
                find_nested_line(line_map, "engines", engine),
                byte_length,
            ));
        }
    }

    out
}

fn extract_tsconfig(
    data: &serde_json::Map<String, Value>,
    filename: &str,
    byte_length: u32,
    line_map: &LineMap,
) -> Vec<Symbol> {
    let mut out = Vec::new();

    if let Some(Value::String(extends)) = data.get("extends") {
        out.push(make_symbol(
            filename,
            "extends",
            "extends",
            "constant",
            &format!("extends: \"{extends}\""),
            find_line(line_map, "extends"),
            byte_length,
        ));
    }

    if let Some(Value::Object(compiler_opts)) = data.get("compilerOptions") {
        for (key, value) in compiler_opts {
            if key == "paths"
                && let Value::Object(paths) = value
            {
                for (alias, targets) in paths {
                    let signature = match targets {
                        Value::Array(items) => format!(
                            "{alias} -> {}",
                            serde_json::to_string(items).unwrap_or_default()
                        ),
                        _ => alias.clone(),
                    };
                    out.push(make_symbol(
                        filename,
                        alias,
                        &format!("compilerOptions.paths.{alias}"),
                        "constant",
                        &signature,
                        find_nested_line(line_map, "paths", alias),
                        byte_length,
                    ));
                }
                continue;
            }
            let signature = match value {
                Value::String(s) => format!("{key}: {s}"),
                _ => format!(
                    "{key}: {}",
                    serde_json::to_string(value).unwrap_or_default()
                ),
            };
            out.push(make_symbol(
                filename,
                key,
                &format!("compilerOptions.{key}"),
                "constant",
                &signature,
                find_nested_line(line_map, "compilerOptions", key),
                byte_length,
            ));
        }
    }

    for section in ["include", "exclude", "files"] {
        if let Some(Value::Array(items)) = data.get(section) {
            let signature = format!(
                "{section}: {}",
                serde_json::to_string(items).unwrap_or_default()
            );
            out.push(make_symbol(
                filename,
                section,
                section,
                "constant",
                &signature,
                find_line(line_map, section),
                byte_length,
            ));
        }
    }

    out
}

fn extract_generic(
    data: &serde_json::Map<String, Value>,
    filename: &str,
    byte_length: u32,
    line_map: &LineMap,
) -> Vec<Symbol> {
    let mut out = Vec::new();
    for (key, value) in data {
        if let Value::Object(nested) = value {
            for (sub_key, sub_value) in nested {
                let signature = format!("{key}.{sub_key}: {}", value_signature(sub_value));
                out.push(make_symbol(
                    filename,
                    sub_key,
                    &format!("{key}.{sub_key}"),
                    "constant",
                    &signature,
                    find_nested_line(line_map, key, sub_key),
                    byte_length,
                ));
            }
        } else {
            let signature = format!("{key}: {}", value_signature(value));
            out.push(make_symbol(
                filename,
                key,
                key,
                "constant",
                &signature,
                find_line(line_map, key),
                byte_length,
            ));
        }
    }
    out
}

fn value_signature(value: &Value) -> String {
    match value {
        Value::String(s) => {
            if s.chars().count() > 60 {
                let truncated: String = s.chars().take(57).collect();
                format!("\"{truncated}...\"")
            } else {
                format!("\"{s}\"")
            }
        }
        Value::Bool(b) => b.to_string(),
        Value::Number(n) => n.to_string(),
        Value::Array(items) => format!("[{} items]", items.len()),
        Value::Object(obj) => format!("{{{} keys}}", obj.len()),
        Value::Null => "null".to_string(),
    }
}

#[allow(clippy::too_many_arguments)]
fn make_symbol(
    filename: &str,
    name: &str,
    qualified_name: &str,
    kind: &str,
    signature: &str,
    line: u32,
    byte_length: u32,
) -> Symbol {
    Symbol {
        symbol_id: make_symbol_id(filename, qualified_name, kind),
        name: name.to_string(),
        qualified_name: qualified_name.to_string(),
        kind: kind.to_string(),
        language: "json".to_string(),
        signature: Some(signature.to_string()),
        docstring: None,
        summary: Some(signature.to_string()),
        decorators: Vec::new(),
        keywords: vec![name.to_string()],
        parent_symbol_id: None,
        line_start: Some(line),
        line_end: Some(line),
        byte_offset: 0,
        byte_length,
        content_hash: None,
        cyclomatic: 0,
        max_nesting: 0,
        param_count: 0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(content: &str, filename: &str) -> Vec<Symbol> {
        let ctx = ExtractionContext::new(content, filename, "json");
        JsonExtractor::new().extract(&ctx).unwrap()
    }

    #[test]
    fn invalid_json_returns_empty() {
        assert!(extract("{not json", "a.json").is_empty());
    }

    #[test]
    fn non_object_top_level_returns_empty() {
        assert!(extract("[1, 2, 3]", "a.json").is_empty());
    }

    #[test]
    fn package_json_extracts_name_and_version() {
        let src = r#"{"name": "pkg", "version": "1.0.0"}"#;
        let syms = extract(src, "package.json");
        let names: Vec<&str> = syms.iter().map(|s| s.name.as_str()).collect();
        assert!(names.contains(&"name"));
        assert!(names.contains(&"version"));
    }

    #[test]
    fn package_json_scripts_become_functions() {
        let src = r#"{"scripts": {"build": "tsc", "test": "vitest"}}"#;
        let syms = extract(src, "package.json");
        let scripts: Vec<&Symbol> = syms.iter().filter(|s| s.kind == "function").collect();
        assert_eq!(scripts.len(), 2);
        assert!(scripts.iter().any(|s| s.qualified_name == "scripts.build"));
    }

    #[test]
    fn package_json_deps_across_sections() {
        let src = r#"{
            "dependencies": {"react": "19.0.0"},
            "devDependencies": {"vitest": "1.0.0"},
            "peerDependencies": {"typescript": "5.0.0"}
        }"#;
        let syms = extract(src, "package.json");
        let qnames: Vec<&str> = syms.iter().map(|s| s.qualified_name.as_str()).collect();
        assert!(qnames.contains(&"dependencies.react"));
        assert!(qnames.contains(&"devDependencies.vitest"));
        assert!(qnames.contains(&"peerDependencies.typescript"));
    }

    #[test]
    fn package_json_engines_are_type_symbols() {
        let src = r#"{"engines": {"node": ">=20"}}"#;
        let syms = extract(src, "package.json");
        let engine = syms.iter().find(|s| s.name == "node").unwrap();
        assert_eq!(engine.kind, "type");
        assert!(engine.signature.as_deref().unwrap().contains(">=20"));
    }

    #[test]
    fn tsconfig_extends_and_compiler_options() {
        let src = r#"{
            "extends": "@tsconfig/base/tsconfig.json",
            "compilerOptions": {
                "target": "ES2022",
                "paths": {"@/*": ["src/*"]}
            }
        }"#;
        let syms = extract(src, "tsconfig.json");
        let qnames: Vec<&str> = syms.iter().map(|s| s.qualified_name.as_str()).collect();
        assert!(qnames.contains(&"extends"));
        assert!(qnames.contains(&"compilerOptions.target"));
        assert!(qnames.contains(&"compilerOptions.paths.@/*"));
    }

    #[test]
    fn tsconfig_include_exclude_files() {
        let src = r#"{
            "include": ["src/**/*"],
            "exclude": ["node_modules"],
            "files": ["main.ts"]
        }"#;
        let syms = extract(src, "tsconfig.json");
        let names: Vec<&str> = syms.iter().map(|s| s.name.as_str()).collect();
        assert!(names.contains(&"include"));
        assert!(names.contains(&"exclude"));
        assert!(names.contains(&"files"));
    }

    #[test]
    fn generic_json_walks_one_level_deep() {
        let src = r#"{"top": "value", "nested": {"inner": 42, "flag": true}}"#;
        let syms = extract(src, "random.json");
        let qnames: Vec<&str> = syms.iter().map(|s| s.qualified_name.as_str()).collect();
        assert!(qnames.contains(&"top"));
        assert!(qnames.contains(&"nested.inner"));
        assert!(qnames.contains(&"nested.flag"));
    }

    #[test]
    fn value_signature_truncates_long_strings() {
        let long = "x".repeat(100);
        let src = format!(r#"{{"big": "{long}"}}"#);
        let syms = extract(&src, "random.json");
        assert!(
            syms[0].signature.as_deref().unwrap().contains("..."),
            "expected truncation, got {:?}",
            syms[0].signature
        );
    }

    #[test]
    fn line_map_tracks_key_positions() {
        let src = "{\n  \"a\": 1,\n  \"b\": 2\n}";
        let syms = extract(src, "x.json");
        let a = syms.iter().find(|s| s.name == "a").unwrap();
        let b = syms.iter().find(|s| s.name == "b").unwrap();
        assert_eq!(a.line_start, Some(2));
        assert_eq!(b.line_start, Some(3));
    }

    #[test]
    fn nested_line_lookup_scopes_to_parent() {
        // `version` appears both at top level and inside `engines`; the
        // engines.version line should be the nested one.
        let src = "{\n  \"version\": \"1.0\",\n  \"engines\": {\n    \"version\": \">=1\"\n  }\n}";
        let syms = extract(src, "package.json");
        let top = syms.iter().find(|s| s.qualified_name == "version").unwrap();
        let nested = syms
            .iter()
            .find(|s| s.qualified_name == "engines.version")
            .unwrap();
        assert_eq!(top.line_start, Some(2));
        assert_eq!(nested.line_start, Some(4));
    }

    #[test]
    fn extractor_registers_json_language() {
        assert_eq!(JsonExtractor::new().languages(), &["json"]);
    }
}
