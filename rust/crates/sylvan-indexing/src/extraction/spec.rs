//! Data-driven language extractor.
//!
//! Most tree-sitter languages follow the same extraction shape: look
//! for specific node types, pull the name out of a named field or a
//! known child kind, grab preceding comments as the docstring, recurse
//! into container nodes to pick up nested symbols. [`LanguageSpec`]
//! captures those per-language constants; [`SpecExtractor`] drives the
//! walk. A new simple language is usually a few lines of `&'static`
//! tables plus one registration call.
//!
//! Languages with extraction rules that do not fit this shape (JSON's
//! hand-rolled AST, CSS's `@import url(...)` handling) stay as bespoke
//! [`LanguageExtractor`] implementations. The spec extractor is an
//! opt-in convenience, not a hard abstraction.
//!
//! Mirrors `sylvan.indexing.source_code.extractor._walk_tree` plus
//! `sylvan.indexing.source_code.symbol_details.extract_name` from the
//! Python side, so spec dicts carry across unchanged.

use sylvan_core::{
    ExtractionContext, ExtractionError, LanguageExtractor, Symbol, make_symbol_id,
};
use tree_sitter::{Language, Node, Parser};

use crate::complexity::compute_complexity;
use crate::enrichment::{content_hash, disambiguate_overloads, extract_keywords, heuristic_summary};

/// Strategy for attaching a docstring to an extracted symbol.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DocstringStrategy {
    /// Collect contiguous comment siblings immediately preceding the
    /// symbol node. Used by C-family, Go, Rust, CSS, and most others.
    PrecedingComment,
    /// Treat the first string literal inside the body as the docstring.
    /// Used by Python, Julia, Elixir.
    NextSiblingString,
}

/// How a language attaches decorators/annotations/attributes to a
/// symbol declaration. Each variant is fully declarative so the walker
/// can discover decorators without per-language branching.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DecoratorStrategy {
    /// No decorator concept in the language.
    None,
    /// Decorators live inside an outer wrapper node that contains both
    /// the decorator children and the inner symbol (Python's
    /// `decorated_definition` holds `decorator` children plus a
    /// `function_definition` or `class_definition`).
    Wrapper {
        /// Wrapper node kind (e.g. `decorated_definition`).
        wrapper: &'static str,
        /// Child node kind that carries each decorator
        /// (e.g. `decorator`).
        child: &'static str,
    },
    /// Decorators appear as siblings immediately preceding the symbol
    /// inside the same parent block (TypeScript `decorator`,
    /// C# `attribute_list`).
    PrecedingSiblings {
        /// Sibling node kinds considered decorator-bearing.
        kinds: &'static [&'static str],
    },
    /// Decorators live inside a child of the symbol itself, typically
    /// a `modifiers` node that wraps `annotation` / `marker_annotation`
    /// (Java).
    InnerModifiers {
        /// Child node kind inside the symbol that holds the modifier
        /// list (e.g. `modifiers`).
        container: &'static str,
        /// Node kinds inside `container` treated as annotations.
        kinds: &'static [&'static str],
    },
}

/// How a language flags module-level named constants. Strategies name
/// the grammar shape explicitly so the walker never has to guess which
/// node layout a language uses.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConstantStrategy {
    /// Language does not emit module-level constants from the walker.
    None,
    /// Python: `expression_statement` containing an `assignment` whose
    /// left-hand identifier matches `UPPER_SNAKE_CASE`.
    PythonAssignment,
}

