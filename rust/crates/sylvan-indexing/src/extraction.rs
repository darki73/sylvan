//! Language-extractor registry and dispatch.
//!
//! Every language plugin implements [`sylvan_core::LanguageExtractor`]
//! and registers itself through a single [`Registry`]. The dispatcher
//! has zero language-specific knowledge — adding a new language is one
//! file + one registration call, never a dispatcher edit.

use std::collections::HashMap;
use std::sync::Arc;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

pub mod languages;

/// Thread-safe registry of language extractors.
///
/// Built once at startup (by the composition root — a binary `main` or
/// the PyO3 module init) and shared as `Arc<Registry>` across the
/// indexing pipeline. Lookups are O(1); the registry itself owns the
/// extractor instances via `Arc` so cloning a `Registry` is cheap.
#[derive(Default, Clone)]
pub struct Registry {
    by_language: HashMap<&'static str, Arc<dyn LanguageExtractor>>,
}

impl Registry {
    /// Build an empty registry. Use [`Registry::with_builtins`] unless
    /// you specifically want to control which languages are available
    /// (e.g. for a minimal binary).
    pub fn empty() -> Self {
        Self::default()
    }

    /// Build a registry pre-populated with every built-in extractor
    /// shipped by this crate. Downstream code should prefer this
    /// constructor; custom registrations go on top.
    pub fn with_builtins() -> Self {
        let mut reg = Self::empty();
        languages::register_builtins(&mut reg);
        reg
    }

    /// Register an extractor for every language it advertises.
    ///
    /// Later registrations override earlier ones, which is what makes
    /// "I want to replace the JavaScript extractor with my own"
    /// possible from user code without touching the built-in table.
    pub fn register(&mut self, extractor: Arc<dyn LanguageExtractor>) {
        for &lang in extractor.languages() {
            self.by_language.insert(lang, Arc::clone(&extractor));
        }
    }

    /// Look up the extractor for `language`, or `None` if unregistered.
    pub fn get(&self, language: &str) -> Option<Arc<dyn LanguageExtractor>> {
        self.by_language.get(language).cloned()
    }

    /// Sorted list of language identifiers the registry knows about.
    pub fn languages(&self) -> Vec<&'static str> {
        let mut langs: Vec<&'static str> = self.by_language.keys().copied().collect();
        langs.sort_unstable();
        langs
    }

    /// Dispatch extraction for `ctx.language`. Returns an empty vector
    /// when no extractor is registered, matching the Python
    /// implementation's silent-skip behaviour on unknown languages.
    pub fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        match self.get(ctx.language) {
            Some(extractor) => extractor.extract(ctx),
            None => Ok(Vec::new()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct FakeA;
    impl LanguageExtractor for FakeA {
        fn languages(&self) -> &'static [&'static str] {
            &["a", "a-alias"]
        }
        fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
            Ok(vec![Symbol {
                name: format!("a:{}", ctx.filename),
                ..Symbol::default()
            }])
        }
    }

    struct FakeB;
    impl LanguageExtractor for FakeB {
        fn languages(&self) -> &'static [&'static str] {
            &["b"]
        }
        fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
            Ok(vec![Symbol {
                name: format!("b:{}", ctx.filename),
                ..Symbol::default()
            }])
        }
    }

    struct FakeAReplacement;
    impl LanguageExtractor for FakeAReplacement {
        fn languages(&self) -> &'static [&'static str] {
            &["a"]
        }
        fn extract(&self, _ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
            Ok(vec![Symbol {
                name: "replacement".into(),
                ..Symbol::default()
            }])
        }
    }

    #[test]
    fn registry_dispatches_by_language() {
        let mut reg = Registry::empty();
        reg.register(Arc::new(FakeA));
        reg.register(Arc::new(FakeB));

        let ctx = ExtractionContext::new("x", "f", "a");
        let syms = reg.extract(&ctx).unwrap();
        assert_eq!(syms[0].name, "a:f");
    }

    #[test]
    fn registry_exposes_all_advertised_aliases() {
        let mut reg = Registry::empty();
        reg.register(Arc::new(FakeA));
        assert_eq!(reg.languages(), vec!["a", "a-alias"]);
    }

    #[test]
    fn unregistered_language_returns_empty() {
        let reg = Registry::empty();
        let ctx = ExtractionContext::new("x", "f", "nope");
        assert!(reg.extract(&ctx).unwrap().is_empty());
    }

    #[test]
    fn later_registration_replaces_earlier() {
        let mut reg = Registry::empty();
        reg.register(Arc::new(FakeA));
        reg.register(Arc::new(FakeAReplacement));
        let ctx = ExtractionContext::new("x", "f", "a");
        let syms = reg.extract(&ctx).unwrap();
        assert_eq!(syms[0].name, "replacement");
        // alias from the original survives because the replacement
        // does not advertise it — explicit scope, not accidental.
        let ctx_alias = ExtractionContext::new("x", "f", "a-alias");
        assert_eq!(reg.extract(&ctx_alias).unwrap()[0].name, "a:f");
    }

    #[test]
    fn with_builtins_includes_registered_languages() {
        // As languages land, this assertion grows. It serves as a
        // lightweight sanity check that `register_builtins` is
        // wiring them in — if a sub-agent ports a language but
        // forgets the registration line, this test catches it.
        let reg = Registry::with_builtins();
        let langs = reg.languages();
        assert!(
            langs.contains(&"json"),
            "expected json in builtins, got {langs:?}"
        );
    }
}
