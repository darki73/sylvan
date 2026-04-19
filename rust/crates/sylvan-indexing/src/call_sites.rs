//! Call-site extraction for indexed symbols.
//!
//! Port of `sylvan.indexing.source_code.call_extractor`. Currently
//! Python-only, mirroring the upstream behaviour (the Python version
//! `return []` for all other languages). Call-site extraction for
//! additional languages lands with Stage 2 extraction, where the
//! per-language AST knowledge is already present.

use tree_sitter::{Node, Parser};

/// A single function/method call discovered inside a caller symbol.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CallSite {
    /// Symbol ID of the enclosing function/method, or `"__module__"` for
    /// calls at module scope.
    pub caller_symbol_id: String,
    /// Callee name. Plain identifiers (`foo`), attribute chains
    /// (`self.bar`, `Module.baz`), and the leaf of a chained call
    /// (`Repo.where(x).first`) all show up here.
    pub callee_name: String,
    /// 1-based line number of the call.
    pub line: u32,
}

/// Input shape matching the enclosing-symbol data the caller already has.
///
/// Corresponds to the fields the Python walker pulled off the `Symbol`
/// dataclass. Only `function` and `method` kinds contribute enclosing
/// scopes; every other kind is filtered at the caller.
#[derive(Debug, Clone)]
pub struct SymbolRange {
    /// Stable symbol ID of the enclosing function/method.
    pub symbol_id: String,
    /// Byte offset of the symbol's body in the source.
    pub byte_offset: u32,
    /// Length of the symbol's body in bytes.
    pub byte_length: u32,
}

/// Walk a Python source string and return every call site.
///
/// `symbols` should already be filtered to `function`/`method` kinds by
/// the caller. Parse failures produce an empty vector, matching the
/// Python implementation's defensive behaviour.
pub fn extract_call_sites(symbols: &[SymbolRange], content: &str, language: &str) -> Vec<CallSite> {
    if language != "python" {
        return Vec::new();
    }

    let mut parser = Parser::new();
    if parser
        .set_language(&tree_sitter_python::LANGUAGE.into())
        .is_err()
    {
        return Vec::new();
    }
    let Some(tree) = parser.parse(content.as_bytes(), None) else {
        return Vec::new();
    };

    let mut ranges: Vec<&SymbolRange> = symbols.iter().collect();
    ranges.sort_by_key(|s| s.byte_offset);

    let bytes = content.as_bytes();
    let mut calls: Vec<CallSite> = Vec::new();

    for range in &ranges {
        let start = range.byte_offset as usize;
        let end = start + range.byte_length as usize;
        let Some(node) = find_node_at_range(tree.root_node(), start, end) else {
            continue;
        };
        walk_symbol(node, bytes, &range.symbol_id, &mut calls);
    }

    walk_module_level(tree.root_node(), bytes, &mut calls);

    calls
}

fn find_node_at_range(root: Node<'_>, start: usize, end: usize) -> Option<Node<'_>> {
    if root.start_byte() == start && root.end_byte() == end {
        return Some(root);
    }
    let mut cursor = root.walk();
    for child in root.children(&mut cursor) {
        if child.start_byte() <= start
            && child.end_byte() >= end
            && let Some(found) = find_node_at_range(child, start, end)
        {
            return Some(found);
        }
    }
    None
}

fn walk_symbol(node: Node<'_>, bytes: &[u8], symbol_id: &str, calls: &mut Vec<CallSite>) {
    if node.kind() == "call"
        && let Some(callee) = resolve_callee(node, bytes)
    {
        calls.push(CallSite {
            caller_symbol_id: symbol_id.to_string(),
            callee_name: callee,
            line: (node.start_position().row as u32) + 1,
        });
    }

    match node.kind() {
        "function_definition" => {
            // Continue walking the body but not the definition header;
            // nested function/class bodies belong to their own symbol.
            if let Some(body) = node.child_by_field_name("body") {
                let mut cursor = body.walk();
                for child in body.children(&mut cursor) {
                    walk_symbol(child, bytes, symbol_id, calls);
                }
            }
            return;
        }
        "class_definition" => {
            return;
        }
        _ => {}
    }

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        walk_symbol(child, bytes, symbol_id, calls);
    }
}

