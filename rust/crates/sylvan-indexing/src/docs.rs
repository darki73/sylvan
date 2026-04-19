//! Markdown / MDX document parser.
//!
//! Replaces `sylvan.indexing.documents.formats.markdown`. Goes through
//! `pulldown-cmark` so fenced code, inline HTML, and nested structures
//! are handled by a real CommonMark parser instead of the hand-rolled
//! regex scan. The old `_strip_mdx` helper's JSX-block regex eats ~50%
//! of content on standard `.md` files in large docs sets
//! (e.g. transformers' `docs/source/`); pulldown-cmark does not.

use fancy_regex::Regex;
use once_cell::sync::Lazy;
use pulldown_cmark::{Event, Parser, Tag, TagEnd};

/// A single section emitted by [`parse_markdown`].
///
/// Byte offsets reference the CLEANED content (post-`strip_mdx`), not
/// the raw input. Consumers that need offsets into the raw content must
/// run strip_mdx themselves and remap.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParsedSection {
    /// Heading text, or `"(root)"` for preamble before the first heading.
    pub title: String,
    /// Heading level. `0` for the `(root)` pseudo-section, otherwise 1-6.
    pub level: u8,
    /// 0-based line index of the heading in the cleaned content.
    pub start_line: usize,
    /// 0-based line index one past the end of this section.
    pub end_line: usize,
    /// Byte offset of the section's first line in the cleaned content.
    pub byte_start: usize,
    /// Byte offset one past the section's last line in the cleaned content.
    pub byte_end: usize,
    /// The section body text (heading line included), as used for
    /// content hashing and tag / reference extraction downstream.
    pub body: String,
}

/// Parse `raw` (.md / .mdx) and return the section list.
///
/// Goes through [`strip_mdx`] first, then walks `pulldown-cmark` events
/// to collect heading positions, then materialises per-section byte
/// ranges and body text. When content precedes the first heading a
/// synthetic `(root)` section is emitted, matching the Python contract.
pub fn parse_markdown(raw: &str) -> Vec<ParsedSection> {
    let cleaned = strip_mdx(raw);
    let lines: Vec<&str> = cleaned.split('\n').collect();

    let line_offsets = compute_line_offsets(&cleaned, &lines);

    let mut headings: Vec<Heading> = Vec::new();
    let mut current: Option<(u8, usize, String)> = None;
    let parser = Parser::new(&cleaned);
    for (event, range) in parser.into_offset_iter() {
        match event {
            Event::Start(Tag::Heading { level, .. }) => {
                let line_idx = offset_to_line(range.start, &line_offsets);
                current = Some((level as u8, line_idx, String::new()));
            }
            Event::End(TagEnd::Heading(_)) => {
                if let Some((level, line_idx, title)) = current.take() {
                    headings.push(Heading {
                        level,
                        line_idx,
                        title,
                    });
                }
            }
            Event::Text(text) => {
                if let Some((_, _, buf)) = current.as_mut() {
                    buf.push_str(&text);
                }
            }
            Event::Code(text) => {
                if let Some((_, _, buf)) = current.as_mut() {
                    buf.push_str(&text);
                }
            }
            _ => {}
        }
    }

    let first_heading_line = headings.first().map(|h| h.line_idx).unwrap_or(lines.len());
    let cleaned_len = cleaned.len();

    let mut sections: Vec<ParsedSection> = Vec::new();

    let preamble_body = lines[..first_heading_line].join("\n");
    if !preamble_body.trim().is_empty() {
        let byte_end = line_offsets
            .get(first_heading_line)
            .copied()
            .unwrap_or(cleaned_len);
        sections.push(ParsedSection {
            title: "(root)".to_string(),
            level: 0,
            start_line: 0,
            end_line: first_heading_line,
            byte_start: 0,
            byte_end,
            body: preamble_body,
        });
    }

    for (i, heading) in headings.iter().enumerate() {
        let next_line = headings
            .get(i + 1)
            .map(|h| h.line_idx)
            .unwrap_or(lines.len());
        let byte_start = line_offsets
            .get(heading.line_idx)
            .copied()
            .unwrap_or(cleaned_len);
        let byte_end = line_offsets.get(next_line).copied().unwrap_or(cleaned_len);
        let body = lines[heading.line_idx..next_line].join("\n");
        sections.push(ParsedSection {
            title: heading.title.trim().to_string(),
            level: heading.level,
            start_line: heading.line_idx,
            end_line: next_line,
            byte_start,
            byte_end,
            body,
        });
    }

    sections
}

struct Heading {
    level: u8,
    line_idx: usize,
    title: String,
}

/// Compute the byte offset of each line start, plus a sentinel at the
/// end equal to the total content length.
fn compute_line_offsets(cleaned: &str, lines: &[&str]) -> Vec<usize> {
    let mut offsets: Vec<usize> = Vec::with_capacity(lines.len() + 1);
    let mut cursor = 0usize;
    for line in lines {
        offsets.push(cursor);
        cursor += line.len() + 1; // +1 for the '\n' separator
    }
    offsets.push(cleaned.len());
    offsets
}

