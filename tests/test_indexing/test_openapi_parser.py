"""Tests for sylvan.indexing.documents.formats.openapi — OpenAPI/Swagger parsing."""

from __future__ import annotations

import json

from sylvan.indexing.documents.formats.openapi import (
    _render_parameters,
    _render_request_body,
    _render_responses,
    parse_openapi,
    sniff_openapi,
)


class TestSniffOpenapi:
    def test_yaml_openapi(self):
        assert sniff_openapi("openapi: 3.0.0\ninfo:\n  title: API", ".yaml") is True

    def test_yaml_swagger(self):
        assert sniff_openapi("swagger: '2.0'\ninfo:\n  title: API", ".yml") is True

    def test_yaml_not_openapi(self):
        assert sniff_openapi("name: my-config\nversion: 1", ".yaml") is False

    def test_json_openapi(self):
        spec = json.dumps({"openapi": "3.0.0", "info": {"title": "API"}})
        assert sniff_openapi(spec, ".json") is True

    def test_json_swagger(self):
        spec = json.dumps({"swagger": "2.0", "info": {"title": "API"}})
        assert sniff_openapi(spec, ".json") is True

    def test_json_not_openapi(self):
        spec = json.dumps({"name": "config", "version": 1})
        assert sniff_openapi(spec, ".json") is False

    def test_json_invalid(self):
        assert sniff_openapi("not json {{{", ".json") is False

    def test_unsupported_extension(self):
        assert sniff_openapi("openapi: 3.0.0", ".txt") is False

    def test_jsonc_extension(self):
        spec = json.dumps({"openapi": "3.1.0"})
        assert sniff_openapi(spec, ".jsonc") is True


class TestRenderParameters:
    def test_empty_params(self):
        assert _render_parameters([]) == ""

    def test_single_param(self):
        params = [{
            "name": "user_id",
            "in": "path",
            "required": True,
            "description": "The user ID",
            "schema": {"type": "integer"},
        }]
        result = _render_parameters(params)
        assert "user_id" in result
        assert "path" in result
        assert "required" in result
        assert "integer" in result
        assert "The user ID" in result

    def test_optional_param(self):
        params = [{"name": "page", "in": "query", "schema": {"type": "integer"}}]
        result = _render_parameters(params)
        assert "optional" in result

    def test_no_schema(self):
        params = [{"name": "x", "in": "query"}]
        result = _render_parameters(params)
        assert "x" in result


class TestRenderRequestBody:
    def test_none_body(self):
        assert _render_request_body(None) == ""

    def test_empty_body(self):
        assert _render_request_body({}) == ""

    def test_body_with_content(self):
        body = {
            "description": "User data",
            "content": {
                "application/json": {
                    "schema": {"type": "object"},
                },
            },
        }
        result = _render_request_body(body)
        assert "User data" in result
        assert "application/json" in result
        assert "object" in result


class TestRenderResponses:
    def test_empty_responses(self):
        assert _render_responses({}) == ""

    def test_responses_with_descriptions(self):
        responses = {
            "200": {"description": "Success"},
            "404": {"description": "Not found"},
        }
        result = _render_responses(responses)
        assert "200" in result
        assert "Success" in result
        assert "404" in result
        assert "Not found" in result


class TestParseOpenapi:
    def test_json_spec(self):
        spec = json.dumps({
            "openapi": "3.0.0",
            "info": {"title": "Pet Store", "version": "1.0.0", "description": "A pet store API"},
            "paths": {
                "/pets": {
                    "get": {
                        "tags": ["pets"],
                        "summary": "List all pets",
                        "operationId": "listPets",
                        "parameters": [
                            {"name": "limit", "in": "query", "schema": {"type": "integer"}},
                        ],
                        "responses": {
                            "200": {"description": "A list of pets"},
                        },
                    },
                    "post": {
                        "tags": ["pets"],
                        "summary": "Create a pet",
                        "responses": {
                            "201": {"description": "Created"},
                        },
                    },
                },
            },
        })
        sections = parse_openapi(spec, "api.json", "myrepo")

        assert len(sections) >= 3  # root + tag + 2 operations
        titles = [s.title for s in sections]
        assert "Pet Store" in titles
        assert "pets" in titles
        assert "GET /pets" in titles
        assert "POST /pets" in titles

    def test_yaml_spec(self):
        yaml_content = """\
openapi: "3.0.0"
info:
  title: My API
  version: "1.0"
paths:
  /users:
    get:
      tags:
        - users
      summary: Get users
      responses:
        "200":
          description: OK
"""
        sections = parse_openapi(yaml_content, "api.yaml", "myrepo")
        assert len(sections) >= 2
        titles = [s.title for s in sections]
        assert "My API" in titles
        assert "GET /users" in titles

    def test_empty_object_spec(self):
        # _load_spec returns {} which is falsy, so parse_openapi returns []
        spec = json.dumps({})
        sections = parse_openapi(spec, "empty.json", "myrepo")
        assert sections == []

    def test_spec_with_no_paths(self):
        spec = json.dumps({
            "openapi": "3.0.0",
            "info": {"title": "Empty API", "version": "1.0"},
        })
        sections = parse_openapi(spec, "api.json", "myrepo")
        # Root section only (no paths)
        assert len(sections) == 1
        assert sections[0].title == "Empty API"

    def test_multiple_tags(self):
        spec = json.dumps({
            "openapi": "3.0.0",
            "info": {"title": "API", "version": "1.0"},
            "paths": {
                "/users": {
                    "get": {
                        "tags": ["users"],
                        "summary": "List users",
                        "responses": {"200": {"description": "OK"}},
                    },
                },
                "/pets": {
                    "get": {
                        "tags": ["pets"],
                        "summary": "List pets",
                        "responses": {"200": {"description": "OK"}},
                    },
                },
            },
        })
        sections = parse_openapi(spec, "api.json", "myrepo")
        titles = [s.title for s in sections]
        assert "users" in titles
        assert "pets" in titles

    def test_untagged_operations(self):
        spec = json.dumps({
            "openapi": "3.0.0",
            "info": {"title": "API", "version": "1.0"},
            "paths": {
                "/health": {
                    "get": {
                        "summary": "Health check",
                        "responses": {"200": {"description": "OK"}},
                    },
                },
            },
        })
        sections = parse_openapi(spec, "api.json", "myrepo")
        titles = [s.title for s in sections]
        assert "Untagged" in titles

    def test_sections_have_hierarchy(self):
        spec = json.dumps({
            "openapi": "3.0.0",
            "info": {"title": "API", "version": "1.0"},
            "paths": {
                "/items": {
                    "get": {
                        "tags": ["items"],
                        "summary": "List",
                        "responses": {"200": {"description": "OK"}},
                    },
                },
            },
        })
        sections = parse_openapi(spec, "api.json", "myrepo")
        # Root is level 1, tag is level 2, operation is level 3
        levels = [s.level for s in sections]
        assert 1 in levels
        assert 2 in levels
        assert 3 in levels

    def test_sections_have_required_fields(self):
        spec = json.dumps({
            "openapi": "3.0.0",
            "info": {"title": "API", "version": "1.0"},
            "paths": {
                "/foo": {
                    "get": {
                        "tags": ["foo"],
                        "responses": {"200": {"description": "OK"}},
                    },
                },
            },
        })
        sections = parse_openapi(spec, "api.json", "myrepo")
        for s in sections:
            assert s.section_id is not None
            assert s.title is not None
            assert s.content_hash is not None
            assert s.byte_start is not None
            assert s.byte_end is not None
