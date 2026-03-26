"""Kubernetes storage kind handlers -- PVC, PV, StorageClass."""

from __future__ import annotations

from sylvan.extensions.native.kubernetes import register_kind_handler


@register_kind_handler("PersistentVolumeClaim")
def handle_pvc(doc: dict, metadata: dict, spec: dict) -> dict:
    access_modes = spec.get("accessModes", [])
    storage_class = spec.get("storageClassName", "")
    resources = spec.get("resources", {})
    requested = resources.get("requests", {}).get("storage", "")

    sig = []
    if access_modes:
        sig.append(f"access=[{', '.join(access_modes)}]")
    if storage_class:
        sig.append(f"class={storage_class}")
    if requested:
        sig.append(f"size={requested}")

    return {"sig_parts": sig, "references": []}


@register_kind_handler("PersistentVolume")
def handle_pv(doc: dict, metadata: dict, spec: dict) -> dict:
    capacity = spec.get("capacity", {}).get("storage", "")
    access_modes = spec.get("accessModes", [])
    reclaim = spec.get("persistentVolumeReclaimPolicy", "")

    sig = []
    if capacity:
        sig.append(f"capacity={capacity}")
    if access_modes:
        sig.append(f"access=[{', '.join(access_modes)}]")
    if reclaim:
        sig.append(f"reclaim={reclaim}")

    return {"sig_parts": sig, "references": []}


@register_kind_handler("StorageClass")
def handle_storage_class(doc: dict, metadata: dict, spec: dict) -> dict:
    provisioner = doc.get("provisioner", "")
    reclaim = doc.get("reclaimPolicy", "")

    sig = []
    if provisioner:
        sig.append(f"provisioner={provisioner}")
    if reclaim:
        sig.append(f"reclaim={reclaim}")

    return {"sig_parts": sig, "references": []}
