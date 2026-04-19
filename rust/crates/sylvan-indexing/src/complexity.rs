//! Per-symbol complexity metrics: cyclomatic complexity, max nesting
//! depth, parameter count.
//!
//! Port of `sylvan.indexing.source_code.complexity` from the Python
//! implementation. Language-specific decision patterns and receiver
//! stripping are hand-ported to the [`provider`] module; the per-symbol
//! pipeline below matches the Python behaviour step-for-step so
//! existing tests keep passing unmodified.

use fancy_regex::Regex;
use once_cell::sync::Lazy;

mod provider;

use provider::{Provider, for_language};

/// Computed complexity metrics for a symbol.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ComplexityMetrics {
    /// Cyclomatic complexity: 1 + decision-point count.
    pub cyclomatic: u32,
    /// Max nesting depth, measured from indentation or brace counting.
    pub max_nesting: u32,
    /// Number of top-level parameters (receiver parameters stripped).
    pub param_count: u32,
}

/// Compute all three metrics for a symbol's source body.
///
/// `language` is a canonical language identifier (e.g. `"python"`,
/// `"javascript"`, `"rust"`). Unknown identifiers fall back to a
/// generic decision pattern and indentation-based nesting.
pub fn compute_complexity(source: &str, language: &str) -> ComplexityMetrics {
    let provider = for_language(language);
    ComplexityMetrics {
        cyclomatic: cyclomatic(source, provider),
        max_nesting: max_nesting(source, provider),
        param_count: param_count(source, provider),
    }
}

static GENERIC_DECISION: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"\b(if|elif|for|while|case|catch|except)\b|&&|\|\||(?<!\w)and\b|(?<!\w)or\b")
        .expect("generic decision pattern compiles")
});

fn cyclomatic(source: &str, provider: Option<&Provider>) -> u32 {
    let clean = strip_noise(source, provider);
    let pattern: &Regex = match provider {
        Some(p) => p.decision_pattern(),
        None => &GENERIC_DECISION,
    };
    let mut count: u32 = 1;
    let mut cursor = 0usize;
    while cursor <= clean.len() {
        match pattern.find_from_pos(&clean, cursor) {
            Ok(Some(m)) => {
                count = count.saturating_add(1);
                // Always advance past the match so zero-width matches
                // cannot spin forever.
                cursor = m.end().max(cursor + 1);
            }
            _ => break,
        }
    }
    count
}

fn max_nesting(source: &str, provider: Option<&Provider>) -> u32 {
    if provider.map(Provider::uses_braces).unwrap_or(false) {
        brace_nesting(source)
    } else {
        indent_nesting(source)
    }
}

fn indent_nesting(source: &str) -> u32 {
    let mut base_indent: Option<u32> = None;
    let mut indent_step: Option<u32> = None;
    let mut max_depth: u32 = 0;

    for line in source.split('\n') {
        let stripped = line.trim_start();
        if stripped.is_empty() || stripped.starts_with('#') {
            continue;
        }

        let indent: u32 = if line.contains('\t') && !stripped.starts_with('\t') {
            let leading = &line[..line.len() - stripped.len()];
            leading.chars().filter(|&c| c == '\t').count() as u32
        } else {
            (line.len() - stripped.len()) as u32
        };

        let Some(base) = base_indent else {
            base_indent = Some(indent);
            continue;
        };

        if indent <= base {
            continue;
        }
        let relative = indent - base;

        if indent_step.is_none() {
            indent_step = Some(relative);
        }
        if let Some(step) = indent_step
            && step > 0
        {
            let depth = relative / step;
            if depth > max_depth {
                max_depth = depth;
            }
        }
    }

    max_depth
}

fn brace_nesting(source: &str) -> u32 {
    let mut depth: u32 = 0;
    let mut max_depth: u32 = 0;
    let mut in_string: Option<char> = None;
    let mut prev: char = '\0';

    for ch in source.chars() {
        match in_string {
            Some(quote) if ch == quote && prev != '\\' => in_string = None,
            Some(_) => {}
            None => match ch {
                '"' | '\'' | '`' => in_string = Some(ch),
                '{' => {
                    depth = depth.saturating_add(1);
                    if depth > max_depth {
                        max_depth = depth;
                    }
                }
                '}' => depth = depth.saturating_sub(1),
                _ => {}
            },
        }
        prev = ch;
    }

    max_depth.saturating_sub(1)
}

