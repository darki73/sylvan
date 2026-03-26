"""Kubernetes networking kind handlers -- Service, Ingress, NetworkPolicy."""

from __future__ import annotations

from sylvan.extensions.native.kubernetes import register_kind_handler


@register_kind_handler("Service")
def handle_service(doc: dict, metadata: dict, spec: dict) -> dict:
    svc_type = spec.get("type", "ClusterIP")
    ports = spec.get("ports", [])
    selector = spec.get("selector", {})

    sig = [f"type={svc_type}"]
    refs = []

    if ports:
        port_strs = [f"{p.get('port', '?')}/{p.get('protocol', 'TCP')}" for p in ports]
        sig.append(f"ports=[{', '.join(port_strs)}]")

    if selector:
        # Service selects pods by labels - reference the workload
        app_label = selector.get("app") or selector.get("app.kubernetes.io/name", "")
        if app_label:
            refs.append(f"k8s://Deployment/{app_label}")

    return {"sig_parts": sig, "references": refs}


@register_kind_handler("Ingress")
def handle_ingress(doc: dict, metadata: dict, spec: dict) -> dict:
    rules = spec.get("rules", [])
    tls = spec.get("tls", [])

    sig = []
    refs = []

    hosts = [r.get("host", "?") for r in rules if r.get("host")]
    if hosts:
        sig.append(f"hosts=[{', '.join(hosts)}]")

    if tls:
        sig.append("tls=true")
        for t in tls:
            secret = t.get("secretName", "")
            if secret:
                refs.append(f"k8s://Secret/{secret}")

    # Backend service references
    for rule in rules:
        for path in rule.get("http", {}).get("paths", []):
            backend = path.get("backend", {})
            svc = backend.get("service", {})
            if svc.get("name"):
                refs.append(f"k8s://Service/{svc['name']}")

    return {"sig_parts": sig, "references": list(dict.fromkeys(refs))}


@register_kind_handler("IngressClass")
def handle_ingress_class(doc: dict, metadata: dict, spec: dict) -> dict:
    controller = spec.get("controller", "")
    sig = []
    if controller:
        sig.append(f"controller={controller}")
    return {"sig_parts": sig, "references": []}


@register_kind_handler("NetworkPolicy")
def handle_network_policy(doc: dict, metadata: dict, spec: dict) -> dict:
    pod_selector = spec.get("podSelector", {})
    policy_types = spec.get("policyTypes", [])
    ingress_rules = spec.get("ingress", [])
    egress_rules = spec.get("egress", [])

    sig = []
    if policy_types:
        sig.append(f"types=[{', '.join(policy_types)}]")
    if ingress_rules:
        sig.append(f"ingress_rules={len(ingress_rules)}")
    if egress_rules:
        sig.append(f"egress_rules={len(egress_rules)}")

    refs = []
    match_labels = pod_selector.get("matchLabels", {})
    app_label = match_labels.get("app") or match_labels.get("app.kubernetes.io/name", "")
    if app_label:
        refs.append(f"k8s://Deployment/{app_label}")

    return {"sig_parts": sig, "references": refs}


@register_kind_handler("Endpoints")
def handle_endpoints(doc: dict, metadata: dict, spec: dict) -> dict:
    return {"sig_parts": [], "references": []}


@register_kind_handler("EndpointSlice")
def handle_endpoint_slice(doc: dict, metadata: dict, spec: dict) -> dict:
    return {"sig_parts": [], "references": []}
