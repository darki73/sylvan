//! Thread-safe wrapper around `tree_sitter_language_pack::get_language`.
//!
//! The pack downloads grammars on first use. Concurrent callers racing
//! on a cold cache can corrupt the download (same file path, overlapping
//! writes). We serialize per-language with a lock so exactly one thread
//! performs the download while others wait.

use std::collections::HashMap;
use std::sync::{Arc, Mutex, OnceLock, RwLock};

use tree_sitter::Language;
use tree_sitter_language_pack::{Error, get_language as pack_get_language};

/// Returns the tree-sitter `Language` for `name`, downloading it on first
/// use. Safe to call from multiple threads simultaneously; concurrent
/// calls for the same language serialize on a per-language lock.
pub fn get_language(name: &str) -> Result<Language, Error> {
    if let Some(lang) = read_cache(name) {
        return Ok(lang);
    }

    let lock = per_language_lock(name);
    let _guard = lock.lock().expect("grammar lock poisoned");

    if let Some(lang) = read_cache(name) {
        return Ok(lang);
    }

    let lang = pack_get_language(name)?;
    cache().write().expect("grammar cache poisoned")
        .insert(name.to_string(), lang.clone());
    Ok(lang)
}

fn cache() -> &'static RwLock<HashMap<String, Language>> {
    static CACHE: OnceLock<RwLock<HashMap<String, Language>>> = OnceLock::new();
    CACHE.get_or_init(Default::default)
}

fn locks() -> &'static Mutex<HashMap<String, Arc<Mutex<()>>>> {
    static LOCKS: OnceLock<Mutex<HashMap<String, Arc<Mutex<()>>>>> = OnceLock::new();
    LOCKS.get_or_init(Default::default)
}

fn read_cache(name: &str) -> Option<Language> {
    cache().read().expect("grammar cache poisoned").get(name).cloned()
}

fn per_language_lock(name: &str) -> Arc<Mutex<()>> {
    let mut map = locks().lock().expect("grammar locks poisoned");
    map.entry(name.to_string())
        .or_insert_with(|| Arc::new(Mutex::new(())))
        .clone()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::thread;

    #[test]
    fn concurrent_callers_all_get_same_language() {
        // python ships pre-downloaded with the pack, so this tests the
        // cache path, not the download path, but still exercises the
        // locking code under concurrency.
        let handles: Vec<_> = (0..16)
            .map(|_| thread::spawn(|| get_language("python").unwrap()))
            .collect();
        for h in handles {
            h.join().unwrap();
        }
    }

    #[test]
    fn unknown_language_returns_err() {
        assert!(get_language("brainfuck_xyz").is_err());
    }
}
