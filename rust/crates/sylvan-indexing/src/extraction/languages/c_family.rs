//! C and C++ extractor.
//!
//! One file, two grammars. Mirrors `sylvan.indexing.languages.c_family`:
//! C gets function/struct/enum/typedef symbols, C++ layers on classes,
//! namespaces, and template declarations with proper containers for
//! nested symbols. Names live inside declarators rather than a direct
//! `name` field for functions and typedefs, so extraction relies on
//! [`SpecExtractor`]'s child-scan fallback.
//!
//! Import extraction is a regex pass over `#include <...>` and
//! `#include "..."` directives, preserving the header text as the
//! specifier with an empty `names` list (mirroring the legacy Python
//! plugin). Resolution filters the standard C / C++ system headers
//! out (no candidate files to match), then emits, in order: the
//! header relative to the including file, the header at the repo
//! root, and the header under `include/` and `src/`. Relative
//! components like `..` are normalized the same way
//! `posixpath.normpath` collapses them in Python.

use std::collections::HashSet;
use std::sync::OnceLock;

use fancy_regex::Regex;
use once_cell::sync::Lazy;
use sylvan_core::{
    ExtractionContext, ExtractionError, Import, LanguageExtractor, ResolverContext, Symbol,
};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, SpecExtractor,
};

const C_PARAMETER_KINDS: &[&str] = &["parameter_declaration", "variadic_parameter"];

static C_INCLUDE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"(?m)^\s*#\s*include\s+[<"]([^>"]+)[>"]"#)
        .expect("c_family #include regex compiles")
});

static C_SYSTEM_HEADERS: Lazy<HashSet<&'static str>> = Lazy::new(|| {
    [
        "stdio.h", "stdlib.h", "string.h", "math.h", "time.h", "ctype.h",
        "errno.h", "signal.h", "setjmp.h", "stdarg.h", "stddef.h", "assert.h",
        "limits.h", "float.h", "locale.h", "stdbool.h", "stdint.h", "inttypes.h",
        "complex.h", "tgmath.h", "fenv.h", "iso646.h", "wchar.h", "wctype.h",
        "iostream", "string", "vector", "map", "set", "algorithm", "memory",
        "functional", "cassert", "cstdio", "cstdlib", "cstring", "cmath",
        "utility", "numeric", "array", "list", "deque", "queue", "stack",
        "unordered_map", "unordered_set", "sstream",
    ]
    .into_iter()
    .collect()
});

static C_SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("function_definition", "function"),
        ("struct_specifier", "class"),
        ("enum_specifier", "type"),
        ("type_definition", "type"),
    ],
    name_fields: &[
        ("struct_specifier", "name"),
        ("enum_specifier", "name"),
    ],
    name_resolutions: &[],
    param_fields: &[("function_definition", "declarator")],
    return_type_fields: &[("function_definition", "type")],
    container_node_types: &[],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::None,
    constant_strategy: ConstantStrategy::None,
    parameter_kinds: C_PARAMETER_KINDS,
    method_promotion: &[],
};

static CPP_SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("function_definition", "function"),
        ("class_specifier", "class"),
        ("struct_specifier", "type"),
        ("enum_specifier", "type"),
        ("namespace_definition", "type"),
        ("template_declaration", "template"),
    ],
    name_fields: &[
        ("class_specifier", "name"),
        ("struct_specifier", "name"),
        ("enum_specifier", "name"),
        ("namespace_definition", "name"),
    ],
    name_resolutions: &[],
    param_fields: &[("function_definition", "declarator")],
    return_type_fields: &[("function_definition", "type")],
    container_node_types: &[
        "class_specifier",
        "struct_specifier",
        "namespace_definition",
    ],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::None,
    constant_strategy: ConstantStrategy::None,
    parameter_kinds: C_PARAMETER_KINDS,
    method_promotion: &[],
};

/// Built-in C and C++ extractor.
pub struct CFamilyExtractor {
    c: OnceLock<SpecExtractor>,
    cpp: OnceLock<SpecExtractor>,
}

impl CFamilyExtractor {
    /// Construct a fresh instance.
    pub fn new() -> Self {
        Self {
            c: OnceLock::new(),
            cpp: OnceLock::new(),
        }
    }

    fn c_delegate(&self) -> &SpecExtractor {
        self.c.get_or_init(|| {
            SpecExtractor::new(&["c"], crate::grammars::get_language("c").expect("c grammar"), &C_SPEC)
        })
    }

    fn cpp_delegate(&self) -> &SpecExtractor {
        self.cpp.get_or_init(|| {
            SpecExtractor::new(&["cpp"], crate::grammars::get_language("cpp").expect("cpp grammar"), &CPP_SPEC)
        })
    }
}

