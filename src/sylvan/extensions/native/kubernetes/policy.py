"""Kubernetes policy kind handlers -- HPA, PDB, LimitRange, ResourceQuota, PriorityClass."""

from __future__ import annotations

from sylvan.extensions.native.kubernetes import register_kind_handler


@register_kind_handler("HorizontalPodAutoscaler")
def handle_hpa(doc: dict, metadata: dict, spec: dict) -> dict:
    min_r = spec.get("minReplicas", "?")
    max_r = spec.get("maxReplicas", "?")
    target_ref = spec.get("scaleTargetRef", {})

    sig = [f"min={min_r}", f"max={max_r}"]
    refs = []

    if target_ref:
        kind = target_ref.get("kind", "Deployment")
        name = target_ref.get("name", "")
        sig.append(f"target={kind}/{name}")
        if name:
            refs.append(f"k8s://{kind}/{name}")

    metrics = spec.get("metrics", [])
    if metrics:
        metric_types = [m.get("type", "?") for m in metrics]
        sig.append(f"metrics=[{', '.join(metric_types)}]")

    return {"sig_parts": sig, "references": refs}


@register_kind_handler("PodDisruptionBudget")
def handle_pdb(doc: dict, metadata: dict, spec: dict) -> dict:
    min_available = spec.get("minAvailable")
    max_unavailable = spec.get("maxUnavailable")
    selector = spec.get("selector", {})

    sig = []
    refs = []

    if min_available is not None:
        sig.append(f"minAvailable={min_available}")
    if max_unavailable is not None:
        sig.append(f"maxUnavailable={max_unavailable}")

    match_labels = selector.get("matchLabels", {})
    app_label = match_labels.get("app") or match_labels.get("app.kubernetes.io/name", "")
    if app_label:
        refs.append(f"k8s://Deployment/{app_label}")

    return {"sig_parts": sig, "references": refs}


@register_kind_handler("LimitRange")
def handle_limit_range(doc: dict, metadata: dict, spec: dict) -> dict:
    limits = spec.get("limits", [])
    sig = []
    for limit in limits:
        ltype = limit.get("type", "?")
        default = limit.get("default", {})
        if default:
            sig.append(f"{ltype}: cpu={default.get('cpu', '?')} mem={default.get('memory', '?')}")
    return {"sig_parts": sig, "references": []}


@register_kind_handler("ResourceQuota")
def handle_resource_quota(doc: dict, metadata: dict, spec: dict) -> dict:
    hard = spec.get("hard", {})
    sig = []
    if hard:
        limits = [f"{k}={v}" for k, v in hard.items()]
        sig.append(f"hard=[{', '.join(limits)}]")
    return {"sig_parts": sig, "references": []}


@register_kind_handler("PriorityClass")
def handle_priority_class(doc: dict, metadata: dict, spec: dict) -> dict:
    value = doc.get("value", 0)
    global_default = doc.get("globalDefault", False)
    sig = [f"value={value}"]
    if global_default:
        sig.append("globalDefault=true")
    return {"sig_parts": sig, "references": []}


@register_kind_handler("RuntimeClass")
def handle_runtime_class(doc: dict, metadata: dict, spec: dict) -> dict:
    handler = doc.get("handler", "")
    sig = []
    if handler:
        sig.append(f"handler={handler}")
    return {"sig_parts": sig, "references": []}
