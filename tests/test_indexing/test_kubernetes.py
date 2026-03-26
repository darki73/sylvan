"""Tests for Kubernetes YAML parsing and symbol extraction."""

from sylvan.extensions.native.kubernetes import (
    _strip_secret_values,
    is_k8s_yaml,
    parse_k8s_file,
    parse_k8s_resource,
)


class TestIsK8sYaml:
    def test_detects_k8s_resource(self):
        content = "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: test"
        assert is_k8s_yaml(content) is True

    def test_rejects_plain_yaml(self):
        content = "name: my-config\nvalue: 42\nkeys:\n  - a\n  - b"
        assert is_k8s_yaml(content) is False

    def test_rejects_helm_templates(self):
        content = "apiVersion: apps/v1\nkind: Deployment\n{{ .Values.name }}"
        assert is_k8s_yaml(content) is False

    def test_rejects_yaml_with_only_api_version(self):
        content = "apiVersion: v1\nname: test"
        assert is_k8s_yaml(content) is False

    def test_rejects_yaml_with_only_kind(self):
        content = "kind: ConfigMap\nname: test"
        assert is_k8s_yaml(content) is False

    def test_rejects_empty(self):
        assert is_k8s_yaml("") is False

    def test_detects_in_first_30_lines(self):
        padding = "\n".join(f"# comment {i}" for i in range(25))
        content = f"{padding}\napiVersion: v1\nkind: Service\nmetadata:\n  name: svc"
        assert is_k8s_yaml(content) is True

    def test_rejects_if_past_30_lines(self):
        padding = "\n".join(f"# comment {i}" for i in range(35))
        content = f"{padding}\napiVersion: v1\nkind: Service"
        assert is_k8s_yaml(content) is False


class TestParseK8sResource:
    def test_basic_deployment(self):
        doc = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "web", "namespace": "prod"},
            "spec": {
                "replicas": 3,
                "template": {"spec": {"containers": [{"name": "app", "image": "nginx:1.25"}]}},
            },
        }
        result = parse_k8s_resource(doc, "deploy.yaml")
        assert result is not None
        assert result["name"] == "web"
        assert result["kind"] == "class"
        assert result["language"] == "kubernetes"
        assert "Deployment/web" in result["symbol_id"]
        assert "@prod" in result["symbol_id"]
        assert "replicas=3" in result["signature"]
        assert "nginx:1.25" in result["signature"]

    def test_service(self):
        doc = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "web-svc", "namespace": "prod"},
            "spec": {
                "type": "ClusterIP",
                "ports": [{"port": 80, "protocol": "TCP"}],
                "selector": {"app": "web"},
            },
        }
        result = parse_k8s_resource(doc, "svc.yaml")
        assert result is not None
        assert "type=ClusterIP" in result["signature"]
        assert "80/TCP" in result["signature"]
        assert "k8s://Deployment/web" in result["references"]

    def test_configmap(self):
        doc = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "config"},
            "data": {"DB_HOST": "localhost", "DB_PORT": "5432"},
        }
        result = parse_k8s_resource(doc, "cm.yaml")
        assert result is not None
        assert result["kind"] == "constant"
        assert "DB_HOST" in result["signature"]
        assert "DB_PORT" in result["signature"]

    def test_secret_values_in_source_are_redacted(self):
        doc = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "creds"},
            "data": {"password": "c2VjcmV0"},
            "stringData": {"api_key": "super-secret-key"},
        }
        result = parse_k8s_resource(doc, "secret.yaml")
        assert result is not None
        assert result["source_doc"]["data"]["password"] == "<redacted>"  # noqa: S105
        assert result["source_doc"]["stringData"]["api_key"] == "<redacted>"

    def test_secret_keys_in_signature(self):
        doc = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "creds"},
            "type": "Opaque",
            "data": {"password": "c2VjcmV0", "username": "dXNlcg=="},
        }
        result = parse_k8s_resource(doc, "secret.yaml")
        assert "type=Opaque" in result["signature"]
        assert "password" in result["signature"]
        assert "username" in result["signature"]
        # Actual values never in signature
        assert "c2VjcmV0" not in result["signature"]

    def test_namespace(self):
        doc = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": "staging", "labels": {"env": "staging"}},
        }
        result = parse_k8s_resource(doc, "ns.yaml")
        assert result["kind"] == "constant"
        assert "labels: env=staging" in result["docstring"]

    def test_external_secret(self):
        doc = {
            "apiVersion": "external-secrets.io/v1",
            "kind": "ExternalSecret",
            "metadata": {"name": "db-creds", "namespace": "prod"},
            "spec": {
                "secretStoreRef": {"name": "vault", "kind": "ClusterSecretStore"},
                "target": {"name": "db-creds"},
                "dataFrom": [{"extract": {"key": "secret/data/db"}}],
            },
        }
        result = parse_k8s_resource(doc, "es.yaml")
        assert "store=vault/ClusterSecretStore" in result["signature"]
        assert "secret/data/db" in result["signature"]
        assert "k8s://Secret/db-creds" in result["references"]

    def test_kustomization(self):
        doc = {
            "apiVersion": "kustomize.config.k8s.io/v1beta1",
            "kind": "Kustomization",
            "metadata": {"name": "kustomization"},
            "resources": ["deployment.yaml", "service.yaml"],
        }
        result = parse_k8s_resource(doc, "kustomization.yaml")
        assert "resources=[deployment.yaml, service.yaml]" in result["signature"]
        assert "k8s://File/deployment.yaml" in result["references"]

    def test_missing_kind_returns_none(self):
        doc = {"apiVersion": "v1", "metadata": {"name": "test"}}
        assert parse_k8s_resource(doc, "test.yaml") is None

    def test_missing_metadata_returns_none(self):
        doc = {"apiVersion": "v1", "kind": "ConfigMap"}
        assert parse_k8s_resource(doc, "test.yaml") is None

    def test_unknown_kind_uses_generic(self):
        doc = {
            "apiVersion": "custom.io/v1",
            "kind": "MyCustomResource",
            "metadata": {"name": "test", "namespace": "default"},
            "spec": {},
        }
        result = parse_k8s_resource(doc, "custom.yaml")
        assert result is not None
        assert result["kind"] == "constant"  # default for unknown
        assert "MyCustomResource/test" in result["signature"]


