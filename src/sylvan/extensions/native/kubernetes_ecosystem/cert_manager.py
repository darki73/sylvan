"""Cert-Manager kind handlers -- Certificate, Issuer, ClusterIssuer."""

from __future__ import annotations

from sylvan.extensions.native.kubernetes import register_kind_handler


@register_kind_handler("Certificate")
def handle_certificate(doc: dict, metadata: dict, spec: dict) -> dict:
    dns_names = spec.get("dnsNames", [])
    secret_name = spec.get("secretName", "")
    issuer_ref = spec.get("issuerRef", {})

    sig = []
    refs = []

    if dns_names:
        sig.append(f"dns=[{', '.join(dns_names)}]")
    if secret_name:
        sig.append(f"secret={secret_name}")
        refs.append(f"k8s://Secret/{secret_name}")
    if issuer_ref:
        issuer_kind = issuer_ref.get("kind", "Issuer")
        issuer_name = issuer_ref.get("name", "")
        sig.append(f"issuer={issuer_kind}/{issuer_name}")
        refs.append(f"k8s://{issuer_kind}/{issuer_name}")

    return {"sig_parts": sig, "references": list(dict.fromkeys(refs))}


@register_kind_handler("Issuer")
def handle_issuer(doc: dict, metadata: dict, spec: dict) -> dict:
    return _handle_issuer_common(spec)


@register_kind_handler("ClusterIssuer")
def handle_cluster_issuer(doc: dict, metadata: dict, spec: dict) -> dict:
    return _handle_issuer_common(spec)


def _handle_issuer_common(spec: dict) -> dict:
    sig = []

    if "acme" in spec:
        acme = spec["acme"]
        server = acme.get("server", "")
        sig.append("type=ACME")
        if "letsencrypt" in server:
            sig.append("server=letsencrypt")
        elif server:
            sig.append(f"server={server.split('//')[-1].split('/')[0]}")
    elif "ca" in spec:
        sig.append("type=CA")
    elif "selfSigned" in spec:
        sig.append("type=self-signed")
    elif "vault" in spec:
        sig.append("type=vault")

    return {"sig_parts": sig, "references": []}