fn param_count(source: &str, provider: Option<&Provider>) -> u32 {
    let Some(first_paren) = source.find('(') else {
        return 0;
    };
    let mut depth: i32 = 0;
    let mut end: Option<usize> = None;
    for (i, ch) in source[first_paren..].char_indices() {
        match ch {
            '(' => depth += 1,
            ')' => {
                depth -= 1;
                if depth == 0 {
                    end = Some(first_paren + i);
                    break;
                }
            }
            _ => {}
        }
    }
    let Some(end) = end else {
        return 0;
    };

    let mut params_str = source[first_paren + 1..end].trim().to_string();
    if params_str.is_empty() {
        return 0;
    }
    if let Some(p) = provider {
        params_str = p.strip_receiver(&params_str);
        if params_str.is_empty() {
            return 0;
        }
    }

    split_top_level_commas(&params_str)
        .into_iter()
        .filter(|s| !s.trim().is_empty())
        .count() as u32
}

fn split_top_level_commas(input: &str) -> Vec<&str> {
    let mut parts: Vec<&str> = Vec::new();
    let bytes = input.as_bytes();
    let mut start = 0usize;
    let mut depth_paren: i32 = 0;
    let mut depth_bracket: i32 = 0;
    let mut depth_brace: i32 = 0;
    let mut depth_angle: i32 = 0;
    let mut i = 0usize;
    while i < bytes.len() {
        match bytes[i] {
            b'(' => depth_paren += 1,
            b')' => depth_paren -= 1,
            b'[' => depth_bracket += 1,
            b']' => depth_bracket -= 1,
            b'{' => depth_brace += 1,
            b'}' => depth_brace -= 1,
            b'<' => depth_angle += 1,
            b'>' => depth_angle -= 1,
            b',' if depth_paren == 0
                && depth_bracket == 0
                && depth_brace == 0
                && depth_angle == 0 =>
            {
                parts.push(&input[start..i]);
                start = i + 1;
            }
            _ => {}
        }
        i += 1;
    }
    parts.push(&input[start..]);
    parts
}

