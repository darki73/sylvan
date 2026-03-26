"""Kubernetes RBAC kind handlers -- ServiceAccount, Role, ClusterRole, RoleBinding, ClusterRoleBinding."""

from __future__ import annotations

from sylvan.extensions.native.kubernetes import register_kind_handler


@register_kind_handler("ServiceAccount")
def handle_service_account(doc: dict, metadata: dict, spec: dict) -> dict:
    annotations = metadata.get("annotations", {})
    sig = []

    # IRSA / workload identity annotations
    arn = annotations.get("eks.amazonaws.com/role-arn", "")
    gcp_sa = annotations.get("iam.gke.io/gcp-service-account", "")
    if arn:
        sig.append(f"arn={arn.split('/')[-1]}")
    if gcp_sa:
        sig.append(f"gcp-sa={gcp_sa}")

    return {"sig_parts": sig, "references": []}


@register_kind_handler("Role")
def handle_role(doc: dict, metadata: dict, spec: dict) -> dict:
    rules = doc.get("rules", [])
    sig = []
    if rules:
        resources = set()
        for r in rules:
            resources.update(r.get("resources", []))
        sig.append(f"rules={len(rules)}")
        if resources:
            sig.append(f"resources=[{', '.join(sorted(resources))}]")
    return {"sig_parts": sig, "references": []}


@register_kind_handler("ClusterRole")
def handle_cluster_role(doc: dict, metadata: dict, spec: dict) -> dict:
    return handle_role(doc, metadata, spec)


@register_kind_handler("RoleBinding")
def handle_role_binding(doc: dict, metadata: dict, spec: dict) -> dict:
    role_ref = doc.get("roleRef", {})
    subjects = doc.get("subjects", [])

    sig = []
    refs = []

    if role_ref:
        role_kind = role_ref.get("kind", "Role")
        role_name = role_ref.get("name", "")
        sig.append(f"role={role_kind}/{role_name}")
        refs.append(f"k8s://{role_kind}/{role_name}")

    for s in subjects:
        s_kind = s.get("kind", "")
        s_name = s.get("name", "")
        if s_kind and s_name:
            sig.append(f"subject={s_kind}/{s_name}")
            refs.append(f"k8s://{s_kind}/{s_name}")

    return {"sig_parts": sig, "references": list(dict.fromkeys(refs))}


@register_kind_handler("ClusterRoleBinding")
def handle_cluster_role_binding(doc: dict, metadata: dict, spec: dict) -> dict:
    return handle_role_binding(doc, metadata, spec)
