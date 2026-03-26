"""Kubernetes YAML parser -- extracts k8s resources as symbols.

Detects k8s YAML files (apiVersion + kind), extracts resources as
first-class symbols with cross-references. Delegates to kind-specific
modules for signature enrichment.
"""

from __future__ import annotations

from typing import Any

# Registry of kind-specific handlers: {kind: handler_func}
_kind_handlers: dict[str, Any] = {}


def register_kind_handler(kind: str):
    """Register a kind-specific signature enrichment handler."""

    def decorator(func):
        _kind_handlers[kind] = func
        return func

    return decorator


def get_kind_handler(kind: str):
    """Get the handler for a specific k8s kind, or None."""
    return _kind_handlers.get(kind)


# Symbol kind mapping: k8s kind -> sylvan symbol kind
KIND_TO_SYMBOL_KIND: dict[str, str] = {
    # Workloads -> class
    "Deployment": "class",
    "StatefulSet": "class",
    "DaemonSet": "class",
    "ReplicaSet": "class",
    "Job": "class",
    "CronJob": "class",
    "Pod": "class",
    # Networking -> class
    "Service": "class",
    "Ingress": "class",
    "IngressClass": "class",
    "NetworkPolicy": "class",
    # Config -> constant
    "ConfigMap": "constant",
    "Secret": "constant",
    "Namespace": "constant",
    "ExternalSecret": "constant",
    "Kustomization": "constant",
    # Storage -> constant
    "PersistentVolumeClaim": "constant",
    "PersistentVolume": "constant",
    "StorageClass": "constant",
    # RBAC -> constant
    "ServiceAccount": "constant",
    "Role": "constant",
    "ClusterRole": "constant",
    "RoleBinding": "constant",
    "ClusterRoleBinding": "constant",
    # Policy -> constant
    "HorizontalPodAutoscaler": "constant",
    "PodDisruptionBudget": "constant",
    "LimitRange": "constant",
    "ResourceQuota": "constant",
    "PriorityClass": "constant",
    "RuntimeClass": "constant",
    # CRDs -> type
    "CustomResourceDefinition": "type",
    "APIService": "type",
}


def is_k8s_yaml(content: str) -> bool:
    """Quick check if YAML content looks like a k8s resource.

    Checks for apiVersion + kind without full YAML parsing.
    Rejects Helm templates (contains {{ }}).
    """
    if "{{" in content:
        return False
    has_api = False
    has_kind = False
    for line in content.split("\n")[:30]:
        stripped = line.strip()
        if stripped.startswith("apiVersion:"):
            has_api = True
        elif stripped.startswith("kind:"):
            has_kind = True
        if has_api and has_kind:
            return True
    return False


def parse_k8s_resource(doc: dict, file_path: str, byte_offset: int = 0) -> dict | None:
    """Extract a single k8s resource as a symbol dict.

    Args:
        doc: Parsed YAML document.
        file_path: Relative file path.
        byte_offset: Byte offset of this document in the file.

    Returns:
        Symbol dict or None if not a valid k8s resource.
    """
    api_version = doc.get("apiVersion", "")
    kind = doc.get("kind", "")
    metadata = doc.get("metadata", {})
    spec = doc.get("spec", {})

    if not kind or not metadata:
        return None

    name = metadata.get("name", "")
    namespace = metadata.get("namespace", "")
    labels = metadata.get("labels", {})
    annotations = metadata.get("annotations", {})

    # Build base signature
    sig_parts = [f"{kind}/{name}"]
    if namespace:
        sig_parts.append(f"namespace={namespace}")
    if api_version:
        sig_parts.append(f"apiVersion={api_version}")

    # Kind-specific enrichment
    handler = get_kind_handler(kind)
    if handler:
        extra = handler(doc, metadata, spec)
        if extra.get("sig_parts"):
            sig_parts.extend(extra["sig_parts"])

    signature = " ".join(sig_parts)

    # Docstring from labels and annotations
    doc_parts = []
    if labels:
        doc_parts.append(f"labels: {', '.join(f'{k}={v}' for k, v in labels.items())}")
    if annotations:
        ann_strs = []
        for k, v in annotations.items():
            v_short = str(v)[:50] + "..." if len(str(v)) > 50 else str(v)
            ann_strs.append(f"{k}={v_short}")
        doc_parts.append(f"annotations: {', '.join(ann_strs)}")
    docstring = "\n".join(doc_parts)

    # Cross-references
    references = []
    if handler:
        extra = handler(doc, metadata, spec)
        references = extra.get("references", [])

    # Strip secret values
    source_doc = doc
    if kind == "Secret":
        source_doc = _strip_secret_values(doc)

    # Symbol kind
    symbol_kind = KIND_TO_SYMBOL_KIND.get(kind, "constant")

    # Symbol ID with namespace scoping
    ns_suffix = f"@{namespace}" if namespace else ""
    symbol_id = f"{file_path}::{kind}/{name}{ns_suffix}#{symbol_kind}"

    return {
        "symbol_id": symbol_id,
        "name": name,
        "qualified_name": f"{kind}/{name}",
        "kind": symbol_kind,
        "language": "kubernetes",
        "signature": signature,
        "docstring": docstring,
        "references": references,
        "byte_offset": byte_offset,
        "source_doc": source_doc,
        "k8s_kind": kind,
        "k8s_namespace": namespace,
        "k8s_api_version": api_version,
    }


