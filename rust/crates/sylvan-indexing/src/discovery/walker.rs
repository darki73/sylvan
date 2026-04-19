//! Non-git walker backend.
//!
//! Used when `root` is not a git work tree or when `use_git` is off.
//! Built on the `ignore` crate, which reads `.gitignore` / `.ignore`
//! files and applies them during the walk.

use std::path::Path;

use ignore::WalkBuilder;
use sylvan_core::discovery::{DiscoveryResult, SkipReason};
use sylvan_security::filters::should_skip_dir;

use crate::discovery::{DiscoveryOptions, has_skippable_directory, normalize_separators, record};

/// Walk `root` sequentially, populating `result` with accepted files
/// and skip diagnostics.
///
/// Sequential for parity with the Python `os.walk` implementation; can
/// be parallelised via `ignore::WalkBuilder::threads` and a locked
/// accumulator once parity is verified against real repositories.
pub(crate) fn discover_via_walk(
    root: &Path,
    options: &DiscoveryOptions,
    result: &mut DiscoveryResult,
) {
    let walker = WalkBuilder::new(root)
        .standard_filters(true)
        .require_git(false)
        .git_ignore(true)
        .git_exclude(true)
        .git_global(false)
        .hidden(false)
        .follow_links(false)
        .filter_entry(|entry| {
            if entry.depth() == 0 {
                return true;
            }
            let is_dir = entry.file_type().map(|t| t.is_dir()).unwrap_or(false);
            if !is_dir {
                return true;
            }
            let name = entry.file_name().to_string_lossy();
            !should_skip_dir(&name)
        })
        .build();

    for entry in walker {
        let entry = match entry {
            Ok(e) => e,
            Err(_) => continue,
        };
        let is_file = entry.file_type().map(|t| t.is_file()).unwrap_or(false);
        if !is_file {
            continue;
        }
        let path = entry.path();
        let rel_raw = match path.strip_prefix(root) {
            Ok(p) => p.to_string_lossy().to_string(),
            Err(_) => continue,
        };
        let rel = normalize_separators(&rel_raw);
        if result.files.len() >= options.max_files {
            result.add_skipped(rel, SkipReason::MaxFilesReached);
            continue;
        }
        if has_skippable_directory(&rel) {
            result.add_skipped(rel, SkipReason::SkipDir);
            continue;
        }
        record(root, path, &rel, options.max_file_size, result);
    }
}
