"""Kubernetes workload kind handlers -- Deployment, StatefulSet, DaemonSet, Job, CronJob."""

from __future__ import annotations

from sylvan.extensions.native.kubernetes import register_kind_handler


def _extract_container_refs(template_spec: dict) -> tuple[list[str], list[str]]:
    """Extract signature parts and references from a pod template spec."""
    sig = []
    refs = []

    containers = template_spec.get("containers", [])
    images = []
    for c in containers:
        image = c.get("image", "")
        if image:
            images.append(image.split("/")[-1])
            refs.append(f"k8s://Image/{image}")
        # Secret/ConfigMap refs from env
        for env in c.get("env", []):
            vf = env.get("valueFrom", {})
            secret_ref = vf.get("secretKeyRef", {})
            if secret_ref.get("name"):
                refs.append(f"k8s://Secret/{secret_ref['name']}")
            cm_ref = vf.get("configMapKeyRef", {})
            if cm_ref.get("name"):
                refs.append(f"k8s://ConfigMap/{cm_ref['name']}")
        # envFrom
        for ef in c.get("envFrom", []):
            if ef.get("secretRef", {}).get("name"):
                refs.append(f"k8s://Secret/{ef['secretRef']['name']}")
            if ef.get("configMapRef", {}).get("name"):
                refs.append(f"k8s://ConfigMap/{ef['configMapRef']['name']}")

    if images:
        sig.append(f"images=[{', '.join(images)}]")

    # Volumes
    for vol in template_spec.get("volumes", []):
        pvc = vol.get("persistentVolumeClaim", {})
        if pvc.get("claimName"):
            refs.append(f"k8s://PersistentVolumeClaim/{pvc['claimName']}")
        secret = vol.get("secret", {})
        if secret.get("secretName"):
            refs.append(f"k8s://Secret/{secret['secretName']}")
        cm = vol.get("configMap", {})
        if cm.get("name"):
            refs.append(f"k8s://ConfigMap/{cm['name']}")

    # ServiceAccount
    sa = template_spec.get("serviceAccountName", "")
    if sa:
        refs.append(f"k8s://ServiceAccount/{sa}")

    # ImagePullSecrets
    for ips in template_spec.get("imagePullSecrets", []):
        if ips.get("name"):
            refs.append(f"k8s://Secret/{ips['name']}")

    return sig, list(dict.fromkeys(refs))  # deduplicate


@register_kind_handler("Deployment")
def handle_deployment(doc: dict, metadata: dict, spec: dict) -> dict:
    replicas = spec.get("replicas", "?")
    template_spec = spec.get("template", {}).get("spec", {})
    sig, refs = _extract_container_refs(template_spec)
    return {
        "sig_parts": [f"replicas={replicas}", *sig],
        "references": refs,
    }


@register_kind_handler("StatefulSet")
def handle_statefulset(doc: dict, metadata: dict, spec: dict) -> dict:
    replicas = spec.get("replicas", "?")
    template_spec = spec.get("template", {}).get("spec", {})
    sig, refs = _extract_container_refs(template_spec)
    vct = spec.get("volumeClaimTemplates", [])
    if vct:
        sig.append(f"volumeClaims={len(vct)}")
    return {
        "sig_parts": [f"replicas={replicas}", *sig],
        "references": refs,
    }


@register_kind_handler("DaemonSet")
def handle_daemonset(doc: dict, metadata: dict, spec: dict) -> dict:
    template_spec = spec.get("template", {}).get("spec", {})
    sig, refs = _extract_container_refs(template_spec)
    node_selector = template_spec.get("nodeSelector", {})
    if node_selector:
        sig.append(f"nodeSelector={list(node_selector.keys())}")
    return {"sig_parts": sig, "references": refs}


@register_kind_handler("Job")
def handle_job(doc: dict, metadata: dict, spec: dict) -> dict:
    template_spec = spec.get("template", {}).get("spec", {})
    sig, refs = _extract_container_refs(template_spec)
    completions = spec.get("completions")
    parallelism = spec.get("parallelism")
    if completions:
        sig.append(f"completions={completions}")
    if parallelism:
        sig.append(f"parallelism={parallelism}")
    return {"sig_parts": sig, "references": refs}


@register_kind_handler("CronJob")
def handle_cronjob(doc: dict, metadata: dict, spec: dict) -> dict:
    schedule = spec.get("schedule", "?")
    job_spec = spec.get("jobTemplate", {}).get("spec", {})
    template_spec = job_spec.get("template", {}).get("spec", {})
    sig, refs = _extract_container_refs(template_spec)
    return {
        "sig_parts": [f'schedule="{schedule}"', *sig],
        "references": refs,
    }


@register_kind_handler("ReplicaSet")
def handle_replicaset(doc: dict, metadata: dict, spec: dict) -> dict:
    replicas = spec.get("replicas", "?")
    template_spec = spec.get("template", {}).get("spec", {})
    sig, refs = _extract_container_refs(template_spec)
    return {
        "sig_parts": [f"replicas={replicas}", *sig],
        "references": refs,
    }


@register_kind_handler("Pod")
def handle_pod(doc: dict, metadata: dict, spec: dict) -> dict:
    sig, refs = _extract_container_refs(spec)
    node = spec.get("nodeName", "")
    if node:
        sig.append(f"node={node}")
    return {"sig_parts": sig, "references": refs}