/// Per-language extraction configuration.
///
/// Fields are `&'static` slices so every spec is a const. Lookups are
/// linear, which is fine for the small (< 20) node-type tables that
/// real grammars produce; swapping to a perfect-hash map is a later
/// micro-optimisation if profiling shows it.
pub struct LanguageSpec {
    /// Map of tree-sitter node type to symbol kind string.
    pub symbol_node_types: &'static [(&'static str, &'static str)],
    /// Map of tree-sitter node type to the field name holding its
    /// symbol name. Nodes without an entry rely on the child-scan
    /// fallback and silently skip if that also returns nothing.
    pub name_fields: &'static [(&'static str, &'static str)],
    /// Map of tree-sitter node type to the field name holding its
    /// parameter list. Used to stitch the signature slice.
    pub param_fields: &'static [(&'static str, &'static str)],
    /// Map of tree-sitter node type to the field name holding its
    /// return-type annotation.
    pub return_type_fields: &'static [(&'static str, &'static str)],
    /// Node types whose children should be walked with this node as
    /// the parent symbol (classes, traits, interfaces, etc).
    pub container_node_types: &'static [&'static str],
    /// How to locate the docstring for extracted symbols.
    pub docstring_strategy: DocstringStrategy,
    /// How the language attaches decorators/annotations/attributes.
    pub decorator_strategy: DecoratorStrategy,
    /// How the language emits module-level constants, if at all.
    pub constant_strategy: ConstantStrategy,
    /// Tree-sitter node kinds considered a parameter when counting
    /// formal parameters under a `param_fields` node. Languages vary
    /// (Python: `typed_parameter`, Rust: `parameter`, Go:
    /// `parameter_declaration`, etc) so this is data rather than a
    /// hardcoded list on the walker.
    pub parameter_kinds: &'static [&'static str],
    /// Map of container kind (from `symbol_node_types`) to the kind
    /// that nested `function` symbols should be promoted to. Python
    /// uses `class` -> `method`; languages without class-method
    /// distinction leave this empty.
    pub method_promotion: &'static [(&'static str, &'static str)],
}

impl LanguageSpec {
    /// Symbol kind string for `node_type`, or `None` if not a symbol.
    pub fn kind_for(&self, node_type: &str) -> Option<&'static str> {
        self.symbol_node_types
            .iter()
            .find_map(|(k, v)| (*k == node_type).then_some(*v))
    }

    /// Configured name field for `node_type`, if any.
    pub fn name_field_for(&self, node_type: &str) -> Option<&'static str> {
        self.name_fields
            .iter()
            .find_map(|(k, v)| (*k == node_type).then_some(*v))
    }

    /// Whether `node_type` is a container whose children should see
    /// this node as their parent symbol.
    pub fn is_container(&self, node_type: &str) -> bool {
        self.container_node_types.contains(&node_type)
    }

    /// Configured parameter-list field for `node_type`, if any.
    pub fn param_field_for(&self, node_type: &str) -> Option<&'static str> {
        self.param_fields
            .iter()
            .find_map(|(k, v)| (*k == node_type).then_some(*v))
    }

    /// Configured return-type field for `node_type`, if any.
    pub fn return_type_field_for(&self, node_type: &str) -> Option<&'static str> {
        self.return_type_fields
            .iter()
            .find_map(|(k, v)| (*k == node_type).then_some(*v))
    }

    /// Whether `kind` is one of the configured parameter node kinds.
    pub fn is_parameter_kind(&self, kind: &str) -> bool {
        self.parameter_kinds.contains(&kind)
    }

    /// Promoted symbol kind when a `function`-kinded symbol is nested
    /// inside a container of kind `container_kind` (e.g. `class` ->
    /// `method` in Python).
    pub fn promoted_kind_for(&self, container_kind: &str) -> Option<&'static str> {
        self.method_promotion
            .iter()
            .find_map(|(k, v)| (*k == container_kind).then_some(*v))
    }
}

/// Language extractor driven entirely by a [`LanguageSpec`].
///
/// Advertises any number of language ids (useful when one grammar
/// covers multiple file extensions, e.g. `.sass` reusing SCSS).
pub struct SpecExtractor {
    language_ids: &'static [&'static str],
    ts_language: Language,
    spec: &'static LanguageSpec,
}

impl SpecExtractor {
    /// Build an extractor. `language_ids` must match the strings the
    /// pipeline sets on [`ExtractionContext::language`] for this
    /// grammar.
    pub fn new(
        language_ids: &'static [&'static str],
        ts_language: Language,
        spec: &'static LanguageSpec,
    ) -> Self {
        Self {
            language_ids,
            ts_language,
            spec,
        }
    }
}

impl LanguageExtractor for SpecExtractor {
    fn languages(&self) -> &'static [&'static str] {
        self.language_ids
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        if u32::try_from(ctx.source_bytes.len()).is_err() {
            return Err(ExtractionError::MissingDependency(format!(
                "{} source exceeds u32::MAX bytes: {}",
                ctx.language,
                ctx.source_bytes.len()
            )));
        }

        let mut parser = Parser::new();
        parser
            .set_language(&self.ts_language)
            .map_err(|err| ExtractionError::MissingDependency(err.to_string()))?;
        let Some(tree) = parser.parse(ctx.source_bytes, None) else {
            return Err(ExtractionError::MissingDependency(format!(
                "{} parser returned no tree",
                ctx.language
            )));
        };

        let mut out = Vec::new();
        let mut walker = Walker {
            spec: self.spec,
            source: ctx.source_bytes,
            filename: ctx.filename,
            language: ctx.language,
        };
        walker.walk(tree.root_node(), None, None, &[], &mut out);
        enrich_symbols(&mut out, ctx);
        disambiguate_overloads(&mut out);
        Ok(out)
    }
}

