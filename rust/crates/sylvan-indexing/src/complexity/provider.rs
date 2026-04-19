//! Per-language complexity provider data.
//!
//! Hand-ported from `src/sylvan/indexing/languages/*.py`. Each entry
//! owns its decision pattern (compiled lazily), whether the language
//! uses braces for nesting, and a receiver-stripping function for the
//! parameter counter.

use fancy_regex::Regex;
use once_cell::sync::Lazy;

/// Language-specific complexity knowledge.
///
/// The three pieces (decision pattern, brace vs indent nesting, and
/// receiver stripping) are the whole surface. Adding a new language
/// means adding a single arm to [`for_language`].
pub struct Provider {
    name: LanguageName,
    pattern: &'static Lazy<Regex>,
    uses_braces: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum LanguageName {
    Python,
    Javascript,
    CFamily,
    Csharp,
    Go,
    Java,
    Php,
    Ruby,
    Rust,
    Swift,
}

impl Provider {
    /// Language-specific decision-point regex.
    pub fn decision_pattern(&self) -> &Regex {
        self.pattern
    }

    /// Whether nesting is counted via braces (`true`) or indentation
    /// (`false`).
    pub fn uses_braces(&self) -> bool {
        self.uses_braces
    }

    /// `true` for Python-family languages where `strip_noise` uses
    /// triple-quoted strings + `#` comments instead of `//` / `/* */`.
    pub fn is_python(&self) -> bool {
        matches!(self.name, LanguageName::Python)
    }

    /// Remove a leading self / cls / `&self` / similar receiver from
    /// `params_str` and return the remainder.
    pub fn strip_receiver(&self, params_str: &str) -> String {
        match self.name {
            LanguageName::Python => strip_python_receiver(params_str),
            LanguageName::Rust => strip_rust_receiver(params_str),
            _ => params_str.to_string(),
        }
    }
}

/// Resolve the provider for `language`, or `None` for unknown names.
pub fn for_language(language: &str) -> Option<&'static Provider> {
    match language.to_ascii_lowercase().as_str() {
        "python" => Some(&PYTHON),
        "javascript" | "typescript" | "tsx" | "jsx" | "mjs" | "vue" | "svelte" => Some(&JAVASCRIPT),
        "c" | "cpp" | "c++" | "h" | "hpp" => Some(&C_FAMILY),
        "csharp" | "cs" => Some(&CSHARP),
        "go" => Some(&GO),
        "java" | "kotlin" | "kt" => Some(&JAVA),
        "php" => Some(&PHP),
        "ruby" | "rb" => Some(&RUBY),
        "rust" | "rs" => Some(&RUST),
        "swift" => Some(&SWIFT),
        _ => None,
    }
}

fn strip_python_receiver(params: &str) -> String {
    if params == "self" || params == "cls" {
        return String::new();
    }
    for prefix in ["self,", "cls,"] {
        if let Some(rest) = params.strip_prefix(prefix) {
            return rest.trim().to_string();
        }
    }
    params.to_string()
}

fn strip_rust_receiver(params: &str) -> String {
    for prefix in ["&mut self,", "&self,", "mut self,", "self,"] {
        if let Some(rest) = params.strip_prefix(prefix) {
            return rest.trim().to_string();
        }
    }
    if matches!(params, "&self" | "&mut self" | "self" | "mut self") {
        return String::new();
    }
    params.to_string()
}

static PY_DECISION: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"\b(if|elif|for|while|except|and|or|assert)\b|\bif\s+.*\s+else\s+")
        .expect("python decision pattern compiles")
});
static JS_DECISION: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"\b(if|for|while|case|catch)\b|&&|\|\||\?\?|\?(?=[^:])")
        .expect("javascript decision pattern compiles")
});
static C_DECISION: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"\b(if|elif|for|while|case|catch|except)\b|&&|\|\||(?<!\w)and\b|(?<!\w)or\b")
        .expect("c-family decision pattern compiles")
});
static CSHARP_DECISION: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"\b(if|for|while|case|catch)\b|&&|\|\||\?(?=[^:])")
        .expect("csharp decision pattern compiles")
});
static GO_DECISION: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"\b(if|for|case|select)\b|&&|\|\|").expect("go decision pattern compiles")
});
static JAVA_DECISION: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"\b(if|for|while|case|catch)\b|&&|\|\||\?(?=[^:])")
        .expect("java decision pattern compiles")
});
static PHP_DECISION: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"\b(if|for|while|case|catch)\b|&&|\|\||\?(?=[^:])")
        .expect("php decision pattern compiles")
});
static RUBY_DECISION: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"\b(if|elif|for|while|except|and|or|assert)\b|\bif\s+.*\s+else\s+")
        .expect("ruby decision pattern compiles")
});
static RUST_DECISION: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"\b(if|for|while|loop|match)\b|=>").expect("rust decision pattern compiles")
});
static SWIFT_DECISION: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"\b(if|for|while|case|catch)\b|&&|\|\||\?(?=[^:])")
        .expect("swift decision pattern compiles")
});

static PYTHON: Provider = Provider {
    name: LanguageName::Python,
    pattern: &PY_DECISION,
    uses_braces: false,
};
static JAVASCRIPT: Provider = Provider {
    name: LanguageName::Javascript,
    pattern: &JS_DECISION,
    uses_braces: true,
};
static C_FAMILY: Provider = Provider {
    name: LanguageName::CFamily,
    pattern: &C_DECISION,
    uses_braces: true,
};
static CSHARP: Provider = Provider {
    name: LanguageName::Csharp,
    pattern: &CSHARP_DECISION,
    uses_braces: true,
};
static GO: Provider = Provider {
    name: LanguageName::Go,
    pattern: &GO_DECISION,
    uses_braces: true,
};
static JAVA: Provider = Provider {
    name: LanguageName::Java,
    pattern: &JAVA_DECISION,
    uses_braces: true,
};
static PHP: Provider = Provider {
    name: LanguageName::Php,
    pattern: &PHP_DECISION,
    uses_braces: true,
};
static RUBY: Provider = Provider {
    name: LanguageName::Ruby,
    pattern: &RUBY_DECISION,
    uses_braces: false,
};
static RUST: Provider = Provider {
    name: LanguageName::Rust,
    pattern: &RUST_DECISION,
    uses_braces: true,
};
static SWIFT: Provider = Provider {
    name: LanguageName::Swift,
    pattern: &SWIFT_DECISION,
    uses_braces: true,
};
