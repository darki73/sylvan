"""Traefik kind handlers -- IngressRoute, IngressRouteTCP, IngressRouteUDP, Middleware."""

from __future__ import annotations

from sylvan.extensions.native.kubernetes import register_kind_handler


@register_kind_handler("IngressRoute")
def handle_ingress_route(doc: dict, metadata: dict, spec: dict) -> dict:
    entry_points = spec.get("entryPoints", [])
    routes = spec.get("routes", [])

    sig = []
    refs = []

    if entry_points:
        sig.append(f"entryPoints=[{', '.join(entry_points)}]")

    for route in routes:
        match = route.get("match", "")
        if "Host(" in match:
            # Extract host from Host(`example.com`)
            import re

            hosts = re.findall(r"Host\(`([^`]+)`\)", match)
            if hosts:
                sig.append(f"hosts=[{', '.join(hosts)}]")

        for svc in route.get("services", []):
            name = svc.get("name", "")
            if name:
                refs.append(f"k8s://Service/{name}")

    return {"sig_parts": sig, "references": list(dict.fromkeys(refs))}


@register_kind_handler("IngressRouteTCP")
def handle_ingress_route_tcp(doc: dict, metadata: dict, spec: dict) -> dict:
    entry_points = spec.get("entryPoints", [])
    routes = spec.get("routes", [])

    sig = []
    refs = []

    if entry_points:
        sig.append(f"entryPoints=[{', '.join(entry_points)}]")

    for route in routes:
        for svc in route.get("services", []):
            name = svc.get("name", "")
            port = svc.get("port", "")
            if name:
                refs.append(f"k8s://Service/{name}")
                if port:
                    sig.append(f"backend={name}:{port}")

    return {"sig_parts": sig, "references": list(dict.fromkeys(refs))}


@register_kind_handler("IngressRouteUDP")
def handle_ingress_route_udp(doc: dict, metadata: dict, spec: dict) -> dict:
    return handle_ingress_route_tcp(doc, metadata, spec)


@register_kind_handler("Middleware")
def handle_middleware(doc: dict, metadata: dict, spec: dict) -> dict:
    # Detect middleware type from spec keys
    middleware_types = [k for k in spec if k not in ("plugin",)]
    sig = []
    if middleware_types:
        sig.append(f"type={middleware_types[0]}")
    return {"sig_parts": sig, "references": []}
