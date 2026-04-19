//! Quick smoke check: point `discover_files` at a real repo, print
//! acceptance/skip summary. Not a test — a CLI aide.
//!
//! Run with:
//!
//! ```text
//! cargo run --example smoke_discover -p sylvan-indexing -- <path>
//! ```

use std::env;
use std::path::PathBuf;

use sylvan_indexing::discovery::{DiscoveryOptions, discover_files};

fn main() {
    let root: PathBuf = env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."));
    let options = DiscoveryOptions {
        max_files: 100_000,
        ..Default::default()
    };
    let start = std::time::Instant::now();
    let result = discover_files(&root, &options);
    let elapsed = start.elapsed();
    println!("root:       {}", root.display());
    println!("git_head:   {:?}", result.git_head);
    println!("files:      {}", result.files.len());
    println!("total seen: {}", result.total_found());
    println!("wall:       {elapsed:?}");
    let mut reasons: Vec<_> = result.skipped.iter().collect();
    reasons.sort_by_key(|(k, _)| (*k).clone());
    for (reason, paths) in reasons {
        println!("  skipped[{reason}]: {}", paths.len());
    }
}
