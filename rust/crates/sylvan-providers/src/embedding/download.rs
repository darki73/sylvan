//! HuggingFace model download + cache (sync API).
//!
//! Resolves a model name to an HF repo, fetches `model.onnx` and
//! `tokenizer.json`, caches them under sylvan's own model directory
//! (default `$SYLVAN_HOME/models/`, i.e. `~/.sylvan/models/`), and
//! returns the local paths. Successive calls reuse the cached copy.

use std::path::PathBuf;

use hf_hub::api::sync::ApiBuilder;

use super::ProviderError;

/// Known model identifiers mapped to their HuggingFace repo + file
/// layout. Extend this table as new default models are supported.
struct KnownModel {
    /// Canonical name callers use (matches fastembed identifiers).
    alias: &'static str,
    /// HF repo id that hosts an ONNX-exported version of the model.
    repo: &'static str,
    /// Path to the ONNX weights within the repo.
    onnx_file: &'static str,
    /// Path to the tokenizer within the repo.
    tokenizer_file: &'static str,
}

const KNOWN_MODELS: &[KnownModel] = &[
    KnownModel {
        alias: "sentence-transformers/all-MiniLM-L6-v2",
        repo: "sentence-transformers/all-MiniLM-L6-v2",
        onnx_file: "onnx/model.onnx",
        tokenizer_file: "tokenizer.json",
    },
    KnownModel {
        alias: "Xenova/all-MiniLM-L6-v2",
        repo: "Xenova/all-MiniLM-L6-v2",
        onnx_file: "onnx/model.onnx",
        tokenizer_file: "tokenizer.json",
    },
];

/// Local paths to a downloaded model's ONNX weights and tokenizer.
#[derive(Debug, Clone)]
pub struct DownloadedModel {
    /// Absolute path to the `.onnx` file on disk.
    pub model_path: PathBuf,
    /// Absolute path to the `tokenizer.json` file on disk.
    pub tokenizer_path: PathBuf,
}

/// Resolve `name` to an HF repo entry, downloading (or reusing) the
/// weights and tokenizer files. Network access is sync and blocking;
/// call from a background thread if the caller is async.
///
/// Cache location: [`sylvan_model_dir`] (respects the `SYLVAN_HOME`
/// env var; defaults to `~/.sylvan/models/`).
pub fn download(name: &str) -> Result<DownloadedModel, ProviderError> {
    download_into(name, &sylvan_model_dir()?)
}

/// Like [`download`] but writes into `cache_dir` instead of the sylvan
/// default. Useful for tests and for callers that want to share cache
/// space with other HF-aware tooling (`~/.cache/huggingface/hub/`).
pub fn download_into(
    name: &str,
    cache_dir: &std::path::Path,
) -> Result<DownloadedModel, ProviderError> {
    let known = KNOWN_MODELS
        .iter()
        .find(|m| m.alias == name)
        .ok_or_else(|| ProviderError::Tokenizer(format!("unknown model name: {name}")))?;

    std::fs::create_dir_all(cache_dir).map_err(|source| ProviderError::Io {
        path: cache_dir.to_path_buf(),
        source,
    })?;

    let api = ApiBuilder::new()
        .with_cache_dir(cache_dir.to_path_buf())
        .build()
        .map_err(|err| ProviderError::Tokenizer(format!("hf-hub init: {err}")))?;
    let repo = api.model(known.repo.to_string());

    let model_path = repo
        .get(known.onnx_file)
        .map_err(|err| ProviderError::Tokenizer(format!("hf-hub download onnx: {err}")))?;
    let tokenizer_path = repo
        .get(known.tokenizer_file)
        .map_err(|err| ProviderError::Tokenizer(format!("hf-hub download tokenizer: {err}")))?;

    Ok(DownloadedModel {
        model_path,
        tokenizer_path,
    })
}

/// Default model used throughout sylvan when no explicit name is given.
pub const DEFAULT_MODEL: &str = "sentence-transformers/all-MiniLM-L6-v2";

/// Default cache directory for model downloads.
///
/// Honours `SYLVAN_HOME` when set, otherwise falls back to the OS
/// home directory plus `.sylvan`. Sub-directory `models/` is appended.
pub fn sylvan_model_dir() -> Result<PathBuf, ProviderError> {
    if let Ok(home) = std::env::var("SYLVAN_HOME") {
        return Ok(PathBuf::from(home).join("models"));
    }
    let home = home_dir().ok_or_else(|| {
        ProviderError::Tokenizer("could not resolve user home directory for model cache".into())
    })?;
    Ok(home.join(".sylvan").join("models"))
}

fn home_dir() -> Option<PathBuf> {
    // Avoid pulling the full `home` crate for this one helper — the
    // platform env vars that matter are HOME on unix, USERPROFILE on
    // Windows.
    #[cfg(windows)]
    {
        std::env::var_os("USERPROFILE").map(PathBuf::from)
    }
    #[cfg(not(windows))]
    {
        std::env::var_os("HOME").map(PathBuf::from)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unknown_model_errors_cleanly() {
        let dir = tempfile::tempdir().unwrap();
        let err = download_into("not-a-real-model", dir.path()).unwrap_err();
        match err {
            ProviderError::Tokenizer(msg) => {
                assert!(msg.contains("not-a-real-model"), "unexpected: {msg}");
            }
            other => panic!("expected Tokenizer error, got {other:?}"),
        }
    }

    #[test]
    fn known_models_are_non_empty() {
        assert!(!KNOWN_MODELS.is_empty());
        assert!(KNOWN_MODELS.iter().any(|m| m.alias == DEFAULT_MODEL));
    }

    #[test]
    fn sylvan_model_dir_honours_env() {
        let tmp = tempfile::tempdir().unwrap();
        // SAFETY: env var mutation is test-local; no other threads race.
        unsafe {
            std::env::set_var("SYLVAN_HOME", tmp.path());
        }
        let dir = sylvan_model_dir().unwrap();
        assert_eq!(dir, tmp.path().join("models"));
        unsafe {
            std::env::remove_var("SYLVAN_HOME");
        }
    }
}