impl Default for CFamilyExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for CFamilyExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["c", "cpp"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        match ctx.language {
            "c" => self.c_delegate().extract(ctx),
            "cpp" => self.cpp_delegate().extract(ctx),
            other => Err(ExtractionError::MissingDependency(format!(
                "c_family extractor received unsupported language: {other}"
            ))),
        }
    }

    fn supports_imports(&self) -> bool {
        true
    }

    fn extract_imports(
        &self,
        ctx: &ExtractionContext<'_>,
    ) -> Result<Vec<Import>, ExtractionError> {
        let mut out = Vec::new();
        for cap in C_INCLUDE_RE.captures_iter(ctx.source).flatten() {
            if let Some(m) = cap.get(1) {
                out.push(Import {
                    specifier: m.as_str().to_string(),
                    names: Vec::new(),
                });
            }
        }
        Ok(out)
    }

    fn supports_resolution(&self) -> bool {
        true
    }

    fn generate_candidates(
        &self,
        specifier: &str,
        source_path: &str,
        _context: &ResolverContext,
    ) -> Vec<String> {
        if C_SYSTEM_HEADERS.contains(specifier) {
            return Vec::new();
        }
        let mut candidates: Vec<String> = Vec::new();
        let source_dir = posix_dirname(source_path);
        if !source_dir.is_empty() {
            candidates.push(posix_normpath(&posix_join(source_dir, specifier)));
        }
        candidates.push(specifier.to_string());
        for prefix in ["include/", "src/"] {
            candidates.push(format!("{prefix}{specifier}"));
        }
        dedupe(candidates)
    }
}

/// POSIX-style `dirname`: strip the last `/`-separated segment.
fn posix_dirname(path: &str) -> &str {
    match path.rfind('/') {
        Some(idx) => &path[..idx],
        None => "",
    }
}

/// POSIX-style join: return `right` if it is absolute, else
/// `left` + `/` + `right` (handling an empty `left` gracefully).
fn posix_join(left: &str, right: &str) -> String {
    if right.starts_with('/') {
        return right.to_string();
    }
    if left.is_empty() {
        return right.to_string();
    }
    if left.ends_with('/') {
        format!("{left}{right}")
    } else {
        format!("{left}/{right}")
    }
}

/// Collapse `.` and `..` components, mirroring `posixpath.normpath`
/// for the relative include paths this resolver sees in practice.
fn posix_normpath(path: &str) -> String {
    if path.is_empty() {
        return ".".to_string();
    }
    let is_absolute = path.starts_with('/');
    // Leading `//` has platform-specific meaning in POSIX; a single
    // leading `/` is plenty here (all include paths we see are
    // relative anyway).
    let mut out: Vec<&str> = Vec::new();
    for part in path.split('/') {
        match part {
            "" | "." => continue,
            ".." => {
                match out.last() {
                    Some(&last) if last != ".." => {
                        out.pop();
                    }
                    _ => {
                        if !is_absolute {
                            out.push("..");
                        }
                    }
                }
            }
            other => out.push(other),
        }
    }
    let joined = out.join("/");
    if is_absolute {
        if joined.is_empty() {
            "/".to_string()
        } else {
            format!("/{joined}")
        }
    } else if joined.is_empty() {
        ".".to_string()
    } else {
        joined
    }
}