/// Fill in complexity, content_hash, summary, keywords on every symbol.
///
/// Kept at module scope instead of on `Walker` so future extractors
/// (bespoke ones like CSS / JSON) can reuse the same enrichment pass
/// without going through the spec walker.
pub fn enrich_symbols(symbols: &mut [Symbol], ctx: &ExtractionContext<'_>) {
    for sym in symbols.iter_mut() {
        let start = sym.byte_offset as usize;
        let end = start.saturating_add(sym.byte_length as usize);
        let body_bytes = ctx.source_bytes.get(start..end).unwrap_or(&[]);
        let body_text = std::str::from_utf8(body_bytes).unwrap_or("");

        let metrics = compute_complexity(body_text, ctx.language);
        sym.cyclomatic = metrics.cyclomatic;
        sym.max_nesting = metrics.max_nesting;
        if sym.param_count == 0 {
            sym.param_count = metrics.param_count;
        }
        sym.content_hash = Some(content_hash(body_bytes));
        let summary = heuristic_summary(sym.docstring.as_deref(), sym.signature.as_deref(), &sym.name);
        sym.summary = if summary.is_empty() { None } else { Some(summary) };
        sym.keywords = extract_keywords(&sym.name, sym.docstring.as_deref(), &sym.decorators);
    }
}

/// Internal view of a collected decorator before it is flattened into
/// the `Symbol.decorators: Vec<String>`. Carries byte/row positions so
/// the symbol range can expand to include decorators that precede the
/// declaration (mirrors Python's `decorator_node_start` expansion).
#[derive(Debug, Clone)]
struct Decorator {
    text: String,
    start_byte: usize,
    start_row: usize,
}

/// Where the walker should look for decorators when building a symbol.
///
/// For `Wrapper` languages (Python `decorated_definition`) the wrapper
/// node is the range anchor. For `PrecedingSiblings` / `InnerModifiers`
/// languages the symbol node itself is the anchor, and decorators are
/// discovered relative to it.
#[derive(Debug, Clone, Copy)]
enum DecoratorContext<'tree> {
    Wrapper(Node<'tree>),
    Symbol(Node<'tree>),
}

struct Walker<'a> {
    spec: &'a LanguageSpec,
    source: &'a [u8],
    filename: &'a str,
    language: &'a str,
}

impl<'a> Walker<'a> {
    fn walk(
        &mut self,
        node: Node<'_>,
        parent_symbol_id: Option<&str>,
        parent_kind: Option<&str>,
        scope: &[String],
        out: &mut Vec<Symbol>,
    ) {
        if node.is_error() {
            return;
        }

        if let DecoratorStrategy::Wrapper { wrapper, .. } = self.spec.decorator_strategy
            && wrapper == node.kind()
        {
            self.handle_decorated_wrapper(node, parent_symbol_id, parent_kind, scope, out);
            return;
        }

        if parent_symbol_id.is_none() {
            self.try_emit_constant(node, out);
        }

        let kind_str = self.spec.kind_for(node.kind());
        if let Some(raw_kind) = kind_str {
            let kind = self.resolve_kind(raw_kind, parent_kind);
            if let Some(sym) = self.build_symbol(
                node,
                DecoratorContext::Symbol(node),
                kind,
                parent_symbol_id,
                scope,
            ) {
                let is_container = self.spec.is_container(node.kind());
                let symbol_id = sym.symbol_id.clone();
                let name = sym.name.clone();
                out.push(sym);
                if is_container {
                    let mut next_scope: Vec<String> = scope.to_vec();
                    next_scope.push(name);
                    let mut cursor = node.walk();
                    for child in node.children(&mut cursor) {
                        self.walk(child, Some(&symbol_id), Some(kind), &next_scope, out);
                    }
                    return;
                }
            }
        }

        let mut cursor = node.walk();
        for child in node.children(&mut cursor) {
            self.walk(child, parent_symbol_id, parent_kind, scope, out);
        }
    }

