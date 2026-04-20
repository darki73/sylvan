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
pub mod blade;
pub mod c_family;
pub mod csharp;
pub mod css;
pub mod dart;
pub mod elixir;
pub mod erlang;
pub mod fortran;
pub mod gdscript;
pub mod gleam;
pub mod go;
pub mod graphql;
pub mod groovy;
pub mod haskell;
pub mod hcl;
pub mod java;
pub mod javascript;
pub mod json;
pub mod julia;
pub mod kotlin;
pub mod lua;
pub mod nix;
pub mod objc;
pub mod perl;
pub mod php;
pub mod proto;
pub mod python;
pub mod r;
pub mod ruby;
pub mod rust;
pub mod scala;
pub mod scss;
pub mod less;
pub mod sql;
pub mod stylus;
pub mod swift;
pub mod typescript;
pub mod vue;

/// Populate `reg` with every extractor this crate ships. Safe to call
/// on a pre-populated registry; later registrations replace earlier
/// ones for the same language identifier.
pub fn register_builtins(reg: &mut Registry) {
    reg.register(Arc::new(bash::BashExtractor::new()));
    reg.register(Arc::new(blade::BladeExtractor::new()));
    reg.register(Arc::new(c_family::CFamilyExtractor::new()));
    reg.register(Arc::new(csharp::CSharpExtractor::new()));
    reg.register(Arc::new(css::CssExtractor::new()));
    reg.register(Arc::new(dart::DartExtractor::new()));
    reg.register(Arc::new(elixir::ElixirExtractor::new()));
    reg.register(Arc::new(erlang::ErlangExtractor::new()));
    reg.register(Arc::new(fortran::FortranExtractor::new()));
    reg.register(Arc::new(gdscript::GdscriptExtractor::new()));
    reg.register(Arc::new(gleam::GleamExtractor::new()));
    reg.register(Arc::new(go::GoExtractor::new()));
    reg.register(Arc::new(graphql::GraphQLExtractor::new()));
    reg.register(Arc::new(groovy::GroovyExtractor::new()));
    reg.register(Arc::new(haskell::HaskellExtractor::new()));
    reg.register(Arc::new(hcl::HclExtractor::new()));
    reg.register(Arc::new(java::JavaExtractor::new()));
    reg.register(Arc::new(javascript::JavaScriptExtractor::new()));
    reg.register(Arc::new(json::JsonExtractor::new()));
    reg.register(Arc::new(julia::JuliaExtractor::new()));
    reg.register(Arc::new(kotlin::KotlinExtractor::new()));
    reg.register(Arc::new(lua::LuaExtractor::new()));
    reg.register(Arc::new(nix::NixExtractor::new()));
    reg.register(Arc::new(objc::ObjCExtractor::new()));
    reg.register(Arc::new(perl::PerlExtractor::new()));
    reg.register(Arc::new(php::PhpExtractor::new()));
    reg.register(Arc::new(proto::ProtoExtractor::new()));
    reg.register(Arc::new(python::PythonExtractor::new()));
    reg.register(Arc::new(r::RExtractor::new()));
    reg.register(Arc::new(ruby::RubyExtractor::new()));
    reg.register(Arc::new(rust::RustExtractor::new()));
    reg.register(Arc::new(scala::ScalaExtractor::new()));
    reg.register(Arc::new(scss::ScssExtractor::new()));
    reg.register(Arc::new(less::LessExtractor::new()));
    reg.register(Arc::new(sql::SqlExtractor::new()));
    reg.register(Arc::new(stylus::StylusExtractor::new()));
    reg.register(Arc::new(swift::SwiftExtractor::new()));
    reg.register(Arc::new(typescript::TypeScriptExtractor::new()));
    reg.register(Arc::new(vue::VueExtractor::new()));
}