/// Preserve-order dedupe for candidate lists.
fn dedupe(values: Vec<String>) -> Vec<String> {
    let mut seen: HashSet<String> = HashSet::new();
    let mut out = Vec::with_capacity(values.len());
    for v in values {
        if seen.insert(v.clone()) {
            out.push(v);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract_c(source: &str) -> Vec<Symbol> {
        CFamilyExtractor::new()
            .extract(&ExtractionContext::new(source, "mod.c", "c"))
            .expect("c extraction")
    }

    fn extract_cpp(source: &str) -> Vec<Symbol> {
        CFamilyExtractor::new()
            .extract(&ExtractionContext::new(source, "mod.cpp", "cpp"))
            .expect("cpp extraction")
    }

    #[test]
    fn empty_c_file_yields_no_symbols() {
        assert!(extract_c("").is_empty());
    }

    #[test]
    fn empty_cpp_file_yields_no_symbols() {
        assert!(extract_cpp("").is_empty());
    }

    #[test]
    fn extracts_c_function() {
        let syms = extract_c("int add(int a, int b) { return a+b; }\n");
        let func = syms
            .iter()
            .find(|s| s.kind == "function")
            .expect("function symbol");
        assert_eq!(func.name, "add");
        assert_eq!(func.language, "c");
        let sig = func.signature.as_deref().expect("signature");
        assert!(sig.contains("add"));
        assert!(sig.contains("int a"));
        assert!(sig.contains("int b"));
    }

    #[test]
    fn extracts_c_struct() {
        let syms = extract_c("struct Point { int x; };\n");
        let s = syms
            .iter()
            .find(|s| s.kind == "class" && s.name == "Point")
            .expect("struct Point");
        assert_eq!(s.language, "c");
    }

    #[test]
    fn extracts_cpp_class() {
        let syms = extract_cpp("class Dog { public: void bark(); };\n");
        let cls = syms
            .iter()
            .find(|s| s.kind == "class" && s.name == "Dog")
            .expect("class Dog");
        assert_eq!(cls.language, "cpp");
    }

    #[test]
    fn c_function_picks_up_preceding_block_comment() {
        let src = "/* doc */\nint x() { return 0; }\n";
        let syms = extract_c(src);
        let func = syms
            .iter()
            .find(|s| s.kind == "function")
            .expect("function symbol");
        let doc = func.docstring.as_deref().unwrap_or("");
        assert!(doc.contains("doc"), "expected docstring to contain 'doc', got {doc:?}");
    }

    #[test]
    fn advertises_c_and_cpp_languages() {
        assert_eq!(CFamilyExtractor::new().languages(), &["c", "cpp"]);
    }

    fn imports(src: &str, lang: &str, filename: &str) -> Vec<sylvan_core::Import> {
        CFamilyExtractor::new()
            .extract_imports(&ExtractionContext::new(src, filename, lang))
            .expect("c_family imports")
    }

    fn candidates(specifier: &str, source_path: &str) -> Vec<String> {
        let ctx = sylvan_core::ResolverContext::default();
        CFamilyExtractor::new().generate_candidates(specifier, source_path, &ctx)
    }

    #[test]
    fn extracts_angle_and_quoted_includes() {
        let src = "#include <stdio.h>\n#include \"myhdr.h\"\n";
        let imps = imports(src, "c", "mod.c");
        assert_eq!(imps.len(), 2);
        assert_eq!(imps[0].specifier, "stdio.h");
        assert!(imps[0].names.is_empty());
        assert_eq!(imps[1].specifier, "myhdr.h");
        assert!(imps[1].names.is_empty());
    }

    #[test]
    fn system_header_yields_no_candidates() {
        assert!(candidates("stdio.h", "src/foo/mod.c").is_empty());
        assert!(candidates("vector", "src/foo/mod.cpp").is_empty());
    }

    #[test]
    fn local_header_emits_relative_root_and_prefixed_candidates() {
        let c = candidates("myhdr.h", "src/foo/mod.c");
        assert_eq!(
            c,
            vec![
                "src/foo/myhdr.h".to_string(),
                "myhdr.h".to_string(),
                "include/myhdr.h".to_string(),
                "src/myhdr.h".to_string(),
            ],
        );
    }

    #[test]
    fn parent_relative_include_normalizes_dotdot() {
        let c = candidates("../other.h", "src/foo/mod.c");
        assert_eq!(
            c,
            vec![
                "src/other.h".to_string(),
                "../other.h".to_string(),
                "include/../other.h".to_string(),
                "src/../other.h".to_string(),
            ],
        );
    }

    #[test]
    fn root_level_source_skips_relative_candidate() {
        let c = candidates("myhdr.h", "mod.c");
        assert_eq!(
            c,
            vec![
                "myhdr.h".to_string(),
                "include/myhdr.h".to_string(),
                "src/myhdr.h".to_string(),
            ],
        );
    }

    #[test]
    fn multiple_includes_produce_multiple_records() {
        let src = "#include <stdio.h>\n#include <stdlib.h>\n#include \"a.h\"\n";
        let imps = imports(src, "c", "mod.c");
        assert_eq!(imps.len(), 3);
        assert_eq!(imps[0].specifier, "stdio.h");
        assert_eq!(imps[1].specifier, "stdlib.h");
        assert_eq!(imps[2].specifier, "a.h");
    }

    #[test]
    fn cpp_includes_work_the_same_as_c() {
        let src = "#include <iostream>\n#include \"dog.hpp\"\n";
        let imps = imports(src, "cpp", "mod.cpp");
        assert_eq!(imps.len(), 2);
        assert_eq!(imps[0].specifier, "iostream");
        assert_eq!(imps[1].specifier, "dog.hpp");
    }

    #[test]
    fn dedupe_preserves_first_occurrence_order() {
        // When source_dir + specifier collapses to the same path as
        // the plain specifier (i.e. source at repo root), the
        // relative-join branch is skipped so no duplicates appear;
        // this test guards against a regression where both branches
        // fire and produce ["myhdr.h", "myhdr.h", ...].
        let c = candidates("myhdr.h", "mod.c");
        assert_eq!(c.iter().filter(|s| s.as_str() == "myhdr.h").count(), 1);
    }
}