fn walk_module_level(root: Node<'_>, bytes: &[u8], calls: &mut Vec<CallSite>) {
    let module_id = "__module__";
    let mut cursor = root.walk();
    for child in root.children(&mut cursor) {
        if matches!(
            child.kind(),
            "function_definition" | "class_definition" | "decorated_definition"
        ) {
            continue;
        }
        walk_for_calls(child, bytes, module_id, calls);
    }
}

fn walk_for_calls(node: Node<'_>, bytes: &[u8], symbol_id: &str, calls: &mut Vec<CallSite>) {
    if node.kind() == "call"
        && let Some(callee) = resolve_callee(node, bytes)
    {
        calls.push(CallSite {
            caller_symbol_id: symbol_id.to_string(),
            callee_name: callee,
            line: (node.start_position().row as u32) + 1,
        });
    }

    if matches!(
        node.kind(),
        "function_definition" | "class_definition" | "decorated_definition"
    ) {
        return;
    }

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        walk_for_calls(child, bytes, symbol_id, calls);
    }
}

fn resolve_callee(call_node: Node<'_>, bytes: &[u8]) -> Option<String> {
    let func_node = call_node.child_by_field_name("function").or_else(|| {
        let mut cursor = call_node.walk();
        call_node
            .children(&mut cursor)
            .find(|c| c.kind() != "argument_list")
    })?;

    match func_node.kind() {
        "identifier" => func_node.utf8_text(bytes).ok().map(str::to_string),
        "attribute" => resolve_attribute_chain(func_node, bytes),
        _ => None,
    }
}

fn resolve_attribute_chain(attr_node: Node<'_>, bytes: &[u8]) -> Option<String> {
    let attr_name = attr_node.child_by_field_name("attribute")?;
    let obj = attr_node.child_by_field_name("object")?;
    let name = attr_name.utf8_text(bytes).ok()?;

    match obj.kind() {
        "identifier" => {
            let obj_text = obj.utf8_text(bytes).ok()?;
            Some(format!("{obj_text}.{name}"))
        }
        "attribute" => resolve_attribute_chain(obj, bytes).map(|parent| format!("{parent}.{name}")),
        "call" => Some(
            find_chain_root(obj, bytes)
                .map(|root| format!("{root}.{name}"))
                .unwrap_or_else(|| name.to_string()),
        ),
        _ => None,
    }
}

fn find_chain_root(node: Node<'_>, bytes: &[u8]) -> Option<String> {
    match node.kind() {
        "identifier" => node.utf8_text(bytes).ok().map(str::to_string),
        "attribute" => {
            let obj = node.child_by_field_name("object")?;
            find_chain_root(obj, bytes)
        }
        "call" => {
            let func = node.child_by_field_name("function")?;
            find_chain_root(func, bytes)
        }
        _ => None,
    }
}

/// Used by tests: produce `SymbolRange` entries from a Python source by
/// locating a named top-level function/method. The indexing pipeline
/// already has this metadata by the time it calls us; tests recreate it
/// the cheap way.
#[cfg(test)]
fn find_symbol_range(content: &str, name: &str, symbol_id: &str) -> Option<SymbolRange> {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_python::LANGUAGE.into())
        .ok()?;
    let tree = parser.parse(content.as_bytes(), None)?;
    find_named_function(tree.root_node(), content.as_bytes(), name).map(|node| SymbolRange {
        symbol_id: symbol_id.to_string(),
        byte_offset: node.start_byte() as u32,
        byte_length: (node.end_byte() - node.start_byte()) as u32,
    })
}

