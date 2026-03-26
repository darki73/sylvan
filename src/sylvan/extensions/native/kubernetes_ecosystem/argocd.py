"""ArgoCD kind handlers -- Application, AppProject, ApplicationSet."""

from __future__ import annotations

from sylvan.extensions.native.kubernetes import register_kind_handler


@register_kind_handler("Application")
def handle_application(doc: dict, metadata: dict, spec: dict) -> dict:
    sig = []
    refs = []

    # Single source
    source = spec.get("source", {})
    # Multi-source
    sources = spec.get("sources", [])

    if source:
        _extract_source(source, sig, refs)
    for s in sources:
        _extract_source(s, sig, refs)

    dest = spec.get("destination", {})
    dest_ns = dest.get("namespace", "")
    if dest_ns:
        sig.append(f"dest={dest_ns}")

    project = spec.get("project", "")
    if project:
        refs.append(f"k8s://AppProject/{project}")

    return {"sig_parts": sig, "references": list(dict.fromkeys(refs))}


def _extract_source(source: dict, sig: list, refs: list) -> None:
    """Extract signature and refs from an ArgoCD source."""
    repo_url = source.get("repoURL", "")
    path = source.get("path", "")
    chart = source.get("chart", "")
    target_rev = source.get("targetRevision", "")

    if chart:
        sig.append(f"chart={chart}")
        if target_rev:
            sig.append(f"chartVersion={target_rev}")
    elif repo_url:
        sig.append(f"repo={repo_url.split('/')[-1]}")
        if path:
            sig.append(f"path={path}")
        if target_rev:
            sig.append(f"rev={target_rev}")


@register_kind_handler("AppProject")
def handle_app_project(doc: dict, metadata: dict, spec: dict) -> dict:
    desc = spec.get("description", "")
    destinations = spec.get("destinations", [])
    source_repos = spec.get("sourceRepos", [])

    sig = []
    if desc:
        sig.append(f'"{desc}"')
    sig.append(f"repos={len(source_repos)}")
    sig.append(f"destinations={len(destinations)}")

    return {"sig_parts": sig, "references": []}


@register_kind_handler("ApplicationSet")
def handle_application_set(doc: dict, metadata: dict, spec: dict) -> dict:
    generators = spec.get("generators", [])
    template = spec.get("template", {})

    sig = []
    if generators:
        gen_types = []
        for g in generators:
            for key in g:
                if key != "selector":
                    gen_types.append(key)
        sig.append(f"generators=[{', '.join(gen_types)}]")

    template_spec = template.get("spec", {})
    dest = template_spec.get("destination", {})
    if dest.get("namespace"):
        sig.append(f"dest={dest['namespace']}")

    return {"sig_parts": sig, "references": []}