class TestDeploymentReferences:
    def test_secret_ref_from_env(self):
        doc = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "app"},
            "spec": {
                "replicas": 1,
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "app",
                                "image": "app:latest",
                                "env": [
                                    {
                                        "name": "DB_PASS",
                                        "valueFrom": {"secretKeyRef": {"name": "db-secret", "key": "password"}},
                                    }
                                ],
                            }
                        ]
                    }
                },
            },
        }
        result = parse_k8s_resource(doc, "deploy.yaml")
        assert "k8s://Secret/db-secret" in result["references"]

    def test_configmap_ref_from_env(self):
        doc = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "app"},
            "spec": {
                "replicas": 1,
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "app",
                                "image": "app:latest",
                                "env": [
                                    {
                                        "name": "LOG_LEVEL",
                                        "valueFrom": {"configMapKeyRef": {"name": "app-config", "key": "log_level"}},
                                    }
                                ],
                            }
                        ]
                    }
                },
            },
        }
        result = parse_k8s_resource(doc, "deploy.yaml")
        assert "k8s://ConfigMap/app-config" in result["references"]

    def test_pvc_ref(self):
        doc = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "app"},
            "spec": {
                "replicas": 1,
                "template": {
                    "spec": {
                        "containers": [{"name": "app", "image": "app:latest"}],
                        "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": "data-pvc"}}],
                    }
                },
            },
        }
        result = parse_k8s_resource(doc, "deploy.yaml")
        assert "k8s://PersistentVolumeClaim/data-pvc" in result["references"]

    def test_service_account_ref(self):
        doc = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "app"},
            "spec": {
                "replicas": 1,
                "template": {
                    "spec": {
                        "serviceAccountName": "app-sa",
                        "containers": [{"name": "app", "image": "app:latest"}],
                    }
                },
            },
        }
        result = parse_k8s_resource(doc, "deploy.yaml")
        assert "k8s://ServiceAccount/app-sa" in result["references"]

    def test_image_pull_secret_ref(self):
        doc = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "app"},
            "spec": {
                "replicas": 1,
                "template": {
                    "spec": {
                        "containers": [{"name": "app", "image": "app:latest"}],
                        "imagePullSecrets": [{"name": "registry-creds"}],
                    }
                },
            },
        }
        result = parse_k8s_resource(doc, "deploy.yaml")
        assert "k8s://Secret/registry-creds" in result["references"]

    def test_references_deduplication(self):
        doc = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "app"},
            "spec": {
                "replicas": 1,
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "app",
                                "image": "app:latest",
                                "env": [
                                    {"name": "A", "valueFrom": {"secretKeyRef": {"name": "s1", "key": "a"}}},
                                    {"name": "B", "valueFrom": {"secretKeyRef": {"name": "s1", "key": "b"}}},
                                ],
                            }
                        ]
                    }
                },
            },
        }
        result = parse_k8s_resource(doc, "deploy.yaml")
        # s1 referenced twice but should appear once
        assert result["references"].count("k8s://Secret/s1") == 1


