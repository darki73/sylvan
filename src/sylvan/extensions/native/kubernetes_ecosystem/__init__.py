"""Kubernetes ecosystem extensions -- ArgoCD, Traefik, Cert-Manager."""

from sylvan.extensions.native.kubernetes import KIND_TO_SYMBOL_KIND

# Register ecosystem kinds
KIND_TO_SYMBOL_KIND.update(
    {
        # ArgoCD
        "Application": "class",
        "ApplicationSet": "class",
        "AppProject": "class",
        # Traefik
        "IngressRoute": "class",
        "IngressRouteTCP": "class",
        "IngressRouteUDP": "class",
        "Middleware": "constant",
        "TLSOption": "constant",
        # Cert-Manager
        "Certificate": "constant",
        "Issuer": "constant",
        "ClusterIssuer": "constant",
    }
)

from sylvan.extensions.native.kubernetes_ecosystem import (  # noqa: F401
    argocd,
    cert_manager,
    traefik,
)
