# Kubernetes Support

Sylvan indexes Kubernetes YAML files as first-class symbols. Deployments, Services, Secrets, and other resources become searchable just like functions and classes. Cross-references between resources enable blast radius analysis and dependency tracing for infrastructure.

## What gets indexed

Any YAML file with `apiVersion` and `kind` fields is recognized as a Kubernetes resource. Each resource becomes a symbol with:

- **Name** from `metadata.name`
- **Namespace** from `metadata.namespace`
- **Signature** with kind-specific details (replicas, images, ports, vault paths, etc.)
- **Cross-references** to other resources (Secrets, ConfigMaps, PVCs, ServiceAccounts)

### Core Kubernetes

| Kind | Symbol type | Signature includes |
|------|------------|-------------------|
| Deployment | class | replicas, container images, resource limits |
| StatefulSet | class | replicas, volume claim templates |
| DaemonSet | class | node selector, tolerations |
| Job / CronJob | class | schedule, completions, parallelism |
| Service | class | type, ports, selector |
| Ingress | class | hosts, paths, TLS |
| ConfigMap | constant | key names |
| Secret | constant | type, key names (values redacted) |
| Namespace | constant | labels |
| PVC / PV | constant | access modes, storage class, size |
| ServiceAccount | constant | IRSA/workload identity annotations |
| Role / RoleBinding | constant | rules, subjects, role ref |
| HPA | constant | min/max replicas, target, metrics |
| NetworkPolicy | constant | policy types, rule counts |

### Ecosystem (shipped as native extensions)

| Kind | Ecosystem | Signature includes |
|------|-----------|-------------------|
| Application | ArgoCD | source repo, path, revision, destination |
| AppProject | ArgoCD | description, allowed repos, destinations |
| ApplicationSet | ArgoCD | generators, destination |
| ExternalSecret | External Secrets | store ref, vault keys, target secret |
| Kustomization | Kustomize | resources list, patches, images |
| IngressRoute | Traefik | entry points, hosts, backend services |
| Middleware | Traefik | middleware type |
| Certificate | Cert-Manager | DNS names, issuer, secret name |
| Issuer / ClusterIssuer | Cert-Manager | type (ACME, CA, self-signed) |

## Searching infrastructure

Index a project that contains k8s manifests:

```
index_project(path="/path/to/infra-repo")
```

Then search like any other code:

```
find_code(query="redis", repo="infra")          # find Redis Deployment
find_code(query="ExternalSecret", repo="infra")  # find all external secrets
find_code(query="vault", repo="infra")           # find anything using Vault
whats_in_file(repo="infra", file_path="k8s/app/deployment.yaml")  # outline of resources
```

## Cross-references and blast radius

Deployments reference Secrets, ConfigMaps, PVCs, and ServiceAccounts. These are stored as imports, so the existing dependency tools work:

```
who_depends_on_this(repo="infra", file_path="k8s/secrets/db-creds.yaml")
# -> shows which Deployments use this Secret

what_breaks_if_i_change(symbol_id="deploy.yaml::Deployment/web@prod#class")
# -> shows all resources affected if this Deployment changes

import_graph(repo="infra", file_path="k8s/app/deployment.yaml")
# -> shows Secrets, PVCs, ServiceAccount dependencies
```

## Secret handling

`kind: Secret` resources with `data` or `stringData` fields contain actual secret values. Sylvan indexes the resource as a symbol (name, namespace, type, key names) but redacts all values:

```
Secret/db-creds namespace=prod type=Opaque keys=[password, username, host]
```

The actual secret values are never stored in the index. Key names are preserved because they describe the structure, not the secrets themselves.

References to secrets (like `secretKeyRef` in Deployment env vars) are safe - they're just pointers, not values.

## Helm templates

Files containing Go template syntax (`{{ }}`) are automatically skipped. These are Helm chart templates that produce valid YAML only after rendering - they can't be parsed as-is.

Helm `values.yaml` files are plain YAML and get indexed normally as documentation sections.

## Multi-document YAML

Files with multiple resources separated by `---` are fully supported. Each document is extracted as a separate symbol. This is common in kustomize outputs and hand-crafted manifests.

## Unknown CRDs

Resources with unrecognized `kind` values still get indexed with generic metadata (name, namespace, apiVersion, labels, annotations). You don't need to configure anything for custom CRDs to be searchable - they just won't have enriched signatures.