class TestMultiDocumentYaml:
    def test_parses_multiple_documents(self):
        content = """apiVersion: v1
kind: Namespace
metadata:
  name: test
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: config
  namespace: test
data:
  key: value
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app
  namespace: test
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: app
          image: app:latest
"""
        results = parse_k8s_file(content, "multi.yaml")
        assert len(results) == 3
        kinds = [r["k8s_kind"] for r in results]
        assert "Namespace" in kinds
        assert "ConfigMap" in kinds
        assert "Deployment" in kinds

    def test_skips_empty_documents(self):
        content = "---\n---\napiVersion: v1\nkind: Namespace\nmetadata:\n  name: test\n---\n"
        results = parse_k8s_file(content, "empty.yaml")
        assert len(results) == 1
        assert results[0]["k8s_kind"] == "Namespace"

    def test_skips_non_k8s_documents(self):
        content = "name: not-k8s\nvalue: 42\n---\napiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: cm"
        results = parse_k8s_file(content, "mixed.yaml")
        assert len(results) == 1

    def test_invalid_yaml_returns_empty(self):
        content = "{{invalid: yaml: [["
        results = parse_k8s_file(content, "bad.yaml")
        assert results == []


class TestEcosystemHandlers:
    def test_argocd_application(self):
        doc = {
            "apiVersion": "argoproj.io/v1alpha1",
            "kind": "Application",
            "metadata": {"name": "my-app", "namespace": "argocd"},
            "spec": {
                "project": "default",
                "source": {
                    "repoURL": "https://github.com/org/repo.git",
                    "path": "manifests",
                    "targetRevision": "main",
                },
                "destination": {"namespace": "prod"},
            },
        }
        result = parse_k8s_resource(doc, "app.yaml")
        assert result["kind"] == "class"
        assert "repo=repo.git" in result["signature"]
        assert "path=manifests" in result["signature"]
        assert "dest=prod" in result["signature"]
        assert "k8s://AppProject/default" in result["references"]

    def test_argocd_multi_source(self):
        doc = {
            "apiVersion": "argoproj.io/v1alpha1",
            "kind": "Application",
            "metadata": {"name": "helm-app", "namespace": "argocd"},
            "spec": {
                "project": "default",
                "sources": [
                    {"repoURL": "https://charts.example.com", "chart": "my-chart", "targetRevision": "1.0.0"},
                    {"repoURL": "https://github.com/org/config.git", "targetRevision": "main", "ref": "values"},
                ],
                "destination": {"namespace": "prod"},
            },
        }
        result = parse_k8s_resource(doc, "app.yaml")
        assert "chart=my-chart" in result["signature"]
        assert "chartVersion=1.0.0" in result["signature"]

    def test_argocd_app_project(self):
        doc = {
            "apiVersion": "argoproj.io/v1alpha1",
            "kind": "AppProject",
            "metadata": {"name": "team-a", "namespace": "argocd"},
            "spec": {
                "description": "Team A project",
                "sourceRepos": ["https://github.com/org/*"],
                "destinations": [{"namespace": "team-a", "server": "https://kubernetes.default.svc"}],
            },
        }
        result = parse_k8s_resource(doc, "project.yaml")
        assert result["kind"] == "class"
        assert '"Team A project"' in result["signature"]
        assert "repos=1" in result["signature"]
        assert "destinations=1" in result["signature"]

    def test_traefik_ingress_route_tcp(self):
        doc = {
            "apiVersion": "traefik.io/v1alpha1",
            "kind": "IngressRouteTCP",
            "metadata": {"name": "tcp-route", "namespace": "default"},
            "spec": {
                "entryPoints": ["websecure"],
                "routes": [{"match": "HostSNI(`*`)", "services": [{"name": "backend-svc", "port": 8080}]}],
            },
        }
        result = parse_k8s_resource(doc, "tcp.yaml")
        assert result["kind"] == "class"
        assert "entryPoints=[websecure]" in result["signature"]
        assert "k8s://Service/backend-svc" in result["references"]

    def test_cert_manager_certificate(self):
        doc = {
            "apiVersion": "cert-manager.io/v1",
            "kind": "Certificate",
            "metadata": {"name": "tls-cert", "namespace": "default"},
            "spec": {
                "dnsNames": ["example.com", "*.example.com"],
                "secretName": "tls-secret",
                "issuerRef": {"name": "letsencrypt", "kind": "ClusterIssuer"},
            },
        }
        result = parse_k8s_resource(doc, "cert.yaml")
        assert "dns=[example.com, *.example.com]" in result["signature"]
        assert "secret=tls-secret" in result["signature"]
        assert "k8s://Secret/tls-secret" in result["references"]
        assert "k8s://ClusterIssuer/letsencrypt" in result["references"]


