"""Tests for sylvan.indexing.documents.formats.yaml_parser — YAML document parsing."""

from __future__ import annotations

from sylvan.indexing.documents.formats.yaml_parser import parse_yaml_doc


class TestParseYamlDoc:
    def test_simple_yaml(self):
        content = """\
name: my-project
version: 1.0
description: A sample project
"""
        sections = parse_yaml_doc(content, "config.yaml", "myrepo")
        assert len(sections) >= 1
        # Should produce sections from the JSON parser delegate
        for s in sections:
            assert s.section_id is not None
            assert s.title is not None

    def test_nested_yaml(self):
        content = """\
database:
  host: localhost
  port: 5432
  credentials:
    username: admin
    password: secret
server:
  port: 8080
  debug: true
"""
        sections = parse_yaml_doc(content, "config.yml", "myrepo")
        assert len(sections) >= 1

    def test_invalid_yaml_falls_back_to_text(self):
        content = "{{invalid: yaml: content: [["
        sections = parse_yaml_doc(content, "bad.yaml", "myrepo")
        # Should fall back to text parser and still return something
        assert len(sections) >= 1

    def test_non_dict_yaml_falls_back_to_text(self):
        content = "- item1\n- item2\n- item3\n"
        sections = parse_yaml_doc(content, "list.yaml", "myrepo")
        # A YAML list (not dict) falls back to text parser
        assert len(sections) >= 1

    def test_empty_yaml_falls_back_to_text(self):
        # Empty string YAML loads as None (not a dict), falls back to text parser
        # Text parser with empty content may return empty list
        content = ""
        sections = parse_yaml_doc(content, "empty.yaml", "myrepo")
        # Either empty or text-parsed sections are acceptable
        assert isinstance(sections, list)

    def test_yaml_with_multiline_strings(self):
        content = """\
readme: |
  This is a long
  multiline description
  of the project.
license: MIT
"""
        sections = parse_yaml_doc(content, "meta.yaml", "myrepo")
        assert len(sections) >= 1

    def test_sections_have_section_ids(self):
        content = "key: value\n"
        sections = parse_yaml_doc(content, "simple.yaml", "myrepo")
        for s in sections:
            assert "myrepo" in s.section_id