    fn resolve_kind(&self, raw_kind: &'static str, parent_kind: Option<&str>) -> &'static str {
        if raw_kind == "function"
            && let Some(pk) = parent_kind
            && let Some(promoted) = self.spec.promoted_kind_for(pk)
        {
            return promoted;
        }
        raw_kind
    }

    fn handle_decorated_wrapper(
        &mut self,
        node: Node<'_>,
        parent_symbol_id: Option<&str>,
        parent_kind: Option<&str>,
        scope: &[String],
        out: &mut Vec<Symbol>,
    ) {
        let mut cursor = node.walk();
        for child in node.children(&mut cursor) {
            if let Some(raw_kind) = self.spec.kind_for(child.kind()) {
                let kind = self.resolve_kind(raw_kind, parent_kind);
                if let Some(sym) = self.build_symbol(
                    child,
                    DecoratorContext::Wrapper(node),
                    kind,
                    parent_symbol_id,
                    scope,
                ) {
                    let is_container = self.spec.is_container(child.kind());
                    let symbol_id = sym.symbol_id.clone();
                    let name = sym.name.clone();
                    out.push(sym);
                    if is_container {
                        let mut next_scope: Vec<String> = scope.to_vec();
                        next_scope.push(name);
                        let mut inner = child.walk();
                        for gc in child.children(&mut inner) {
                            self.walk(gc, Some(&symbol_id), Some(kind), &next_scope, out);
                        }
                    }
                    return;
                }
            }
        }
        let mut fallback = node.walk();
        for child in node.children(&mut fallback) {
            self.walk(child, parent_symbol_id, parent_kind, scope, out);
        }
    }

    fn try_emit_constant(&self, node: Node<'_>, out: &mut Vec<Symbol>) {
        match self.spec.constant_strategy {
            ConstantStrategy::None => {}
            ConstantStrategy::PythonAssignment => self.emit_python_constant(node, out),
        }
    }

    fn emit_python_constant(&self, node: Node<'_>, out: &mut Vec<Symbol>) {
        let assign = match node.kind() {
            "expression_statement" => {
                let mut cursor = node.walk();
                node.children(&mut cursor)
                    .find(|c| c.kind() == "assignment")
            }
            "assignment" => Some(node),
            _ => None,
        };
        let Some(assign) = assign else {
            return;
        };
        let Some(lhs) = assign.child_by_field_name("left") else {
            return;
        };
        if lhs.kind() != "identifier" {
            return;
        }
        let Some(name) = self.node_text(lhs).map(trim_string) else {
            return;
        };
        if name.is_empty() || !is_all_caps_constant(&name) {
            return;
        }
        let start = assign.start_byte();
        let end = assign.end_byte();
        if out
            .iter()
            .any(|s| s.kind == "constant" && s.name == name && s.byte_offset as usize == start)
        {
            return;
        }
        let Some(byte_offset) = u32::try_from(start).ok() else {
            return;
        };
        let Some(byte_length) = u32::try_from(end.saturating_sub(start)).ok() else {
            return;
        };
        let Some(line_start) = u32::try_from(assign.start_position().row).ok() else {
            return;
        };
        let Some(line_end) = u32::try_from(assign.end_position().row).ok() else {
            return;
        };
        out.push(Symbol {
            symbol_id: make_symbol_id(self.filename, &name, "constant"),
            name: name.clone(),
            qualified_name: name,
            kind: "constant".to_string(),
            language: self.language.to_string(),
            line_start: Some(line_start.saturating_add(1)),
            line_end: Some(line_end.saturating_add(1)),
            byte_offset,
            byte_length,
            ..Symbol::default()
        });
    }

    fn build_symbol(
        &self,
        node: Node<'_>,
        decorator_ctx: DecoratorContext<'_>,
        kind: &str,
        parent_symbol_id: Option<&str>,
        scope: &[String],
    ) -> Option<Symbol> {
        let name = self.extract_name(node)?;
        let qualified_name = if scope.is_empty() {
            name.clone()
        } else {
            let mut q = scope.join(".");
            q.push('.');
            q.push_str(&name);
            q
        };

        let decorators_full = self.collect_decorators(decorator_ctx);
        let (range_start, range_start_row) = match decorator_ctx {
            DecoratorContext::Wrapper(w) => (w.start_byte(), w.start_position().row),
            DecoratorContext::Symbol(_) => decorators_full
                .first()
                .map(|d| (d.start_byte, d.start_row))
                .unwrap_or_else(|| (node.start_byte(), node.start_position().row)),
        };
        let end = node.end_byte();
        let byte_offset = u32::try_from(range_start).ok()?;
        let byte_length = u32::try_from(end.saturating_sub(range_start)).ok()?;
        let line_start = u32::try_from(range_start_row)
            .ok()?
            .saturating_add(1);
        let decorators: Vec<String> =
            decorators_full.into_iter().map(|d| d.text).collect();
        let line_end = u32::try_from(node.end_position().row)
            .ok()?
            .saturating_add(1);

        let docstring = match self.spec.docstring_strategy {
            DocstringStrategy::PrecedingComment => self.preceding_comment(node),
            DocstringStrategy::NextSiblingString => self.next_sibling_string(node),
        };

        let signature = self.build_signature(node);
        let param_count = self
            .spec
            .param_field_for(node.kind())
            .and_then(|f| node.child_by_field_name(f))
            .map(|n| self.count_parameters(n))
            .unwrap_or(0);

        Some(Symbol {
            symbol_id: make_symbol_id(self.filename, &qualified_name, kind),
            name,
            qualified_name,
            kind: kind.to_string(),
            language: self.language.to_string(),
            parent_symbol_id: parent_symbol_id.map(str::to_string),
            line_start: Some(line_start),
            line_end: Some(line_end),
            byte_offset,
            byte_length,
            docstring,
            signature,
            decorators,
            param_count,
            ..Symbol::default()
        })
    }

    fn count_parameters(&self, params_node: Node<'_>) -> u32 {
        let mut count: u32 = 0;
        let mut cursor = params_node.walk();
        for child in params_node.children(&mut cursor) {
            if !child.is_named() {
                continue;
            }
            if self.spec.is_parameter_kind(child.kind()) {
                count = count.saturating_add(1);
            }
        }
        count
    }

    fn build_signature(&self, node: Node<'_>) -> Option<String> {
        let start = node.start_byte();
        let end = if let Some(body) = node.child_by_field_name("body") {
            body.start_byte()
        } else {
            let from = start.min(self.source.len());
            match self.source[from..].iter().position(|b| *b == b'\n') {
                Some(off) => from + off,
                None => node.end_byte(),
            }
        };
        if end <= start {
            return None;
        }
        let slice = self.source.get(start..end)?;
        let text = std::str::from_utf8(slice).ok()?;
        let mut sig = text.trim().to_string();
        while let Some(c) = sig.chars().last() {
            if matches!(c, ':' | '{' | ' ' | '\t' | '\n' | '\r') {
                sig.pop();
            } else {
                break;
            }
        }
        if sig.is_empty() { None } else { Some(sig) }
    }

    fn collect_decorators(&self, ctx: DecoratorContext<'_>) -> Vec<Decorator> {
        match (self.spec.decorator_strategy, ctx) {
            (DecoratorStrategy::None, _) => Vec::new(),
            (
                DecoratorStrategy::Wrapper { child, .. },
                DecoratorContext::Wrapper(wrapper),
            ) => self.decorators_from_children(wrapper, &[child]),
            (
                DecoratorStrategy::PrecedingSiblings { kinds },
                DecoratorContext::Symbol(node),
            ) => self.decorators_from_preceding_siblings(node, kinds),
            (
                DecoratorStrategy::InnerModifiers { container, kinds },
                DecoratorContext::Symbol(node),
            ) => self.decorators_from_inner(node, container, kinds),
            _ => Vec::new(),
        }
    }

    fn decorators_from_children(
        &self,
        parent: Node<'_>,
        kinds: &[&str],
    ) -> Vec<Decorator> {
        let mut out = Vec::new();
        let mut cursor = parent.walk();
        for child in parent.children(&mut cursor) {
            if !kinds.contains(&child.kind()) {
                continue;
            }
            if let Some(decorator) = self.decorator_from_node(child) {
                out.push(decorator);
            }
        }
        out
    }

    fn decorators_from_preceding_siblings(
        &self,
        node: Node<'_>,
        kinds: &[&str],
    ) -> Vec<Decorator> {
        let mut collected: Vec<Decorator> = Vec::new();
        let mut sibling = node.prev_sibling();
        while let Some(s) = sibling {
            if !kinds.contains(&s.kind()) {
                break;
            }
            if let Some(decorator) = self.decorator_from_node(s) {
                collected.push(decorator);
            }
            sibling = s.prev_sibling();
        }
        collected.reverse();
        collected
    }

    fn decorators_from_inner(
        &self,
        node: Node<'_>,
        container: &str,
        kinds: &[&str],
    ) -> Vec<Decorator> {
        let mut cursor = node.walk();
        let Some(modifier_node) = node
            .children(&mut cursor)
            .find(|c| c.kind() == container)
        else {
            return Vec::new();
        };
        self.decorators_from_children(modifier_node, kinds)
    }

    fn decorator_from_node(&self, node: Node<'_>) -> Option<Decorator> {
        let text = self.node_text(node)?;
        let trimmed = text.trim();
        if trimmed.is_empty() {
            return None;
        }
        Some(Decorator {
            text: trimmed.to_string(),
            start_byte: node.start_byte(),
            start_row: node.start_position().row,
        })
    }

    fn extract_name(&self, node: Node<'_>) -> Option<String> {
        if let Some(field) = self.spec.name_field_for(node.kind())
            && let Some(name_node) = node.child_by_field_name(field)
        {
            return self.node_text(name_node).map(trim_string);
        }
        if let Some(name) = self.scan_children_for_name(node) {
            return Some(name);
        }
        if let Some(decl) = node.child_by_field_name("declarator")
            && let Some(name) = self.declarator_identifier(decl)
        {
            return Some(name);
        }
        None
    }

    fn declarator_identifier(&self, node: Node<'_>) -> Option<String> {
        match node.kind() {
            "identifier" | "type_identifier" | "field_identifier" => {
                self.node_text(node).map(trim_string)
            }
            "function_declarator"
            | "pointer_declarator"
            | "reference_declarator"
            | "parenthesized_declarator"
            | "array_declarator"
            | "init_declarator" => {
                if let Some(inner) = node.child_by_field_name("declarator") {
                    return self.declarator_identifier(inner);
                }
                let mut cursor = node.walk();
                for child in node.children(&mut cursor) {
                    if let Some(found) = self.declarator_identifier(child) {
                        return Some(found);
                    }
                }
                None
            }
            _ => None,
        }
    }

    fn scan_children_for_name(&self, node: Node<'_>) -> Option<String> {
        let mut cursor = node.walk();
        for child in node.children(&mut cursor) {
            if matches!(
                child.kind(),
                "identifier"
                    | "type_identifier"
                    | "field_identifier"
                    | "property_identifier"
                    | "selectors"
                    | "class_selector"
                    | "id_selector"
                    | "tag_name"
                    | "keyframes_name"
                    | "keyword_query"
                    | "string_value"
                    | "word"
            ) {
                return self.node_text(child).map(trim_string);
            }
            if child.kind() == "call_expression" {
                let mut inner_cursor = child.walk();
                for inner in child.children(&mut inner_cursor) {
                    if inner.kind() == "arguments" {
                        let mut arg_cursor = inner.walk();
                        for arg in inner.children(&mut arg_cursor) {
                            if arg.kind() == "string_value" {
                                return self.node_text(arg).map(trim_string);
                            }
                        }
                    }
                }
            }
        }
        None
    }

    fn preceding_comment(&self, node: Node<'_>) -> Option<String> {
        let mut pieces: Vec<String> = Vec::new();
        let mut sibling = node.prev_sibling();
        while let Some(s) = sibling {
            if !is_comment_kind(s.kind()) {
                break;
            }
            if let Some(text) = self.node_text(s) {
                pieces.push(text);
            }
            sibling = s.prev_sibling();
        }
        if pieces.is_empty() {
            return None;
        }
        pieces.reverse();
        let joined = pieces
            .iter()
            .map(|s| strip_comment_syntax(s))
            .collect::<Vec<_>>()
            .join("\n");
        let trimmed = joined.trim();
        if trimmed.is_empty() {
            None
        } else {
            Some(trimmed.to_string())
        }
    }

    fn next_sibling_string(&self, node: Node<'_>) -> Option<String> {
        let body = node.child_by_field_name("body")?;
        let mut cursor = body.walk();
        let first = body.children(&mut cursor).next()?;
        let target = match first.kind() {
            "expression_statement" => first.child(0)?,
            _ => first,
        };
        if !matches!(target.kind(), "string" | "string_literal") {
            return None;
        }
        let text = self.node_text(target)?;
        Some(strip_string_quotes(&text))
    }

    fn node_text(&self, node: Node<'_>) -> Option<String> {
        let bytes = self.source.get(node.start_byte()..node.end_byte())?;
        Some(String::from_utf8_lossy(bytes).into_owned())
    }
}

fn trim_string(s: String) -> String {
    s.trim().to_string()
}

fn is_all_caps_constant(name: &str) -> bool {
    let mut has_letter = false;
    for c in name.chars() {
        if c.is_ascii_lowercase() {
            return false;
        }
        if c.is_ascii_alphabetic() {
            has_letter = true;
        } else if !(c.is_ascii_digit() || c == '_') {
            return false;
        }
    }
    has_letter
}

fn is_comment_kind(kind: &str) -> bool {
    matches!(kind, "comment" | "line_comment" | "block_comment")
}

fn strip_comment_syntax(raw: &str) -> String {
    let t = raw.trim();
    if let Some(rest) = t.strip_prefix("/**")
        && let Some(inner) = rest.strip_suffix("*/")
    {
        return inner
            .lines()
            .map(|l| l.trim().trim_start_matches('*').trim())
            .collect::<Vec<_>>()
            .join("\n")
            .trim()
            .to_string();
    }
    if let Some(rest) = t.strip_prefix("/*")
        && let Some(inner) = rest.strip_suffix("*/")
    {
        return inner
            .lines()
            .map(|l| l.trim().trim_start_matches('*').trim())
            .collect::<Vec<_>>()
            .join("\n")
            .trim()
            .to_string();
    }
    if let Some(rest) = t.strip_prefix("///") {
        return rest.trim().to_string();
    }
    if let Some(rest) = t.strip_prefix("//") {
        return rest.trim().to_string();
    }
    if let Some(rest) = t.strip_prefix('#') {
        return rest.trim().to_string();
    }
    if let Some(rest) = t.strip_prefix("--") {
        return rest.trim().to_string();
    }
    t.to_string()
}

fn strip_string_quotes(raw: &str) -> String {
    let t = raw.trim();
    for q in ["\"\"\"", "'''"] {
        if let Some(rest) = t.strip_prefix(q)
            && let Some(inner) = rest.strip_suffix(q)
        {
            return inner.trim().to_string();
        }
    }
    for q in ['"', '\''] {
        if t.starts_with(q) && t.ends_with(q) && t.len() >= 2 {
            return t[1..t.len() - 1].to_string();
        }
    }
    t.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strip_line_comment_removes_slashes() {
        assert_eq!(strip_comment_syntax("// hello"), "hello");
        assert_eq!(strip_comment_syntax("/// doc comment"), "doc comment");
    }

    #[test]
    fn strip_block_comment_trims_stars() {
        let raw = "/**\n * line one\n * line two\n */";
        let out = strip_comment_syntax(raw);
        assert!(out.contains("line one"));
        assert!(out.contains("line two"));
        assert!(!out.contains('*'));
    }

    #[test]
    fn strip_hash_comment_for_shells() {
        assert_eq!(strip_comment_syntax("# greet helper"), "greet helper");
    }

    #[test]
    fn strip_string_quotes_handles_triple_and_single() {
        assert_eq!(strip_string_quotes("\"hello\""), "hello");
        assert_eq!(strip_string_quotes("'hi'"), "hi");
        assert_eq!(strip_string_quotes("\"\"\"doc\"\"\""), "doc");
    }

    #[test]
    fn spec_lookup_helpers() {
        static SPEC: LanguageSpec = LanguageSpec {
            symbol_node_types: &[("function_definition", "function")],
            name_fields: &[("function_definition", "name")],
            param_fields: &[],
            return_type_fields: &[],
            container_node_types: &["class_definition"],
            docstring_strategy: DocstringStrategy::PrecedingComment,
            decorator_strategy: DecoratorStrategy::None,
            constant_strategy: ConstantStrategy::None,
            parameter_kinds: &[],
            method_promotion: &[],
        };
        assert_eq!(SPEC.kind_for("function_definition"), Some("function"));
        assert_eq!(SPEC.kind_for("nope"), None);
        assert_eq!(SPEC.name_field_for("function_definition"), Some("name"));
        assert!(SPEC.is_container("class_definition"));
        assert!(!SPEC.is_container("function_definition"));
    }
}