class TestStripSecretValues:
    def test_strips_data(self):
        doc = {"data": {"key1": "dmFsdWUx", "key2": "dmFsdWUy"}}
        stripped = _strip_secret_values(doc)
        assert stripped["data"]["key1"] == "<redacted>"
        assert stripped["data"]["key2"] == "<redacted>"

    def test_strips_string_data(self):
        doc = {"stringData": {"password": "hunter2"}}
        stripped = _strip_secret_values(doc)
        assert stripped["stringData"]["password"] == "<redacted>"  # noqa: S105

    def test_preserves_other_fields(self):
        doc = {"metadata": {"name": "test"}, "data": {"key": "val"}}
        stripped = _strip_secret_values(doc)
        assert stripped["metadata"]["name"] == "test"

    def test_does_not_modify_original(self):
        doc = {"data": {"key": "original"}}
        _strip_secret_values(doc)
        assert doc["data"]["key"] == "original"


class TestPolicyHandlers:
    def test_hpa(self):
        doc = {
            "apiVersion": "autoscaling/v2",
            "kind": "HorizontalPodAutoscaler",
            "metadata": {"name": "web-hpa", "namespace": "prod"},
            "spec": {
                "minReplicas": 2,
                "maxReplicas": 10,
                "scaleTargetRef": {"kind": "Deployment", "name": "web"},
                "metrics": [{"type": "Resource"}],
            },
        }
        result = parse_k8s_resource(doc, "hpa.yaml")
        assert "min=2" in result["signature"]
        assert "max=10" in result["signature"]
        assert "target=Deployment/web" in result["signature"]
        assert "k8s://Deployment/web" in result["references"]

    def test_pdb(self):
        doc = {
            "apiVersion": "policy/v1",
            "kind": "PodDisruptionBudget",
            "metadata": {"name": "web-pdb"},
            "spec": {
                "minAvailable": 1,
                "selector": {"matchLabels": {"app": "web"}},
            },
        }
        result = parse_k8s_resource(doc, "pdb.yaml")
        assert "minAvailable=1" in result["signature"]
        assert "k8s://Deployment/web" in result["references"]


class TestRbacHandlers:
    def test_role_binding(self):
        doc = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "RoleBinding",
            "metadata": {"name": "admin-binding", "namespace": "prod"},
            "roleRef": {"kind": "Role", "name": "admin"},
            "subjects": [{"kind": "ServiceAccount", "name": "deployer"}],
        }
        result = parse_k8s_resource(doc, "rb.yaml")
        assert "role=Role/admin" in result["signature"]
        assert "subject=ServiceAccount/deployer" in result["signature"]
        assert "k8s://Role/admin" in result["references"]
        assert "k8s://ServiceAccount/deployer" in result["references"]

    def test_service_account_with_irsa(self):
        doc = {
            "apiVersion": "v1",
            "kind": "ServiceAccount",
            "metadata": {
                "name": "s3-reader",
                "namespace": "prod",
                "annotations": {"eks.amazonaws.com/role-arn": "arn:aws:iam::123:role/s3-reader"},
            },
        }
        result = parse_k8s_resource(doc, "sa.yaml")
        assert "arn=s3-reader" in result["signature"]