#[cfg(test)]
fn find_named_function<'a>(node: Node<'a>, bytes: &[u8], target: &str) -> Option<Node<'a>> {
    if node.kind() == "function_definition"
        && let Some(name) = node.child_by_field_name("name")
        && let Ok(text) = name.utf8_text(bytes)
        && text == target
    {
        return Some(node);
    }
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if let Some(found) = find_named_function(child, bytes, target) {
            return Some(found);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    fn call_names(calls: &[CallSite], caller: &str) -> Vec<String> {
        let mut names: Vec<String> = calls
            .iter()
            .filter(|c| c.caller_symbol_id == caller)
            .map(|c| c.callee_name.clone())
            .collect();
        names.sort();
        names
    }

    #[test]
    fn extracts_simple_call() {
        let src = "def a():\n    foo()\n";
        let range = find_symbol_range(src, "a", "repo::a").unwrap();
        let calls = extract_call_sites(&[range], src, "python");
        assert_eq!(call_names(&calls, "repo::a"), vec!["foo"]);
        assert_eq!(calls[0].line, 2);
    }

    #[test]
    fn extracts_attribute_access() {
        let src = "def a(self):\n    self.bar()\n    Module.baz()\n";
        let range = find_symbol_range(src, "a", "repo::a").unwrap();
        let calls = extract_call_sites(&[range], src, "python");
        assert_eq!(
            call_names(&calls, "repo::a"),
            vec!["Module.baz", "self.bar"]
        );
    }

    #[test]
    fn extracts_chained_call_leaf() {
        // `Repo.where(x).first()` — outer call resolves to `leaf = first`
        // via the chain root `Repo`, producing `Repo.first`. The inner
        // call `Repo.where` shows up as its own entry.
        let src = "def a():\n    Repo.where(x).first()\n";
        let range = find_symbol_range(src, "a", "repo::a").unwrap();
        let calls = extract_call_sites(&[range], src, "python");
        let names = call_names(&calls, "repo::a");
        assert!(names.contains(&"Repo.first".to_string()), "got {names:?}");
        assert!(names.contains(&"Repo.where".to_string()), "got {names:?}");
    }

    #[test]
    fn nested_function_body_attributed_to_outer() {
        // Matches the Python implementation: walking a function's body
        // descends into nested function definitions and attributes their
        // calls to the outer symbol. (The inner function also has its
        // own symbol entry, so those calls are duplicated by design;
        // the indexer deduplicates downstream.)
        let src = "def outer():\n    def inner():\n        inner_call()\n    outer_call()\n";
        let range = find_symbol_range(src, "outer", "repo::outer").unwrap();
        let calls = extract_call_sites(&[range], src, "python");
        assert_eq!(
            call_names(&calls, "repo::outer"),
            vec!["inner_call", "outer_call"]
        );
    }

    #[test]
    fn module_level_calls_captured() {
        let src = "startup()\n\ndef a():\n    in_func()\n\nteardown()\n";
        let range = find_symbol_range(src, "a", "repo::a").unwrap();
        let calls = extract_call_sites(&[range], src, "python");
        let module_calls = call_names(&calls, "__module__");
        assert_eq!(module_calls, vec!["startup", "teardown"]);
    }

    #[test]
    fn non_python_returns_empty() {
        let range = SymbolRange {
            symbol_id: "x".into(),
            byte_offset: 0,
            byte_length: 10,
        };
        assert!(extract_call_sites(&[range], "foo();", "c").is_empty());
    }

    #[test]
    fn empty_symbol_list_returns_only_module_calls() {
        let src = "init()\n";
        let calls = extract_call_sites(&[], src, "python");
        assert_eq!(call_names(&calls, "__module__"), vec!["init"]);
    }

    #[test]
    fn line_numbers_are_one_based() {
        let src = "\n\ndef a():\n    foo()\n";
        let range = find_symbol_range(src, "a", "repo::a").unwrap();
        let calls = extract_call_sites(&[range], src, "python");
        assert_eq!(calls[0].line, 4);
    }
}
