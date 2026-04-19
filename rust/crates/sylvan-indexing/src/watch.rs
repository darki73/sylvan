//! Filesystem watcher built on the `notify` crate.
//!
//! Replaces the previous Python `watchfiles` integration. Debouncing is
//! delegated to `notify-debouncer-full`, which groups rapid-fire events
//! (e.g. editor save flurries) into a single batch.
//!
//! The public surface is deliberately small: [`Watcher::start`] returns
//! a handle whose [`Watcher::next_batch`] call blocks until either a
//! batch is available or the supplied timeout elapses. Dropping the
//! handle stops the watcher cleanly.

use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::sync::mpsc::{Receiver, RecvTimeoutError, channel};
use std::time::Duration;

use notify::{EventKind, RecursiveMode};
use notify_debouncer_full::{DebounceEventResult, Debouncer, FileIdMap, new_debouncer};

/// A file-change event surfaced to the Python layer.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct FileChange {
    /// Kind of change.
    pub kind: ChangeKind,
    /// Absolute path that changed.
    pub path: PathBuf,
}

/// Collapsed change classification.
///
/// `notify` emits finer-grained event kinds; we fold them into the three
/// buckets the Python proxy cares about.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ChangeKind {
    /// Path newly created or renamed into the tree.
    Added,
    /// Existing path had its contents or metadata modified.
    Modified,
    /// Path removed or renamed out of the tree.
    Removed,
}

/// A running filesystem watcher.
///
/// Keeps the `notify` debouncer alive for its lifetime. Drop to stop.
pub struct Watcher {
    _debouncer: Debouncer<notify::RecommendedWatcher, FileIdMap>,
    rx: Mutex<Receiver<Vec<FileChange>>>,
}

/// Errors raised when starting or driving a [`Watcher`].
#[derive(Debug, thiserror::Error)]
pub enum WatchError {
    /// The configured root directory was not valid or could not be
    /// registered with the underlying notify backend.
    #[error("failed to start watching {path:?}: {source}")]
    Start {
        /// Path the caller asked to watch.
        path: PathBuf,
        /// Underlying `notify` error.
        #[source]
        source: notify::Error,
    },
}

impl Watcher {
    /// Start watching `root` recursively with `debounce` granularity.
    ///
    /// Events are grouped in batches no shorter than `debounce`. The
    /// watcher uses the platform's native backend (inotify, ReadDirectoryChangesW,
    /// FSEvents) via `notify`.
    ///
    /// # Errors
    ///
    /// Returns [`WatchError::Start`] if `root` cannot be registered
    /// with the underlying OS facility.
    pub fn start(root: &Path, debounce: Duration) -> Result<Self, WatchError> {
        let (tx, rx) = channel::<Vec<FileChange>>();
        let mut debouncer = new_debouncer(debounce, None, move |result: DebounceEventResult| {
            let events = match result {
                Ok(events) => events,
                Err(_) => return,
            };
            let batch: Vec<FileChange> = events
                .into_iter()
                .flat_map(|event| classify(&event.event))
                .collect();
            if batch.is_empty() {
                return;
            }
            // Receiver drop is the normal shutdown signal; don't panic.
            let _ = tx.send(batch);
        })
        .map_err(|source| WatchError::Start {
            path: root.to_path_buf(),
            source,
        })?;

        debouncer
            .watch(root, RecursiveMode::Recursive)
            .map_err(|source| WatchError::Start {
                path: root.to_path_buf(),
                source,
            })?;

        Ok(Self {
            _debouncer: debouncer,
            rx: Mutex::new(rx),
        })
    }

    /// Block up to `timeout` waiting for the next batch of changes.
    ///
    /// Returns `None` if no batch arrived within `timeout`. Returns the
    /// batch if one arrived. Returns an empty vec if the watcher was
    /// shut down (receiver disconnected).
    pub fn next_batch(&self, timeout: Duration) -> Option<Vec<FileChange>> {
        let rx = self.rx.lock().expect("watcher receiver mutex poisoned");
        match rx.recv_timeout(timeout) {
            Ok(batch) => Some(batch),
            Err(RecvTimeoutError::Timeout) => None,
            Err(RecvTimeoutError::Disconnected) => Some(Vec::new()),
        }
    }
}