class TestWorkloadHandlers:
    def test_statefulset(self):
        doc = {
            "apiVersion": "apps/v1",
            "kind": "StatefulSet",
            "metadata": {"name": "redis", "namespace": "cache"},
            "spec": {
                "replicas": 3,
                "template": {"spec": {"containers": [{"name": "redis", "image": "redis:7"}]}},
                "volumeClaimTemplates": [{"metadata": {"name": "data"}}],
            },
        }
        result = parse_k8s_resource(doc, "sts.yaml")
        assert result["kind"] == "class"
        assert "replicas=3" in result["signature"]
        assert "volumeClaims=1" in result["signature"]

    def test_daemonset(self):
        doc = {
            "apiVersion": "apps/v1",
            "kind": "DaemonSet",
            "metadata": {"name": "log-agent"},
            "spec": {
                "template": {
                    "spec": {
                        "containers": [{"name": "agent", "image": "fluentd:latest"}],
                        "nodeSelector": {"role": "worker"},
                    }
                }
            },
        }
        result = parse_k8s_resource(doc, "ds.yaml")
        assert result["kind"] == "class"
        assert "nodeSelector" in result["signature"]

    def test_job(self):
        doc = {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {"name": "migrate"},
            "spec": {
                "completions": 1,
                "parallelism": 1,
                "template": {"spec": {"containers": [{"name": "migrate", "image": "app:latest"}]}},
            },
        }
        result = parse_k8s_resource(doc, "job.yaml")
        assert result["kind"] == "class"
        assert "completions=1" in result["signature"]

    def test_cronjob(self):
        doc = {
            "apiVersion": "batch/v1",
            "kind": "CronJob",
            "metadata": {"name": "backup"},
            "spec": {
                "schedule": "0 2 * * *",
                "jobTemplate": {
                    "spec": {"template": {"spec": {"containers": [{"name": "backup", "image": "backup:v1"}]}}}
                },
            },
        }
        result = parse_k8s_resource(doc, "cron.yaml")
        assert 'schedule="0 2 * * *"' in result["signature"]

    def test_replicaset(self):
        doc = {
            "apiVersion": "apps/v1",
            "kind": "ReplicaSet",
            "metadata": {"name": "web-rs"},
            "spec": {
                "replicas": 2,
                "template": {"spec": {"containers": [{"name": "web", "image": "web:v1"}]}},
            },
        }
        result = parse_k8s_resource(doc, "rs.yaml")
        assert "replicas=2" in result["signature"]

    def test_pod(self):
        doc = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": "debug"},
            "spec": {
                "containers": [{"name": "debug", "image": "busybox"}],
                "nodeName": "node-1",
            },
        }
        result = parse_k8s_resource(doc, "pod.yaml")
        assert "node=node-1" in result["signature"]

    def test_env_from_secret_ref(self):
        doc = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "app"},
            "spec": {
                "replicas": 1,
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "app",
                                "image": "app:latest",
                                "envFrom": [{"secretRef": {"name": "env-secret"}}],
                            }
                        ]
                    }
                },
            },
        }
        result = parse_k8s_resource(doc, "deploy.yaml")
        assert "k8s://Secret/env-secret" in result["references"]

    def test_env_from_configmap_ref(self):
        doc = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "app"},
            "spec": {
                "replicas": 1,
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "app",
                                "image": "app:latest",
                                "envFrom": [{"configMapRef": {"name": "env-config"}}],
                            }
                        ]
                    }
                },
            },
        }
        result = parse_k8s_resource(doc, "deploy.yaml")
        assert "k8s://ConfigMap/env-config" in result["references"]

    def test_volume_secret_ref(self):
        doc = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "app"},
            "spec": {
                "replicas": 1,
                "template": {
                    "spec": {
                        "containers": [{"name": "app", "image": "app:latest"}],
                        "volumes": [{"name": "tls", "secret": {"secretName": "tls-cert"}}],
                    }
                },
            },
        }
        result = parse_k8s_resource(doc, "deploy.yaml")
        assert "k8s://Secret/tls-cert" in result["references"]

    def test_volume_configmap_ref(self):
        doc = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "app"},
            "spec": {
                "replicas": 1,
                "template": {
                    "spec": {
                        "containers": [{"name": "app", "image": "app:latest"}],
                        "volumes": [{"name": "cfg", "configMap": {"name": "app-config"}}],
                    }
                },
            },
        }
        result = parse_k8s_resource(doc, "deploy.yaml")
        assert "k8s://ConfigMap/app-config" in result["references"]