/// Map a byte offset into the cleaned content to a 0-based line index.
fn offset_to_line(byte_offset: usize, line_offsets: &[usize]) -> usize {
    // Line offsets are sorted; find the last line start <= byte_offset.
    match line_offsets.binary_search(&byte_offset) {
        Ok(idx) => idx,
        Err(idx) => idx.saturating_sub(1),
    }
}

static FRONTMATTER: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?s)\A---\s*\n.*?\n---\s*\n").expect("frontmatter regex compiles"));
static IMPORT_LINE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?m)^import\s+.*$").expect("import regex compiles"));
static EXPORT_LINE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?m)^export\s+.*$").expect("export regex compiles"));

/// Strip MDX constructs the markdown parser should not see.
///
/// Specifically: leading YAML frontmatter and top-level `import` /
/// `export` statements. Unlike the Python predecessor this function
/// does NOT attempt to strip JSX blocks — those are inline HTML and
/// pulldown-cmark already declines to emit heading events inside them,
/// so the old JSX regex was both unnecessary and buggy.
pub fn strip_mdx(content: &str) -> String {
    let no_frontmatter = FRONTMATTER.replace(content, "").into_owned();
    let no_imports = IMPORT_LINE.replace_all(&no_frontmatter, "").into_owned();
    EXPORT_LINE.replace_all(&no_imports, "").into_owned()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn titles(sections: &[ParsedSection]) -> Vec<&str> {
        sections.iter().map(|s| s.title.as_str()).collect()
    }

    #[test]
    fn atx_headings_extracted() {
        let md = "# Title\nSome content\n## Subtitle\nMore content\n";
        let sections = parse_markdown(md);
        assert_eq!(titles(&sections), vec!["Title", "Subtitle"]);
    }

    #[test]
    fn heading_levels_preserved() {
        let md = "# H1\n## H2\n### H3\n";
        let sections = parse_markdown(md);
        let levels: Vec<u8> = sections.iter().map(|s| s.level).collect();
        assert_eq!(levels, vec![1, 2, 3]);
    }

    #[test]
    fn preamble_produces_root_section() {
        let md = "Preamble text\n\n# Heading\nBody\n";
        let sections = parse_markdown(md);
        assert_eq!(sections[0].title, "(root)");
        assert_eq!(sections[0].level, 0);
    }

    #[test]
    fn no_headings_just_preamble() {
        let md = "Just some text without headings.\n";
        let sections = parse_markdown(md);
        assert_eq!(sections.len(), 1);
        assert_eq!(sections[0].title, "(root)");
    }

    #[test]
    fn byte_offsets_non_negative_and_ordered() {
        let md = "# First\nContent\n## Second\nMore\n";
        let sections = parse_markdown(md);
        for s in &sections {
            assert!(s.byte_end >= s.byte_start, "bad range on {s:?}");
        }
    }

    #[test]
    fn setext_headings_extracted() {
        let md = "Title\n=====\nContent\n";
        let sections = parse_markdown(md);
        assert_eq!(
            sections
                .iter()
                .find(|s| s.title == "Title")
                .map(|s| s.level),
            Some(1)
        );
    }

    #[test]
    fn fenced_code_headings_ignored() {
        let md = "# Real\n```\n## Fake\n```\n## Real2\n";
        let sections = parse_markdown(md);
        let ts = titles(&sections);
        assert!(ts.contains(&"Real"));
        assert!(ts.contains(&"Real2"));
        assert!(!ts.contains(&"Fake"));
    }

    #[test]
    fn frontmatter_stripped() {
        let md = "---\ntitle: Test\n---\n# Heading\nContent\n";
        let sections = parse_markdown(md);
        assert!(titles(&sections).contains(&"Heading"));
    }

    #[test]
    fn mdx_imports_stripped() {
        let md = "import X from 'y'\n\n# Heading\nContent\n";
        let sections = parse_markdown(md);
        assert!(titles(&sections).contains(&"Heading"));
    }

    #[test]
    fn mdx_exports_stripped() {
        let md = "export const x = 1\n\n# Heading\n";
        let sections = parse_markdown(md);
        assert!(titles(&sections).contains(&"Heading"));
    }

    #[test]
    fn bodies_include_heading_line() {
        let md = "# Heading\nBody text\n## Next\n";
        let sections = parse_markdown(md);
        let first = sections.iter().find(|s| s.title == "Heading").unwrap();
        assert!(first.body.contains("# Heading"));
        assert!(first.body.contains("Body text"));
    }

    #[test]
    fn heading_through_components_still_found() {
        // The Python `_strip_mdx` regex sucks characters out of real
        // .md files by greedily matching capitalised-tag spans across
        // unrelated headings. pulldown-cmark treats the component as
        // inline HTML and still finds the later heading cleanly.
        let md = "<Tip>\nSome prose.\n</Tip>\n\n# Real Heading\n\nBody.\n";
        let sections = parse_markdown(md);
        assert!(titles(&sections).contains(&"Real Heading"));
    }

    #[test]
    fn offset_to_line_binary_search() {
        let offsets = vec![0, 10, 20, 30];
        assert_eq!(offset_to_line(0, &offsets), 0);
        assert_eq!(offset_to_line(5, &offsets), 0);
        assert_eq!(offset_to_line(10, &offsets), 1);
        assert_eq!(offset_to_line(25, &offsets), 2);
    }
}
