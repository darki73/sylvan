//! Integration test for [`sylvan_logging::init`]'s one-shot semantics.
//!
//! Runs in its own binary, so there is no interference with unit-test
//! threads that might install their own subscriber.

use sylvan_logging::{InitError, LoggingConfig, init};

#[test]
fn init_succeeds_once_then_reports_already_initialized() {
    let _guard = init(&LoggingConfig::default()).expect("first init must succeed");

    let err = init(&LoggingConfig::default())
        .map(|_| ())
        .expect_err("second init must fail");
    assert!(
        matches!(err, InitError::AlreadyInitialized),
        "expected AlreadyInitialized, got {err:?}",
    );
}