static LINE_COMMENT: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?m)//.*$|#.*$").expect("line comment regex compiles"));
static BLOCK_COMMENT: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?s)/\*.*?\*/").expect("block comment regex compiles"));
static PY_HASH_COMMENT: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?m)#.*$").expect("python hash-comment regex compiles"));
static TRIPLE_STRING: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"(?s)""".*?"""|'''.*?'''"#).expect("triple-quoted string regex compiles")
});
static DOUBLE_STRING: Lazy<Regex> =
    Lazy::new(|| Regex::new(r#""(?:[^"\\]|\\.)*""#).expect("double-string regex compiles"));
static SINGLE_STRING: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"'(?:[^'\\]|\\.)*'").expect("single-string regex compiles"));
static TEMPLATE_STRING: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"`(?:[^`\\]|\\.)*`").expect("template-string regex compiles"));

fn strip_noise(source: &str, provider: Option<&Provider>) -> String {
    let is_python = matches!(provider, Some(p) if p.is_python());
    let mut text: String = if is_python {
        let a = TRIPLE_STRING.replace_all(source, "");
        PY_HASH_COMMENT.replace_all(a.as_ref(), "").into_owned()
    } else {
        let a = BLOCK_COMMENT.replace_all(source, "");
        LINE_COMMENT.replace_all(a.as_ref(), "").into_owned()
    };
    text = DOUBLE_STRING.replace_all(&text, "\"\"").into_owned();
    text = SINGLE_STRING.replace_all(&text, "''").into_owned();
    text = TEMPLATE_STRING.replace_all(&text, "``").into_owned();
    text
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_source_has_baseline_cyclomatic() {
        assert_eq!(compute_complexity("", "python").cyclomatic, 1);
    }

    #[test]
    fn simple_python_function() {
        let source = "def hello():\n    return 1\n";
        let m = compute_complexity(source, "python");
        assert_eq!(m.cyclomatic, 1);
        assert!(m.max_nesting <= 1);
        assert_eq!(m.param_count, 0);
    }

    #[test]
    fn python_branches_counted() {
        let source = "def f(x):\n    if x:\n        for i in x:\n            if i:\n                pass\n            else:\n                pass\n";
        assert!(compute_complexity(source, "python").cyclomatic >= 3);
    }

    #[test]
    fn python_self_stripped() {
        let source = "def method(self, x, y):\n    pass\n";
        assert_eq!(compute_complexity(source, "python").param_count, 2);
    }

    #[test]
    fn python_cls_stripped() {
        let source = "def method(cls, x):\n    pass\n";
        assert_eq!(compute_complexity(source, "python").param_count, 1);
    }

    #[test]
    fn python_typed_params() {
        let source = "def func(a: int, b: str = 'hello') -> bool:\n    pass\n";
        assert_eq!(compute_complexity(source, "python").param_count, 2);
    }

    #[test]
    fn python_generic_params() {
        let source =
            "def func(items: list[dict[str, Any]], callback: Callable[[int], bool]):\n    pass\n";
        assert_eq!(compute_complexity(source, "python").param_count, 2);
    }

    #[test]
    fn javascript_brace_nesting() {
        let source = "function deep() {\n    if (true) {\n        for (let i = 0; i < 10; i++) {\n            if (i > 5) {\n                console.log(i);\n            }\n        }\n    }\n}";
        assert!(compute_complexity(source, "javascript").max_nesting >= 3);
    }

    #[test]
    fn javascript_ternary_counts() {
        // `cond ? a : b` has `?` followed by space (non-colon) and should
        // increment cyclomatic. `??` nullish likewise has its own branch.
        let source = "function f(x) { return x > 0 ? a : b; }";
        let m = compute_complexity(source, "javascript");
        assert!(m.cyclomatic >= 2, "expected ternary to count, got {m:?}");
    }

    #[test]
    fn rust_self_receiver_stripped() {
        let source = "fn m(&self, a: i32, b: i32) -> i32 { a + b }";
        assert_eq!(compute_complexity(source, "rust").param_count, 2);
    }

    #[test]
    fn rust_mut_self_stripped() {
        let source = "fn m(&mut self, a: i32) { a; }";
        assert_eq!(compute_complexity(source, "rust").param_count, 1);
    }

    #[test]
    fn unknown_language_falls_back_to_generic() {
        let m = compute_complexity("if x then y", "brainfuck");
        assert!(m.cyclomatic >= 1);
    }

    #[test]
    fn no_parens_gives_zero_params() {
        assert_eq!(compute_complexity("MAX = 3\n", "python").param_count, 0);
    }

    #[test]
    fn strip_noise_removes_python_comments() {
        let text = strip_noise(
            "x = 1  # comment\nif x:  # hit\n    y = 2\n",
            for_language("python"),
        );
        assert!(!text.contains("# comment"));
        assert!(!text.contains("# hit"));
    }

    #[test]
    fn strip_noise_removes_c_block_comment() {
        let text = strip_noise(
            "int x = 1; /* block\ncomment */ if (x) return;",
            for_language("c"),
        );
        assert!(!text.contains("block"));
        assert!(text.contains("if (x)"));
    }

    #[test]
    fn split_top_level_commas_respects_brackets() {
        assert_eq!(
            split_top_level_commas("a, b[c, d], e<f, g>, h"),
            vec!["a", " b[c, d]", " e<f, g>", " h"]
        );
    }

    #[test]
    fn brace_nesting_ignores_braces_inside_strings() {
        // Outer `fn f() { ... }` opens to depth 1, the inner `{ let x = 1; }`
        // bumps depth 2. Strings must be skipped: the `{{not real}}` inside
        // the string literal would otherwise push depth to 4+.
        let with_string = "fn f() { let s = \"{{not real}}\"; { let x = 1; } }";
        let without_string = "fn f() { { let x = 1; } }";
        assert_eq!(brace_nesting(with_string), brace_nesting(without_string));
    }
}
