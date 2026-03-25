"""Shared test fixtures for sylvan tests."""

from __future__ import annotations

import os

import pytest

from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import run_migrations
from sylvan.database.orm.runtime.query_cache import QueryCache
from sylvan.session.tracker import SessionTracker


@pytest.fixture
async def backend(tmp_path):
    """Create an async SQLite backend for testing."""
    db_path = tmp_path / "test.db"
    backend = SQLiteBackend(db_path)
    await backend.connect()
    await run_migrations(backend)
    yield backend
    await backend.disconnect()


@pytest.fixture
async def ctx(backend):
    """Set up a SylvanContext with the test backend."""
    context = SylvanContext(
        backend=backend,
        session=SessionTracker(),
        cache=QueryCache(),
    )
    token = set_context(context)
    yield context
    reset_context(token)


@pytest.fixture
def tmp_sylvan_home(tmp_path):
    """Set SYLVAN_HOME to a temp directory for test isolation."""
    home = tmp_path / ".sylvan"
    home.mkdir()
    os.environ["SYLVAN_HOME"] = str(home)
    yield home
    os.environ.pop("SYLVAN_HOME", None)


@pytest.fixture
def sample_python_file(tmp_path):
    """Create a sample Python file for testing."""
    code = '''
"""Sample module for testing."""

MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30

class HttpClient:
    """An HTTP client for making requests."""

    def __init__(self, base_url: str, timeout: int = DEFAULT_TIMEOUT):
        self.base_url = base_url
        self.timeout = timeout

    def get(self, path: str, params: dict = None) -> dict:
        """Send a GET request."""
        pass

    def post(self, path: str, data: dict = None) -> dict:
        """Send a POST request."""
        pass

def create_client(base_url: str) -> HttpClient:
    """Factory function for creating HTTP clients."""
    return HttpClient(base_url)

@property
def _internal_helper():
    pass
'''
    f = tmp_path / "sample.py"
    f.write_text(code, encoding="utf-8")
    return f


@pytest.fixture
def sample_ts_file(tmp_path):
    """Create a sample TypeScript file for testing."""
    code = """
interface Config {
    apiUrl: string;
    timeout: number;
}

type RequestMethod = "GET" | "POST" | "PUT" | "DELETE";

class ApiClient {
    private config: Config;

    constructor(config: Config) {
        this.config = config;
    }

    async fetch(path: string, method: RequestMethod = "GET"): Promise<Response> {
        return fetch(`${this.config.apiUrl}${path}`, { method });
    }
}

export function createApiClient(config: Config): ApiClient {
    return new ApiClient(config);
}

export const DEFAULT_CONFIG: Config = {
    apiUrl: "https://api.example.com",
    timeout: 5000,
};
"""
    f = tmp_path / "api.ts"
    f.write_text(code, encoding="utf-8")
    return f


@pytest.fixture
def sample_go_file(tmp_path):
    """Create a sample Go file for testing."""
    code = """package main

import (
    "fmt"
    "net/http"
)

// Handler handles HTTP requests.
type Handler struct {
    prefix string
}

// ServeHTTP implements the http.Handler interface.
func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
    fmt.Fprintf(w, "Hello from %s", h.prefix)
}

// NewHandler creates a new Handler.
func NewHandler(prefix string) *Handler {
    return &Handler{prefix: prefix}
}

const MaxConnections = 100
"""
    f = tmp_path / "main.go"
    f.write_text(code, encoding="utf-8")
    return f


@pytest.fixture
def sample_project(tmp_path, sample_python_file, sample_ts_file, sample_go_file):
    """Create a multi-language sample project."""
    # Move files into a structured project
    src = tmp_path / "src"
    src.mkdir()

    (src / "client.py").write_text(sample_python_file.read_text(), encoding="utf-8")
    (src / "api.ts").write_text(sample_ts_file.read_text(), encoding="utf-8")
    (src / "main.go").write_text(sample_go_file.read_text(), encoding="utf-8")

    return tmp_path