class TestNetworkingHandlers:
    def test_ingress_with_tls(self):
        doc = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": {"name": "web-ingress"},
            "spec": {
                "tls": [{"hosts": ["example.com"], "secretName": "tls-secret"}],
                "rules": [
                    {
                        "host": "example.com",
                        "http": {"paths": [{"path": "/", "backend": {"service": {"name": "web-svc"}}}]},
                    }
                ],
            },
        }
        result = parse_k8s_resource(doc, "ingress.yaml")
        assert "hosts=[example.com]" in result["signature"]
        assert "tls=true" in result["signature"]
        assert "k8s://Secret/tls-secret" in result["references"]
        assert "k8s://Service/web-svc" in result["references"]

    def test_ingress_class(self):
        doc = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "IngressClass",
            "metadata": {"name": "nginx"},
            "spec": {"controller": "k8s.io/ingress-nginx"},
        }
        result = parse_k8s_resource(doc, "ic.yaml")
        assert "controller=k8s.io/ingress-nginx" in result["signature"]

    def test_network_policy(self):
        doc = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {"name": "deny-all"},
            "spec": {
                "podSelector": {"matchLabels": {"app": "web"}},
                "policyTypes": ["Ingress", "Egress"],
                "ingress": [{"from": [{"podSelector": {}}]}],
                "egress": [],
            },
        }
        result = parse_k8s_resource(doc, "np.yaml")
        assert "types=[Ingress, Egress]" in result["signature"]
        assert "ingress_rules=1" in result["signature"]
        assert "k8s://Deployment/web" in result["references"]

    def test_endpoints(self):
        doc = {
            "apiVersion": "v1",
            "kind": "Endpoints",
            "metadata": {"name": "external-db"},
        }
        result = parse_k8s_resource(doc, "ep.yaml")
        assert result is not None
        assert result["kind"] == "constant"  # unknown kind defaults to constant


class TestStorageHandlers:
    def test_pvc(self):
        doc = {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {"name": "data-pvc"},
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "storageClassName": "ssd",
                "resources": {"requests": {"storage": "10Gi"}},
            },
        }
        result = parse_k8s_resource(doc, "pvc.yaml")
        assert "access=[ReadWriteOnce]" in result["signature"]
        assert "class=ssd" in result["signature"]
        assert "size=10Gi" in result["signature"]

    def test_pv(self):
        doc = {
            "apiVersion": "v1",
            "kind": "PersistentVolume",
            "metadata": {"name": "nfs-pv"},
            "spec": {
                "capacity": {"storage": "100Gi"},
                "accessModes": ["ReadWriteMany"],
                "persistentVolumeReclaimPolicy": "Retain",
            },
        }
        result = parse_k8s_resource(doc, "pv.yaml")
        assert "capacity=100Gi" in result["signature"]
        assert "access=[ReadWriteMany]" in result["signature"]
        assert "reclaim=Retain" in result["signature"]

    def test_storage_class(self):
        doc = {
            "apiVersion": "storage.k8s.io/v1",
            "kind": "StorageClass",
            "metadata": {"name": "fast-ssd"},
            "provisioner": "kubernetes.io/aws-ebs",
            "reclaimPolicy": "Delete",
        }
        result = parse_k8s_resource(doc, "sc.yaml")
        assert "provisioner=kubernetes.io/aws-ebs" in result["signature"]
        assert "reclaim=Delete" in result["signature"]


