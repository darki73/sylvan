"""Kubernetes config kind handlers -- ConfigMap, Secret, Namespace, ExternalSecret, Kustomization."""

from __future__ import annotations

from sylvan.extensions.native.kubernetes import register_kind_handler


@register_kind_handler("ConfigMap")
def handle_configmap(doc: dict, metadata: dict, spec: dict) -> dict:
    data = doc.get("data", {})
    sig = []
    if data:
        sig.append(f"keys=[{', '.join(data.keys())}]")
    return {"sig_parts": sig, "references": []}


@register_kind_handler("Secret")
def handle_secret(doc: dict, metadata: dict, spec: dict) -> dict:
    secret_type = doc.get("type", "")
    data = doc.get("data", {})
    string_data = doc.get("stringData", {})
    labels = metadata.get("labels", {})

    sig = []
    refs = []

    if secret_type:
        sig.append(f"type={secret_type}")

    # ArgoCD repo secrets
    argo_type = labels.get("argocd.argoproj.io/secret-type", "")
    if argo_type:
        sig.append(f"argocd-type={argo_type}")
        url = string_data.get("url") or string_data.get("repoURL", "")
        if url:
            sig.append(f"url={url.split('/')[-1]}")

    # Key names only (values stripped in __init__.py)
    all_keys = list(data.keys()) + list(string_data.keys())
    non_meta_keys = [k for k in all_keys if k not in ("type", "url", "repoURL")]
    if non_meta_keys:
        sig.append(f"keys=[{', '.join(non_meta_keys)}]")

    return {"sig_parts": sig, "references": refs}


@register_kind_handler("Namespace")
def handle_namespace(doc: dict, metadata: dict, spec: dict) -> dict:
    return {"sig_parts": [], "references": []}


@register_kind_handler("ExternalSecret")
def handle_external_secret(doc: dict, metadata: dict, spec: dict) -> dict:
    store = spec.get("secretStoreRef", {})
    target = spec.get("target", {})
    data_from = spec.get("dataFrom", [])
    data = spec.get("data", [])

    sig = []
    refs = []

    if store:
        sig.append(f"store={store.get('name', '?')}/{store.get('kind', '?')}")

    # Vault keys from dataFrom
    keys = [e.get("extract", {}).get("key", "") for e in data_from if "extract" in e]
    if keys:
        sig.append(f"keys=[{', '.join(keys)}]")

    # Individual data mappings
    if data and not keys:
        remote_keys = list({d.get("remoteRef", {}).get("key", "") for d in data if d.get("remoteRef")})
        if remote_keys:
            sig.append(f"sources=[{', '.join(remote_keys)}]")

    # Target secret this creates
    target_name = target.get("name", "")
    if target_name:
        refs.append(f"k8s://Secret/{target_name}")

    return {"sig_parts": sig, "references": refs}


@register_kind_handler("Kustomization")
def handle_kustomization(doc: dict, metadata: dict, spec: dict) -> dict:
    resources = doc.get("resources", [])
    patches = doc.get("patchesStrategicMerge", []) + doc.get("patches", [])
    images = doc.get("images", [])

    sig = []
    refs = []

    if resources:
        sig.append(f"resources=[{', '.join(resources)}]")
        for r in resources:
            refs.append(f"k8s://File/{r}")

    if patches:
        sig.append(f"patches={len(patches)}")

    if images:
        image_names = [i.get("name", "").split("/")[-1] for i in images if i.get("name")]
        if image_names:
            sig.append(f"images=[{', '.join(image_names)}]")

    return {"sig_parts": sig, "references": refs}
