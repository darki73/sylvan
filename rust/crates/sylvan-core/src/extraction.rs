//! Traits for the per-language symbol-extraction pipeline.
//!
//! Every language plugin implements [`LanguageExtractor`]. A registry
//! in the indexing crate holds one instance per canonical language
//! identifier (`"python"`, `"typescript"`, ...) and dispatches on the
//! identifier at parse time. The trait deliberately stays narrow: it
//! reports which languages it speaks, and it extracts symbols from a
//! pre-parsed source string. Everything else (tree-sitter wiring,
//! file I/O, enrichment passes like complexity / call-site extraction)
//! lives in the calling layer.

use crate::symbol::Symbol;

/// Repo-scoped state passed to import-resolution plugins.
///
/// Mirrors the Python `ResolverContext` dataclass. The orchestrator
/// builds one per repo (populated from `composer.json` / `tsconfig.json`
/// if present) and hands it to each language's candidate generator.
/// Keys and values are plain `String` so the Python bridge can fill it
/// from dicts without worrying about lifetimes.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ResolverContext {
    /// PHP PSR-4 namespace prefix to directory list mapping.
    pub psr4_mappings: std::collections::BTreeMap<String, Vec<String>>,
    /// TypeScript path alias to directory list mapping (without
    /// trailing `/*`, matching the Python orchestrator's convention).
    pub tsconfig_aliases: std::collections::BTreeMap<String, Vec<String>>,
}

/// A single import statement extracted from source.
///
/// Mirrors the Python plugin's `{"specifier", "names"}` dict. The
/// resolver pass downstream turns `specifier` into a concrete file id
/// using language-specific candidate generation; `names` captures the
/// individual symbols pulled from that specifier so downstream
/// tooling can pin usages. Plain `import foo` / `require "x"` style
/// imports leave `names` empty.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Import {
    /// Raw module/package/file specifier.
    pub specifier: String,
    /// Individual names imported from `specifier`, if any.
    pub names: Vec<String>,
}

/// Extraction context carrying the shared inputs every language needs.
///
/// Kept as a borrow-heavy struct so implementors can slice into
/// `source` without copies; tree-sitter consumers re-encode to UTF-8
/// bytes once and pass them alongside the string slice.
#[derive(Debug)]
pub struct ExtractionContext<'a> {
    /// Raw source text.
    pub source: &'a str,
    /// Raw source as UTF-8 bytes. Pre-computed so per-node slicing by
    /// tree-sitter byte offsets avoids repeated encoding.
    pub source_bytes: &'a [u8],
    /// Relative file path used for stable symbol IDs.
    pub filename: &'a str,
    /// Canonical language identifier (matches the registry key).
    pub language: &'a str,
}

impl<'a> ExtractionContext<'a> {
    /// Build a fresh context, pre-encoding `source` into a byte buffer
    /// the caller owns for the duration of the extraction call.
    pub fn new(source: &'a str, filename: &'a str, language: &'a str) -> Self {
        Self {
            source,
            source_bytes: source.as_bytes(),
            filename,
            language,
        }
    }
}

/// Error returned by an extractor that cannot run for this input.
///
/// Parse errors are not bubbled through this type — implementations
/// should skip bad files rather than fail the whole indexing pass, so
/// per-file errors are absorbed internally and the returned `Vec` is
/// just empty on parse failure. Only configuration-level failures
/// (grammar load, missing dependency) surface as errors.
#[derive(Debug, thiserror::Error)]
pub enum ExtractionError {
    /// The tree-sitter grammar for this language could not be loaded.
    #[error("grammar {language:?} could not be loaded: {message}")]
    GrammarLoad {
        /// Language identifier whose grammar failed to load.
        language: String,
        /// Human-readable reason.
        message: String,
    },
    /// A required external dependency is not available.
    #[error("missing dependency: {0}")]
    MissingDependency(String),
}

/// A pluggable extractor for a specific language (or language family).
pub trait LanguageExtractor: Send + Sync {
    /// Canonical language identifiers this extractor handles.
    ///
    /// A single extractor may claim multiple aliases — for example the
    /// JavaScript extractor typically handles `"javascript"`,
    /// `"typescript"`, `"tsx"`, `"jsx"`, and `"mjs"`.
    fn languages(&self) -> &'static [&'static str];

    /// Extract all symbols from the context.
    ///
    /// Parse failures and individual-symbol extraction errors return
    /// an empty or partial list; only environmental issues (grammar
    /// missing, etc.) surface as `Err`.
    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError>;

    /// Extract raw import statements from the context.
    ///
    /// The default is an empty list so languages that do not speak
    /// imports (shell, stylesheets) fall through silently. Languages
    /// that do implement this override the default and walk the
    /// grammar. Resolution of specifiers to files happens in a
    /// later pipeline step, not here.
    fn extract_imports(
        &self,
        _ctx: &ExtractionContext<'_>,
    ) -> Result<Vec<Import>, ExtractionError> {
        Ok(Vec::new())
    }

    /// Whether this extractor implements [`Self::extract_imports`].
    ///
    /// The Python proxy uses this to decide whether to route through
    /// Rust or fall through to the legacy per-language extractor. The
    /// default is `false` so incremental ports do not silently mask
    /// Python's import output with an empty Rust result.
    fn supports_imports(&self) -> bool {
        false
    }

    /// Generate candidate file paths for an import specifier.
    ///
    /// Pure function: no file-system or database access. The resolver
    /// pass in the pipeline pairs the returned candidates against the
    /// repo's indexed files to pick the winning path. Languages that
    /// do not participate in resolution keep the default empty list.
    fn generate_candidates(
        &self,
        _specifier: &str,
        _source_path: &str,
        _context: &ResolverContext,
    ) -> Vec<String> {
        Vec::new()
    }

    /// Whether this extractor implements [`Self::generate_candidates`].
    fn supports_resolution(&self) -> bool {
        false
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Stub;

    impl LanguageExtractor for Stub {
        fn languages(&self) -> &'static [&'static str] {
            &["stub", "dummy"]
        }
        fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
            Ok(vec![Symbol {
                name: ctx.filename.to_string(),
                language: ctx.language.to_string(),
                ..Symbol::default()
            }])
        }
    }

    #[test]
    fn stub_extractor_roundtrip() {
        let ctx = ExtractionContext::new("x = 1\n", "a.py", "stub");
        let syms = Stub.extract(&ctx).unwrap();
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].name, "a.py");
        assert_eq!(syms[0].language, "stub");
    }

    #[test]
    fn context_exposes_bytes() {
        let ctx = ExtractionContext::new("héllo", "f.py", "python");
        assert_eq!(ctx.source.len(), 6);
        assert_eq!(ctx.source_bytes.len(), 6);
    }

    #[test]
    fn stub_advertises_multiple_languages() {
        assert_eq!(Stub.languages().len(), 2);
    }
}