class TestAdditionalPolicyHandlers:
    def test_limit_range(self):
        doc = {
            "apiVersion": "v1",
            "kind": "LimitRange",
            "metadata": {"name": "default-limits", "namespace": "prod"},
            "spec": {"limits": [{"type": "Container", "default": {"cpu": "500m", "memory": "256Mi"}}]},
        }
        result = parse_k8s_resource(doc, "lr.yaml")
        assert "Container:" in result["signature"]
        assert "cpu=500m" in result["signature"]

    def test_resource_quota(self):
        doc = {
            "apiVersion": "v1",
            "kind": "ResourceQuota",
            "metadata": {"name": "team-quota", "namespace": "team-a"},
            "spec": {"hard": {"pods": "20", "requests.cpu": "10", "requests.memory": "32Gi"}},
        }
        result = parse_k8s_resource(doc, "rq.yaml")
        assert "hard=[" in result["signature"]
        assert "pods=20" in result["signature"]

    def test_priority_class(self):
        doc = {
            "apiVersion": "scheduling.k8s.io/v1",
            "kind": "PriorityClass",
            "metadata": {"name": "high-priority"},
            "value": 1000000,
            "globalDefault": False,
        }
        result = parse_k8s_resource(doc, "pc.yaml")
        assert "value=1000000" in result["signature"]

    def test_priority_class_global_default(self):
        doc = {
            "apiVersion": "scheduling.k8s.io/v1",
            "kind": "PriorityClass",
            "metadata": {"name": "default-priority"},
            "value": 0,
            "globalDefault": True,
        }
        result = parse_k8s_resource(doc, "pc.yaml")
        assert "globalDefault=true" in result["signature"]

    def test_runtime_class(self):
        doc = {
            "apiVersion": "node.k8s.io/v1",
            "kind": "RuntimeClass",
            "metadata": {"name": "nvidia"},
            "handler": "nvidia",
        }
        result = parse_k8s_resource(doc, "rc.yaml")
        assert "handler=nvidia" in result["signature"]


class TestAdditionalRbacHandlers:
    def test_role(self):
        doc = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "Role",
            "metadata": {"name": "pod-reader", "namespace": "default"},
            "rules": [
                {"apiGroups": [""], "resources": ["pods", "pods/log"], "verbs": ["get", "list"]},
                {"apiGroups": [""], "resources": ["configmaps"], "verbs": ["get"]},
            ],
        }
        result = parse_k8s_resource(doc, "role.yaml")
        assert "rules=2" in result["signature"]
        assert "configmaps" in result["signature"]
        assert "pods" in result["signature"]

    def test_cluster_role(self):
        doc = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRole",
            "metadata": {"name": "node-viewer"},
            "rules": [{"apiGroups": [""], "resources": ["nodes"], "verbs": ["get", "list"]}],
        }
        result = parse_k8s_resource(doc, "cr.yaml")
        assert "rules=1" in result["signature"]
        assert "nodes" in result["signature"]

    def test_cluster_role_binding(self):
        doc = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRoleBinding",
            "metadata": {"name": "admin-binding"},
            "roleRef": {"kind": "ClusterRole", "name": "cluster-admin"},
            "subjects": [{"kind": "User", "name": "admin@example.com"}],
        }
        result = parse_k8s_resource(doc, "crb.yaml")
        assert "role=ClusterRole/cluster-admin" in result["signature"]
        assert "subject=User/admin@example.com" in result["signature"]
        assert "k8s://ClusterRole/cluster-admin" in result["references"]


