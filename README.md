# OpenShift / RHACM / GitOps Practical Assignment

## Overview

This repository contains the implementation artifacts and selected evidence for the practical assignment.

The solution demonstrates:

- Two Single Node OpenShift clusters: `cluster1` and `cluster2`
- `cluster1` configured as the RHACM Hub
- `cluster2` imported and managed through RHACM
- OpenShift GitOps / Argo CD
- RHACM policy management and enforcement
- CLI and OpenShift Console login banners
- Prevention of namespace creation with names beginning with `test`
- Operator installation through RHACM policy
- A practical SRE monitoring application
- GitOps-based application deployment to `cluster2`
- Monitoring and operational troubleshooting
- Rollback using Git and Argo CD

## Environment and Access

### Domain

```text
etcd.store
```

### AWS Region

```text
Mumbai (ap-south-1)
```

### Cluster1

API:

```text
https://api.cluster1.etcd.store:6443
```

OpenShift Console:

```text
https://console-openshift-console.apps.cluster1.etcd.store
```

### Cluster2

API:

```text
https://api.cluster2.etcd.store:6443
```

OpenShift Console:

```text
https://console-openshift-console.apps.cluster2.etcd.store
```

### SRE Application

```text
https://sre.etcd.store
```

### Jump Host

A jump host is available in the Mumbai AWS region and can be used to access the OpenShift environments through the CLI and to reach the cluster consoles.

The following shortcuts are configured on the jump host:

```text
c1    -> login/access to cluster1
c2    -> login/access to cluster2
```

Cluster credentials are provided separately through a secure channel and are not stored in this repository.

## AWS Cost / Environment Status

The assessment environment is hosted in the AWS Mumbai region and incurs AWS cost while resources are running.

To reduce the cost during the assessment, the OpenShift VM instance type was downgraded to:

```text
t3.2xlarge
```

The VMs are kept **OFF when they are not required**.

**Please turn off the VMs after completing the assessment to avoid unnecessary ongoing AWS charges.**

## Repository Structure

```text
OpenShift_ACM_GitOps_Assignment/
├── README.md
├── app.py
├── Dockerfile
│
├── acm/
│   ├── policies/
│   ├── placements/
│   └── bindings/
│
├── gitops/
├── operators/
├── application/
├── cluster-config/
├── tls/
└── snapshots/
```

## Architecture

```text
                         Git Repository
                              |
                              v
                     OpenShift GitOps
                         Argo CD
                              |
                         ApplicationSet
                              |
                              v
+------------------------------------------------------+
| cluster1 - RHACM Hub                                 |
|                                                      |
|  Policies / Placements / ManagedCluster              |
+-----------------------------+------------------------+
                              |
                              v
                     cluster2 - Managed SNO
                              |
             +----------------+----------------+
             |                |                |
          Policies         Operators       GitOps App
             |                |                |
       Admission/TLS      Logging/Cert      SRE Monitor
                                               |
                                      /healthz /ready
                                      /metrics /api
```

## 1. Two Single Node OpenShift Clusters

Two Single Node OpenShift clusters were created: `cluster1` and `cluster2`.

Sanitized installation configuration examples are included under `cluster-config/`.

## 2. RHACM Hub and OpenShift GitOps

`cluster1` is configured as the RHACM Hub. OpenShift GitOps is installed on the Hub and uses Argo CD for GitOps-based application deployment.

## 3. Cluster2 Managed by RHACM

`cluster2` is imported into RHACM and selected through the `cluster2` placement.

## 4. Login Banner Policy

The `policy-login-banner` policy is targeted to `cluster2` and manages the CLI warning configuration and OpenShift Console notification.

The policy uses:

```yaml
remediationAction: enforce
```

The policy is associated with NIST SP 800-53 AC-8 System Use Notification.

## 5. Prevent `test*` Namespace Creation

A Kubernetes `ValidatingAdmissionPolicy` is deployed through RHACM to prevent creation of namespaces whose names begin with `test`.

The admission expression is:

```text
!object.metadata.name.startsWith('test')
```

The binding uses:

```yaml
validationActions:
  - Deny
```

Example:

```bash
oc create namespace test-project
```

The request is rejected.

## 6. Operator Installation Through Policy

Operators are installed/configured through RHACM policies. The implementation includes cert-manager.

## 7. SRE Application

The SRE monitoring application is implemented in Python and deployed to `cluster2`.

Endpoints:

| Endpoint | Purpose |
|---|---|
| `/` | Web dashboard |
| `/api` | JSON health information |
| `/metrics` | Prometheus-compatible metrics |
| `/healthz` | Liveness |
| `/ready` | Readiness |

The application monitors node health, pod health, container restarts, deployment availability and ClusterOperator status. It uses read-only Kubernetes/OpenShift permissions.

## 8. ACM + GitOps Deployment

The application is stored in Git and deployed using OpenShift GitOps / Argo CD. The ApplicationSet uses an ACM placement decision to target `cluster2`.

```text
Git
 |
 v
Argo CD ApplicationSet
 |
 v
ACM Placement Decision
 |
 v
cluster2
 |
 v
SRE Monitor
```

Automated synchronization and self-healing are enabled.

## 9. Rollback, Policy Enforcement and Troubleshooting

### Deliberately Introduced Failure

A simple application failure scenario is used. The working Deployment contains a valid container image. The image is deliberately changed in the Git-managed Deployment to an invalid image:

```yaml
containers:
  - name: sre-monitor
    image: invalid-image:does-not-exist
```

After committing and pushing the change, Argo CD detects it and synchronizes the Deployment to `cluster2`. The application pod enters a state such as `ImagePullBackOff` or `ErrImagePull`.

### Troubleshooting

```bash
oc get pods -n sre-monitor
oc describe pod <pod-name> -n sre-monitor
oc get deployment sre-monitor -n sre-monitor
oc get deployment sre-monitor -n sre-monitor \
  -o jsonpath='{.spec.template.spec.containers[0].image}'
oc get events -n sre-monitor --sort-by=.lastTimestamp
```

The configured image is compared with the Git version and the incorrect image reference is identified as the root cause.

### Rollback

The incorrect Git commit is reverted rather than manually editing the live Deployment.

```text
Incorrect image committed
        |
        v
Argo CD synchronization
        |
        v
ImagePullBackOff
        |
        v
Troubleshoot
        |
        v
Git revert
        |
        v
Argo CD detects Git change
        |
        v
Previous working image synchronized
        |
        v
Application healthy
```

This keeps Git as the source of truth and avoids configuration drift.

## 10. Monitoring

RHACM provides centralized visibility of the managed cluster and policy compliance. The SRE monitor provides an operational view of nodes, pods, deployments, container restarts and ClusterOperators.

## Evidence

The `snapshots/` directory contains the selected implementation screenshots covering the completed tasks, including RHACM, policies, operators, GitOps, monitoring, the SRE application and namespace policy enforcement.

## Security

Credentials are not stored in this repository. Passwords, private SSH keys, OpenShift pull secrets, AWS access keys and cloud secret access keys must be provided separately through a secure channel.


## Lab Repository Visibility

For this assessment/lab purpose, the GitHub repository and Docker Hub image repository are intentionally kept public to simplify access and demonstrate the GitOps workflow. This is a lab convenience and is not the recommended production security posture. No production secrets should be stored in either repository.