def parse_k8s_file(content: str, file_path: str) -> list[dict]:
    """Parse a YAML file containing one or more k8s resources.

    Handles multi-document YAML (--- separators).

    Args:
        content: Raw YAML content.
        file_path: Relative file path.

    Returns:
        List of symbol dicts.
    """
    try:
        import yaml
    except ImportError:
        return []

    try:
        docs = list(yaml.safe_load_all(content))
    except Exception:
        return []

    results = []
    # Track byte offsets for each document
    byte_offset = 0
    doc_texts = content.split("\n---")

    for i, doc in enumerate(docs):
        if doc is None or not isinstance(doc, dict):
            if i < len(doc_texts):
                byte_offset += len(doc_texts[i].encode("utf-8")) + 4  # +4 for \n---
            continue

        if "apiVersion" not in doc or "kind" not in doc:
            if i < len(doc_texts):
                byte_offset += len(doc_texts[i].encode("utf-8")) + 4
            continue

        result = parse_k8s_resource(doc, file_path, byte_offset)
        if result:
            results.append(result)

        if i < len(doc_texts):
            byte_offset += len(doc_texts[i].encode("utf-8")) + 4

    return results


def _strip_secret_values(doc: dict) -> dict:
    """Remove actual secret values from a Secret resource.

    Keeps key names for searchability, strips values.
    """
    import copy

    stripped = copy.deepcopy(doc)

    if "data" in stripped:
        stripped["data"] = {k: "<redacted>" for k in stripped["data"]}
    if "stringData" in stripped:
        stripped["stringData"] = {k: "<redacted>" for k in stripped["stringData"]}

    return stripped


async def store_k8s_symbols(
    file_id: int,
    file_path: str,
    content: str,
    result: Any,
) -> None:
    """Parse k8s YAML and store resources as symbols with cross-references.

    Args:
        file_id: Database ID of the file.
        file_path: Relative file path.
        content: Raw YAML content.
        result: IndexResult accumulator.
    """
    import json

    from sylvan.database.orm import FileImport, Symbol
    from sylvan.indexing.source_code.extractor import compute_content_hash

    resources = parse_k8s_file(content, file_path)

    for r in resources:
        source_yaml = json.dumps(r["source_doc"], indent=2, ensure_ascii=False, default=str)
        source_bytes = source_yaml.encode("utf-8")

        await Symbol.upsert(
            conflict_columns=["symbol_id"],
            update_columns=[
                "file_id",
                "name",
                "qualified_name",
                "kind",
                "language",
                "signature",
                "docstring",
                "summary",
                "decorators",
                "keywords",
                "line_start",
                "line_end",
                "byte_offset",
                "byte_length",
                "content_hash",
            ],
            file_id=file_id,
            symbol_id=r["symbol_id"],
            name=r["name"],
            qualified_name=r["qualified_name"],
            kind=r["kind"],
            language=r["language"],
            signature=r["signature"],
            docstring=r["docstring"],
            summary=f"{r['k8s_kind']} in {r.get('k8s_namespace', 'default')} namespace",
            decorators=[],
            keywords=[r["k8s_kind"], r["k8s_api_version"], r.get("k8s_namespace", "")],
            line_start=1,
            line_end=None,
            byte_offset=r["byte_offset"],
            byte_length=len(source_bytes),
            content_hash=compute_content_hash(source_bytes),
        )
        result.symbols_extracted += 1

        # Store cross-references as imports
        for ref in r.get("references", []):
            await FileImport.create(
                file_id=file_id,
                specifier=ref,
                names=[r["name"]],
            )
            result.imports_extracted += 1


def _k8s_sniffer(file_path: str, content: str) -> bool:
    """Content sniffer for k8s YAML files."""
    if not file_path.endswith((".yaml", ".yml")):
        return False
    return is_k8s_yaml(content)


# Import kind handlers to trigger registration
# Import ecosystem handlers
import contextlib

from sylvan.extensions.native.kubernetes import (  # noqa: F401
    config,
    networking,
    policy,
    rbac,
    storage,
    workloads,
)

with contextlib.suppress(Exception):
    from sylvan.extensions.native import kubernetes_ecosystem  # noqa: F401

# Register content handler
from sylvan.extensions import register_content_handler

register_content_handler(
    name="kubernetes",
    sniffer=_k8s_sniffer,
    handler=store_k8s_symbols,
    priority=10,
)
