"""Tests for context provider framework."""

from sylvan.providers.ecosystem_context.base import (
    FileContext,
    discover_providers,
)


class TestFileContext:
    def test_summary_context(self):
        fc = FileContext(description="A user table", tags=["core", "auth"], properties={"id": "primary key"})
        summary = fc.summary_context()
        assert "user table" in summary
        assert "core" in summary
        assert "primary key" in summary

    def test_search_keywords(self):
        fc = FileContext(tags=["api", "v2"], properties={"endpoint": "/users", "method": "GET"})
        kw = fc.search_keywords()
        assert "api" in kw
        assert "v2" in kw
        assert "endpoint" in kw
        assert "method" in kw

    def test_empty_context(self):
        fc = FileContext()
        assert fc.summary_context() == ""
        assert fc.search_keywords() == []


class TestDiscoverProviders:
    def test_no_providers_for_empty_dir(self, tmp_path):
        providers = discover_providers(tmp_path)
        # dbt provider won't detect without dbt_project.yml
        assert all(p.name != "dbt" or False for p in providers)

    def test_dbt_provider_detects(self, tmp_path):
        # Create a dbt project structure (dbt provider scans up to 2 levels deep)
        sub = tmp_path / "myproject"
        sub.mkdir()
        (sub / "dbt_project.yml").write_text("name: test\nmodel-paths: ['models']\n")
        (sub / "models").mkdir()

        providers = discover_providers(tmp_path)
        dbt_providers = [p for p in providers if p.name == "dbt"]
        assert len(dbt_providers) == 1
