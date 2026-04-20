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

pub mod bash;
pub mod c_family;
pub mod csharp;
pub mod css;
pub mod go;
pub mod java;
pub mod javascript;
pub mod json;
pub mod php;
pub mod python;
pub mod ruby;
pub mod rust;
pub mod typescript;

/// Populate `reg` with every extractor this crate ships. Safe to call
/// on a pre-populated registry; later registrations replace earlier
/// ones for the same language identifier.
pub fn register_builtins(reg: &mut Registry) {
    reg.register(Arc::new(bash::BashExtractor::new()));
    reg.register(Arc::new(c_family::CFamilyExtractor::new()));
    reg.register(Arc::new(csharp::CSharpExtractor::new()));
    reg.register(Arc::new(css::CssExtractor::new()));
    reg.register(Arc::new(go::GoExtractor::new()));
    reg.register(Arc::new(java::JavaExtractor::new()));
    reg.register(Arc::new(javascript::JavaScriptExtractor::new()));
    reg.register(Arc::new(json::JsonExtractor::new()));
    reg.register(Arc::new(php::PhpExtractor::new()));
    reg.register(Arc::new(python::PythonExtractor::new()));
    reg.register(Arc::new(ruby::RubyExtractor::new()));
    reg.register(Arc::new(rust::RustExtractor::new()));
    reg.register(Arc::new(typescript::TypeScriptExtractor::new()));
}
