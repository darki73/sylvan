//! Built-in language extractors.
//!
//! Each supported language lives in its own submodule under this one
//! and registers itself into the [`super::Registry`] via
//! [`register_builtins`]. Adding a new language is a three-step,
//! file-local change: drop the implementation in
//! `languages/<name>.rs`, add `mod <name>;` below, add one
//! `reg.register(...)` line inside `register_builtins`.
//!
//! Nothing else in the crate — not the dispatcher, not the pipeline,
//! not any dependent crate — is aware of the specific language list.

use std::sync::Arc;

use super::Registry;

/// Populate `reg` with every extractor this crate ships. Safe to call
/// on a pre-populated registry; later registrations replace earlier
/// ones for the same language identifier.
pub fn register_builtins(reg: &mut Registry) {
    // Intentionally empty right now: the walker + first language port
    // lands in follow-up work. The registration surface stays stable
    // so sub-agents can fan out one language per file without touching
    // this table more than once each.
    let _ = reg;
    // Example of the final shape:
    // reg.register(Arc::new(python::PythonExtractor::new()));
    // reg.register(Arc::new(javascript::JavaScriptExtractor::new()));
    let _ = Arc::<()>::new; // keep the import used in release builds
}
