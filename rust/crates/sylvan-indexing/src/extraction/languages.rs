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

pub mod json;

/// Populate `reg` with every extractor this crate ships. Safe to call
/// on a pre-populated registry; later registrations replace earlier
/// ones for the same language identifier.
pub fn register_builtins(reg: &mut Registry) {
    reg.register(Arc::new(json::JsonExtractor::new()));
    // Additional languages land here one file at a time — see the
    // module doc for the three-step addition recipe.
}