fn classify(event: &notify::Event) -> Vec<FileChange> {
    let kind = match event.kind {
        EventKind::Create(_) => ChangeKind::Added,
        EventKind::Modify(modify) => match modify {
            notify::event::ModifyKind::Name(notify::event::RenameMode::To) => ChangeKind::Added,
            notify::event::ModifyKind::Name(notify::event::RenameMode::From) => ChangeKind::Removed,
            _ => ChangeKind::Modified,
        },
        EventKind::Remove(_) => ChangeKind::Removed,
        _ => return Vec::new(),
    };
    event
        .paths
        .iter()
        .map(|path| FileChange {
            kind,
            path: path.clone(),
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::io::Write;
    use std::time::Instant;

    const DEBOUNCE: Duration = Duration::from_millis(50);
    const RECV_TIMEOUT: Duration = Duration::from_secs(5);

    fn drain_until<F: Fn(&[FileChange]) -> bool>(
        watcher: &Watcher,
        deadline: Duration,
        predicate: F,
    ) -> Vec<FileChange> {
        let start = Instant::now();
        let mut all: Vec<FileChange> = Vec::new();
        while start.elapsed() < deadline {
            let remaining = deadline.saturating_sub(start.elapsed());
            match watcher.next_batch(remaining.min(Duration::from_millis(200))) {
                Some(batch) => {
                    all.extend(batch);
                    if predicate(&all) {
                        return all;
                    }
                }
                None => continue,
            }
        }
        all
    }

    #[test]
    fn detects_file_creation() {
        let dir = tempfile::tempdir().unwrap();
        let watcher = Watcher::start(dir.path(), DEBOUNCE).unwrap();
        std::thread::sleep(Duration::from_millis(100));

        let target = dir.path().join("new.txt");
        fs::write(&target, b"hello").unwrap();

        let events = drain_until(&watcher, RECV_TIMEOUT, |batch| {
            batch.iter().any(|c| c.path.ends_with("new.txt"))
        });
        assert!(
            events.iter().any(|c| c.path.ends_with("new.txt")),
            "expected a change for new.txt, got {events:?}"
        );
    }

    #[test]
    fn detects_file_modification() {
        let dir = tempfile::tempdir().unwrap();
        let target = dir.path().join("existing.txt");
        fs::write(&target, b"initial").unwrap();

        let watcher = Watcher::start(dir.path(), DEBOUNCE).unwrap();
        std::thread::sleep(Duration::from_millis(100));

        // Append rather than recreate so we exercise Modify rather than Create.
        let mut f = fs::OpenOptions::new().append(true).open(&target).unwrap();
        f.write_all(b" more").unwrap();
        drop(f);

        let events = drain_until(&watcher, RECV_TIMEOUT, |batch| {
            batch.iter().any(|c| c.path.ends_with("existing.txt"))
        });
        assert!(
            events.iter().any(|c| c.path.ends_with("existing.txt")),
            "expected a change for existing.txt, got {events:?}"
        );
    }

    #[test]
    fn detects_file_removal() {
        let dir = tempfile::tempdir().unwrap();
        let target = dir.path().join("gone.txt");
        fs::write(&target, b"bye").unwrap();

        let watcher = Watcher::start(dir.path(), DEBOUNCE).unwrap();
        std::thread::sleep(Duration::from_millis(100));

        fs::remove_file(&target).unwrap();

        let events = drain_until(&watcher, RECV_TIMEOUT, |batch| {
            batch
                .iter()
                .any(|c| c.kind == ChangeKind::Removed && c.path.ends_with("gone.txt"))
        });
        assert!(
            events
                .iter()
                .any(|c| c.kind == ChangeKind::Removed && c.path.ends_with("gone.txt")),
            "expected a Removed event for gone.txt, got {events:?}"
        );
    }

    #[test]
    fn times_out_with_no_events() {
        let dir = tempfile::tempdir().unwrap();
        let watcher = Watcher::start(dir.path(), DEBOUNCE).unwrap();
        let batch = watcher.next_batch(Duration::from_millis(150));
        assert!(batch.is_none(), "expected None, got {batch:?}");
    }

    #[test]
    fn errors_on_missing_root() {
        let dir = tempfile::tempdir().unwrap();
        let missing = dir.path().join("does-not-exist");
        let result = Watcher::start(&missing, DEBOUNCE);
        assert!(matches!(result, Err(WatchError::Start { .. })));
    }
}