class TestAdditionalEcosystemHandlers:
    def test_argocd_application_set(self):
        doc = {
            "apiVersion": "argoproj.io/v1alpha1",
            "kind": "ApplicationSet",
            "metadata": {"name": "team-apps", "namespace": "argocd"},
            "spec": {
                "generators": [{"git": {"repoURL": "https://github.com/org/apps.git"}}],
                "template": {"spec": {"destination": {"namespace": "prod"}}},
            },
        }
        result = parse_k8s_resource(doc, "appset.yaml")
        assert "generators=[git]" in result["signature"]
        assert "dest=prod" in result["signature"]

    def test_traefik_ingress_route_http(self):
        doc = {
            "apiVersion": "traefik.io/v1alpha1",
            "kind": "IngressRoute",
            "metadata": {"name": "web-route"},
            "spec": {
                "entryPoints": ["web", "websecure"],
                "routes": [
                    {
                        "match": "Host(`example.com`)",
                        "services": [{"name": "web-svc", "port": 80}],
                    }
                ],
            },
        }
        result = parse_k8s_resource(doc, "route.yaml")
        assert "entryPoints=[web, websecure]" in result["signature"]
        assert "hosts=[example.com]" in result["signature"]
        assert "k8s://Service/web-svc" in result["references"]

    def test_traefik_middleware(self):
        doc = {
            "apiVersion": "traefik.io/v1alpha1",
            "kind": "Middleware",
            "metadata": {"name": "rate-limit"},
            "spec": {"rateLimit": {"average": 100, "burst": 200}},
        }
        result = parse_k8s_resource(doc, "mw.yaml")
        assert "type=rateLimit" in result["signature"]

    def test_cert_manager_issuer(self):
        doc = {
            "apiVersion": "cert-manager.io/v1",
            "kind": "Issuer",
            "metadata": {"name": "letsencrypt-prod", "namespace": "default"},
            "spec": {"acme": {"server": "https://acme-v02.api.letsencrypt.org/directory"}},
        }
        result = parse_k8s_resource(doc, "issuer.yaml")
        assert "type=ACME" in result["signature"]
        assert "server=letsencrypt" in result["signature"]

    def test_cert_manager_cluster_issuer_self_signed(self):
        doc = {
            "apiVersion": "cert-manager.io/v1",
            "kind": "ClusterIssuer",
            "metadata": {"name": "self-signed"},
            "spec": {"selfSigned": {}},
        }
        result = parse_k8s_resource(doc, "ci.yaml")
        assert "type=self-signed" in result["signature"]

    def test_traefik_ingress_route_udp(self):
        doc = {
            "apiVersion": "traefik.io/v1alpha1",
            "kind": "IngressRouteUDP",
            "metadata": {"name": "dns-route"},
            "spec": {
                "entryPoints": ["dns-udp"],
                "routes": [{"services": [{"name": "dns-svc", "port": 53}]}],
            },
        }
        result = parse_k8s_resource(doc, "udp.yaml")
        assert "k8s://Service/dns-svc" in result["references"]


class TestContentHandlerRegistration:
    def test_k8s_sniffer_registered(self):
        from sylvan.extensions import _registered_content_handlers

        names = [h["name"] for h in _registered_content_handlers]
        assert "kubernetes" in names

    def test_sniffer_matches_k8s_yaml(self):
        from sylvan.extensions import get_content_handler

        content = "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: test"
        handler = get_content_handler("deploy.yaml", content)
        assert handler is not None

    def test_sniffer_rejects_non_yaml(self):
        from sylvan.extensions import get_content_handler

        handler = get_content_handler("main.py", "import os\nprint('hello')")
        assert handler is None

    def test_sniffer_rejects_plain_yaml(self):
        from sylvan.extensions import get_content_handler

        handler = get_content_handler("config.yaml", "name: test\nvalue: 42")
        assert handler is None

    def test_sniffer_rejects_non_yaml_extension(self):
        from sylvan.extensions import get_content_handler

        content = "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: test"
        handler = get_content_handler("readme.md", content)
        assert handler is None


class TestExternalSecretVariations:
    def test_data_field_mapping(self):
        doc = {
            "apiVersion": "external-secrets.io/v1",
            "kind": "ExternalSecret",
            "metadata": {"name": "mixed-secrets", "namespace": "prod"},
            "spec": {
                "secretStoreRef": {"name": "vault", "kind": "ClusterSecretStore"},
                "target": {"name": "mixed-secrets"},
                "data": [
                    {"secretKey": "DB_URL", "remoteRef": {"key": "secret/data/db", "property": "url"}},
                    {"secretKey": "API_KEY", "remoteRef": {"key": "secret/data/api", "property": "key"}},
                ],
            },
        }
        result = parse_k8s_resource(doc, "es.yaml")
        assert (
            "sources=[secret/data/api, secret/data/db]" in result["signature"]
            or "sources=[secret/data/db, secret/data/api]" in result["signature"]
        )

    def test_secret_with_argocd_repo_label(self):
        doc = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": "my-repo",
                "namespace": "argocd",
                "labels": {"argocd.argoproj.io/secret-type": "repository"},
            },
            "stringData": {"type": "git", "url": "ssh://git@github.com/org/repo.git"},
        }
        result = parse_k8s_resource(doc, "repo.yaml")
        assert "argocd-type=repository" in result["signature"]
        assert "url=repo.git" in result["signature"]
