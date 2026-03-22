# OPA vs YAML-Based Policy Engines for AI Agent Access Control

**Research Date:** 2026-03-22

---

## 1. OPA (Open Policy Agent) / Rego

### 1.1 Architecture

OPA is a CNCF-graduated, general-purpose policy engine that decouples policy decisions from application logic. It accepts structured data (JSON/YAML) as input, evaluates it against Rego policies, and returns structured decisions.

**Deployment models:**

| Model | How It Works | Latency | Use When |
|-------|-------------|---------|----------|
| **Sidecar/Daemon** | OPA runs as a separate process on the same host. App queries it over localhost HTTP (port 8181). | Sub-millisecond network + eval time | Microservices, Kubernetes pods |
| **Go Library** | OPA embedded directly via `github.com/open-policy-agent/opa/v1/rego` package. No network hop. | Fastest (pure in-process) | Go applications only |
| **REST API** | OPA runs as a standalone service. App queries `POST /v1/data/<path>`. | Fast but includes network round-trip | Polyglot environments |
| **WASM** | Rego compiled to WebAssembly. Embeddable in any language with a Wasm runtime. | Between REST and Go library | Edge, browser, non-Go apps |

**Key architectural principle:** OPA operates on pre-loaded, in-memory data. Policy decisions never require database lookups at evaluation time -- all data is pushed to OPA ahead of time via bundles or the data API.

### 1.2 Rego Policy Language

Rego is a declarative language derived from Datalog. Policies are deny-by-default, expressed as rules that evaluate to true/false or produce sets/objects.

**Complete API authorization example:**

```rego
package authz

import rego.v1

# Default deny
default allow := false

# Allow GET requests from users with "reader" role
allow if {
    input.method == "GET"
    "reader" in input.user.roles
}

# Allow POST requests from users with "writer" role
allow if {
    input.method == "POST"
    "writer" in input.user.roles
}

# Allow users to access their own resources
allow if {
    input.method == "GET"
    input.path = ["users", user_id]
    input.user.id == user_id
}

# Admin bypass
allow if {
    "admin" in input.user.roles
}
```

**Input to OPA (JSON):**
```json
{
  "method": "GET",
  "path": ["users", "bob"],
  "user": {
    "id": "bob",
    "roles": ["reader"]
  }
}
```

**Kubernetes admission control example:**

```rego
package kubernetes.admission

import rego.v1

deny contains msg if {
    input.request.kind.kind == "Pod"
    some container in input.request.object.spec.containers
    not startswith(container.image, "registry.internal.com/")
    msg := sprintf("Container '%s' uses untrusted image: %s", [container.name, container.image])
}

deny contains msg if {
    input.request.kind.kind == "Pod"
    some container in input.request.object.spec.containers
    not container.resources.limits
    msg := sprintf("Container '%s' must specify resource limits", [container.name])
}
```

### 1.3 OPA Use Cases

| Use Case | How OPA Fits |
|----------|-------------|
| **API authorization** | Service queries OPA on each request with method, path, user claims. OPA returns allow/deny. |
| **Kubernetes admission control** | OPA Gatekeeper acts as a validating webhook. Evaluates pod specs, deployments, etc. against Rego policies. |
| **Data filtering** | Partial evaluation produces residual queries that can be pushed down to databases (e.g., SQL WHERE clauses). |
| **Infrastructure-as-code** | Conftest validates Terraform plans, Dockerfiles, K8s manifests against Rego policies in CI/CD. |
| **Envoy external authorization** | OPA-Envoy plugin evaluates authorization for every request passing through the service mesh. |

### 1.4 OPA for AI Agents -- Existing Patterns

**Red Hat MCP Gateway (2025):** OPA is used to enforce tool-level access control for AI agents in a Model Context Protocol gateway. The architecture works as follows:

1. Keycloak stores per-user tool permissions as client roles
2. OPA extracts tool permissions from JWT `resource_access` claims
3. A "wristband" feature creates signed JWTs containing allowed tools mappings
4. The broker validates signatures and filters tool responses

**Rego policy for MCP tool extraction:**

```rego
tools = { server: roles |
    server := object.keys(input.auth.identity.resource_access)[_]
    roles := object.get(input.auth.identity.resource_access, server, {}).roles
}
```

This produces a structure like `{"server1.mcp.local": ["greet", "time"], "server2.mcp.local": ["headers"]}`.

**Three-layer verification for tool calls:**
1. **Tool Visibility** -- broker filters `tools/list` based on permitted tools from the wristband header
2. **Audience Verification** -- token exchange ensures `aud` claim matches target server only
3. **Permission Checking** -- request-time validation confirms users can access specific tools via `x-mcp-toolname` header

### 1.5 Performance Characteristics

**Target latency budget:** For microservice API authorization, policy evaluation has a budget on the order of **1 millisecond**.

| Integration | Typical Latency | Notes |
|-------------|----------------|-------|
| Go library (prepared query) | **< 0.1 ms** | No network hop, pre-compiled |
| WASM | **0.1 - 0.5 ms** | In-process, compiled to native-speed instructions |
| REST API (localhost) | **0.5 - 2 ms** | Includes HTTP overhead on loopback |
| REST API (remote) | **2 - 10 ms** | Network-dependent |

**Key performance considerations:**
- OPA-Envoy plugin adds measurable latency: between 90th and 99th percentile, at least 2x compared to Envoy alone
- The `opa_eval` WASM fast-path (added in v0.31.0) significantly speeds embedded evaluation
- Policy complexity matters: linear rules evaluate faster than rules requiring iteration over large datasets
- OPA operates on in-memory data, so evaluation speed depends on data size, not I/O

**Cedar comparison (independent benchmarks):** Cedar (Rust-based) has been measured at **42-60x faster** than Rego for equivalent authorization policies, according to Trail of Bits security assessment. However, Cedar is limited to PARC-model (Principal/Action/Resource/Condition) boolean decisions only.

### 1.6 Policy Management, Versioning, and Bundles

**OPA Bundles** are the standard mechanism for distributing policies in production:

- A bundle is a gzip-compressed tar archive containing Rego files, JSON/YAML data files, and a manifest
- OPA instances periodically pull bundles from a remote HTTP server
- Policies are loaded atomically -- no partial updates
- Bundle signing with public keys prevents tampering
- Updates are hot-loaded without OPA restart

**Typical production workflow:**
1. Developers author Rego policies in Git
2. CI/CD pipeline runs `opa test` and builds a bundle
3. Bundle is pushed to an HTTP server (S3, GCS, or Styra DAS)
4. OPA instances pull the new bundle and activate it
5. If signature verification fails, OPA keeps the old bundle and reports an error

**Multiple bundle strategy:** Data and policy can come from separate bundles updated at different rates (e.g., role mappings change hourly, policy logic changes weekly).

### 1.7 Partial Evaluation

Partial evaluation lets OPA produce **residual policies** when some inputs are unknown at query time. This is used to:

- Generate SQL WHERE clauses for data filtering
- Compile policies to conditions that can be evaluated closer to the data
- Pre-compute decisions when only some context is available

Example: If the policy says "allow if user.department == resource.department" and you know the user but not the resource, partial evaluation returns a residual condition that can be pushed to the database query.

**WASM partial evaluation** is under active development (GitHub issue #3407) to bring this capability to embedded environments.

### 1.8 Integration Patterns Summary

| Pattern | Language | Overhead | Management Features |
|---------|----------|----------|-------------------|
| REST API (`/v1/data/`) | Any | HTTP round-trip | Full (bundles, logs, status) |
| Go SDK (`opa/v1/sdk`) | Go | None | Full (bundles, decision logs) |
| Go Rego package | Go | None | Manual only |
| WASM | Any with Wasm runtime | Minimal | Manual only |
| Envoy plugin (gRPC) | Envoy mesh | gRPC call | Full |

### 1.9 Enterprise Adoption

**Known financial services adopters:**

| Company | Use Case |
|---------|----------|
| **Goldman Sachs** | Cloud Entitlements Service (OCES) -- multi-tenant OPA on ECS Fargate, multi-regional, policies authored in GitLab with CI/CD. Also Kubernetes admission control in multi-tenant clusters. |
| **Capital One** | Validating admission controller across Kubernetes clusters: image registry allowlisting, label requirements, resource requirements, container privileges. |
| **BNY Mellon** | OPA as sidecar to enforce access control based on Active Directory and internal service context. |
| **Marsh McLennan** | OPA Gatekeeper in Kubernetes + OPA as authorization decision point for ingress traffic. |
| **State Street Corporation** | Early production/testing stage. |

Other major adopters: Netflix, Pinterest, Atlassian, Chef, Cloudflare, Intuit, SAP, Tripadvisor, Yelp.

**Note:** Apple hired the OPA maintainers in August 2025, and OPA was originally created by Styra.

### 1.10 Styra DAS

Styra DAS is the commercial management platform for OPA:

- **Policy authoring and collaboration** with impact analysis
- **Decision logging** with compliance monitoring
- **Pre-built policy libraries** for NIST SP 800-190, PCI DSS, MITRE ATT&CK, CIS Benchmarks, Pod Security
- **Enterprise OPA** provides better performance, native data source integrations, and decision analysis
- **Terraform provider** for infrastructure-as-code management of policies
- **24/7/365 support** on enterprise tier
- Pricing is per-system (starts at 10 systems)

---

## 2. YAML-Based Policy Engines

### 2.1 NVIDIA NemoClaw / OpenShell

NemoClaw is NVIDIA's enterprise security layer for AI agents, built on OpenShell (open-source agent sandbox runtime). It enforces **deny-by-default** policies written in declarative YAML.

**Policy schema (4 protection domains):**

| Domain | Category | Hot-Reloadable? |
|--------|----------|----------------|
| **Filesystem** | Static | No (locked at sandbox creation) |
| **Network** | Dynamic | Yes |
| **Process** | Static | No |
| **Inference** | Dynamic | Yes |

**Complete OpenShell policy example:**

```yaml
version: 1

filesystem_policy:
  include_workdir: true
  read_only:
    - /usr
    - /lib
    - /proc
    - /dev/urandom
    - /etc
  read_write:
    - /sandbox
    - /tmp
    - /dev/null

landlock:
  compatibility: best_effort

process:
  run_as_user: sandbox
  run_as_group: sandbox

network_policies:
  github_rest_api:
    name: github-rest-api
    endpoints:
      - host: api.github.com
        port: 443
        protocol: rest
        tls: terminate
        enforcement: enforce
        access: read-only          # Permits GET, HEAD, OPTIONS only
    binaries:
      - path: /usr/local/bin/claude
      - path: /usr/bin/node
      - path: /usr/bin/gh

  npm_registry:
    name: npm-registry
    endpoints:
      - host: registry.npmjs.org
        port: 443
    binaries:
      - path: /usr/bin/npm
      - path: /usr/bin/node

  git_operations:
    name: git-endpoints
    endpoints:
      - host: github.com
        port: 443
        protocol: rest
        tls: terminate
        enforcement: enforce
    binaries:
      - path: /usr/bin/git
```

**Access levels in network policy:**

| Value | Allowed HTTP Methods |
|-------|---------------------|
| `full` | All methods and paths |
| `read-only` | GET, HEAD, OPTIONS |
| `read-write` | GET, HEAD, OPTIONS, POST, PUT, PATCH |

**Fine-grained path rules:**

```yaml
rules:
  - allow:
      method: GET
      path: /**/info/refs*
  - allow:
      method: POST
      path: /**/git-upload-pack
```

**Key constraints:** Max 4096 chars per path, 256 total path entries, no `..` traversal, no root-level read-write.

**Evaluation model:** OpenShell enforces at the OS/process level (Landlock LSM for filesystem, network proxy with TLS termination for HTTP inspection). This is fundamentally different from OPA -- it's a runtime sandbox, not a policy decision point.

### 2.2 Casbin

Casbin is an authorization library (not a standalone engine) available in Go, Java, Node.js, Python, .NET, Rust, PHP, and Elixir. It uses the **PERM metamodel** (Policy, Effect, Request, Matchers) defined in CONF files.

**RBAC model (model.conf):**

```ini
[request_definition]
r = sub, obj, act

[policy_definition]
p = sub, obj, act

[role_definition]
g = _, _

[policy_effect]
e = some(where (p.eft == allow))

[matchers]
m = g(r.sub, p.sub) && r.obj == p.obj && r.act == p.act
```

**Policy file (policy.csv):**

```csv
p, admin, /api/users, read
p, admin, /api/users, write
p, viewer, /api/users, read
g, alice, admin
g, bob, viewer
```

**ABAC model:**

```ini
[request_definition]
r = sub, obj, act

[policy_definition]
p = sub_rule, obj, act

[policy_effect]
e = some(where (p.eft == allow))

[matchers]
m = eval(p.sub_rule) && r.obj == p.obj && r.act == p.act
```

**ABAC policy:**

```csv
p, r.sub.Age > 18, /data1, read
p, r.sub.Age < 60, /data2, write
```

**Key differences from OPA:**
- Simpler DSL, easier to read than Rego
- Less flexible -- designed specifically for access control, not general-purpose policy
- Embedded library (no sidecar/daemon model by default)
- Supports ACL, RBAC, ABAC through configuration
- No built-in bundle distribution, decision logging, or partial evaluation

### 2.3 AWS IAM Policy Model (JSON)

AWS IAM uses a JSON-based policy language with the structure:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::123456789012:user/alice"},
      "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": "arn:aws:s3:::my-bucket/*",
      "Condition": {
        "StringEquals": {
          "s3:prefix": ["home/alice/"]
        },
        "IpAddress": {
          "aws:SourceIp": "192.168.1.0/24"
        }
      }
    }
  ]
}
```

**Relevance to agent access control:** IAM's model of Effect + Action + Resource + Condition maps well to agent tool authorization (Effect=Allow, Action=tool_name, Resource=context_id, Condition=approval_status).

### 2.4 Kubernetes RBAC (YAML)

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: production
  name: pod-reader
rules:
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  namespace: production
  name: read-pods
subjects:
  - kind: User
    name: alice
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: pod-reader
  apiGroup: rbac.authorization.k8s.io
```

**Limitations for agent use case:** K8s RBAC only supports verb+resource matching. No conditional logic, no attribute-based decisions, no context-aware evaluation.

### 2.5 Cedar (AWS)

Cedar is AWS's purpose-built authorization policy language, focused on readability and formal verification.

**Basic permit:**

```cedar
permit(
  principal == User::"alice",
  action == Action::"view",
  resource == Photo::"VacationPhoto94.jpg"
);
```

**Attribute-based with conditions:**

```cedar
permit(
  principal,
  action in [Action::"listPhotos", Action::"view"],
  resource in Album::"device_prototypes"
)
when {
  principal.department == "HardwareEngineering" &&
  principal.jobLevel >= 5
};
```

**Deny with exceptions:**

```cedar
forbid(
  principal,
  action,
  resource
)
when {
  resource.private
}
unless {
  principal == resource.owner
};
```

**Cedar vs OPA comparison:**

| Dimension | Cedar | OPA/Rego |
|-----------|-------|---------|
| **Language** | Functional, PARC-model | Datalog-derived, general-purpose |
| **Performance** | 42-60x faster than Rego (Trail of Bits) | Sub-millisecond but slower than Cedar |
| **Safety** | Formal verification, deterministic | Community-driven testing |
| **Scope** | Authorization only (boolean permit/forbid) | General-purpose (any JSON/YAML decision) |
| **Output** | Boolean only | Arbitrary structured data |
| **Ecosystem** | AWS Verified Permissions, growing | CNCF, Kubernetes, Envoy, massive |
| **Readability** | High (designed for non-engineers) | Moderate to low (requires Rego expertise) |
| **Flexibility** | No helper functions, no iteration, no non-boolean decisions | Full programming language capabilities |

---

## 3. Direct Comparison for Agent Tool Access Control

### 3.1 The Use Case

Every tool call an AI agent makes must be evaluated against policy. The policy check must consider:
- **Tool name** (e.g., `update_compliance_status`, `get_account_details`)
- **context_id boundary** (agent can only operate within its assigned context)
- **Data scope** (which data the agent can read/write)
- **Approval requirements** (some actions need human approval)

### 3.2 Same Policy in Both Formats

**Scenario:** "Allow `update_compliance_status` only if context_id matches AND approval_policy is `single_approval`"

#### OPA/Rego Version

```rego
package agent.authz

import rego.v1

default allow := false

# Tool-level permissions from external data
tool_config := data.tool_configs[input.tool_name]

# Allow if tool is permitted for this context and approval requirements are met
allow if {
    # Tool exists in config
    tool_config

    # Context boundary check
    input.context_id == input.agent.assigned_context_id

    # Data scope check
    input.data_scope in tool_config.allowed_scopes

    # Approval check
    approval_satisfied
}

# No approval needed
approval_satisfied if {
    tool_config.approval_policy == "none"
}

# Single approval needed and received
approval_satisfied if {
    tool_config.approval_policy == "single_approval"
    input.approvals[_].approved == true
}

# Dual approval needed
approval_satisfied if {
    tool_config.approval_policy == "dual_approval"
    count({a | some a in input.approvals; a.approved == true}) >= 2
}
```

**Data file (tool_configs.json, loaded as OPA data):**

```json
{
  "tool_configs": {
    "update_compliance_status": {
      "allowed_scopes": ["compliance", "regulatory"],
      "approval_policy": "single_approval",
      "audit_level": "full"
    },
    "get_account_details": {
      "allowed_scopes": ["account_read"],
      "approval_policy": "none",
      "audit_level": "standard"
    },
    "execute_trade": {
      "allowed_scopes": ["trading"],
      "approval_policy": "dual_approval",
      "audit_level": "full"
    }
  }
}
```

**Input for evaluation:**

```json
{
  "tool_name": "update_compliance_status",
  "context_id": "ctx-12345",
  "data_scope": "compliance",
  "agent": {
    "id": "agent-001",
    "assigned_context_id": "ctx-12345"
  },
  "approvals": [
    {"approver": "manager@bank.com", "approved": true, "timestamp": "2026-03-22T10:00:00Z"}
  ]
}
```

**Test file:**

```rego
package agent.authz_test

import data.agent.authz

test_allow_matching_context_with_approval if {
    authz.allow with input as {
        "tool_name": "update_compliance_status",
        "context_id": "ctx-12345",
        "data_scope": "compliance",
        "agent": {"id": "agent-001", "assigned_context_id": "ctx-12345"},
        "approvals": [{"approver": "mgr@bank.com", "approved": true}]
    }
    with data.tool_configs as {
        "update_compliance_status": {
            "allowed_scopes": ["compliance", "regulatory"],
            "approval_policy": "single_approval"
        }
    }
}

test_deny_wrong_context if {
    not authz.allow with input as {
        "tool_name": "update_compliance_status",
        "context_id": "ctx-99999",
        "data_scope": "compliance",
        "agent": {"id": "agent-001", "assigned_context_id": "ctx-12345"},
        "approvals": [{"approver": "mgr@bank.com", "approved": true}]
    }
    with data.tool_configs as {
        "update_compliance_status": {
            "allowed_scopes": ["compliance"],
            "approval_policy": "single_approval"
        }
    }
}

test_deny_no_approval_when_required if {
    not authz.allow with input as {
        "tool_name": "update_compliance_status",
        "context_id": "ctx-12345",
        "data_scope": "compliance",
        "agent": {"id": "agent-001", "assigned_context_id": "ctx-12345"},
        "approvals": []
    }
    with data.tool_configs as {
        "update_compliance_status": {
            "allowed_scopes": ["compliance"],
            "approval_policy": "single_approval"
        }
    }
}
```

#### YAML-Based Version (Custom Engine)

```yaml
# agent-tool-policy.yaml
version: 1
default_effect: deny

global_rules:
  - name: context_boundary
    description: "Agent must operate within assigned context"
    match:
      context_id: "{{ agent.assigned_context_id }}"
    effect: continue    # Not sufficient alone, but required

tools:
  update_compliance_status:
    allowed_scopes:
      - compliance
      - regulatory
    approval_policy: single_approval
    audit_level: full
    conditions:
      - field: context_id
        operator: equals
        value: "{{ agent.assigned_context_id }}"

  get_account_details:
    allowed_scopes:
      - account_read
    approval_policy: none
    audit_level: standard

  execute_trade:
    allowed_scopes:
      - trading
    approval_policy: dual_approval
    audit_level: full
    conditions:
      - field: trade_amount
        operator: less_than
        value: 1000000
```

#### Cedar Version

```cedar
// Allow tool call if context matches and approval satisfied
permit(
  principal is Agent,
  action == Action::"update_compliance_status",
  resource is Context
)
when {
  principal.assigned_context_id == resource.context_id &&
  context.data_scope in resource.allowed_scopes &&
  context.approval_count >= 1
};

// Deny cross-context access
forbid(
  principal is Agent,
  action,
  resource is Context
)
when {
  principal.assigned_context_id != resource.context_id
};
```

### 3.3 Latency Comparison

| Approach | Expected Latency (per tool call) | Notes |
|----------|--------------------------------|-------|
| **OPA Go library** | **< 0.1 ms** | Best for Go services; pre-compiled queries |
| **OPA WASM** | **0.1 - 0.5 ms** | Good for non-Go; in-process |
| **Cedar (Rust)** | **< 0.05 ms** | Fastest; but limited to PARC model |
| **OPA REST (localhost)** | **0.5 - 2 ms** | Acceptable for most agent use cases |
| **YAML custom engine** | **< 0.1 ms** | Simple matching is fast; depends on implementation |
| **Casbin** | **< 0.1 ms** | In-process library, very fast for simple RBAC |

**Verdict:** All approaches meet the sub-millisecond budget for per-tool-call evaluation when deployed in-process or on localhost. The latency difference between them is unlikely to be the deciding factor unless you are evaluating thousands of tool calls per second.

### 3.4 Expressiveness

| Requirement | OPA/Rego | YAML (Custom) | Cedar | Casbin |
|-------------|----------|---------------|-------|--------|
| Tool name matching | Yes | Yes | Yes | Yes |
| Context ID boundary | Yes | Yes | Yes | Yes |
| Data scope checking | Yes | Yes | Yes | With custom functions |
| Conditional approval logic | Yes (any complexity) | Limited (needs custom engine) | Yes (simple conditions) | Limited |
| Hierarchical overrides | Yes (package hierarchy + data) | Possible but complex | Yes (policy sets) | Via role hierarchy |
| Aggregation (count approvals) | Yes (`count()` built-in) | Needs custom code | No (no aggregation) | No |
| Cross-reference external data | Yes (via `data.*` namespace) | Needs custom loading | Via entity store | Via adapter |
| Dynamic conditions (time-based, etc.) | Yes (built-in time functions) | Needs custom code | Via context attributes | Via custom functions |

**Key finding:** OPA/Rego is the only option that natively handles all the requirements without custom engine code. YAML is sufficient for the simple cases (tool name + context_id + scope) but requires a custom evaluation engine for conditional logic like approval counting. Cedar handles the PARC model well but lacks aggregation.

### 3.5 Auditability

| Dimension | OPA | YAML-Based | Cedar |
|-----------|-----|-----------|-------|
| **Decision logging** | Built-in. Every decision logged with input, result, policy version, timestamp, decision_id, trace_id, metrics. | Must be custom-built. | AWS Verified Permissions provides audit via CloudTrail. |
| **Decision replay** | Yes -- logs contain full input, can replay against any policy version. | Depends on implementation. | Via CloudTrail event replay. |
| **Sensitive data masking** | Built-in `system.log.mask` rules to erase/redact fields before shipping. | Must be custom-built. | CloudTrail has PII handling. |
| **Compliance monitoring** | Styra DAS provides dashboards, alerts, and compliance reports. | Must be custom-built. | AWS console dashboards. |
| **Log shipping** | Periodic upload to HTTP servers, configurable batch size, gzip compressed. | Must be custom-built. | Built into AWS. |

**Example OPA decision log entry:**

```json
{
  "decision_id": "4ca636c1-55e4-417a-b1d8-4aceb67960d1",
  "labels": {"app": "agent-gateway", "version": "v2.1.0"},
  "path": "agent/authz/allow",
  "input": {
    "tool_name": "update_compliance_status",
    "context_id": "ctx-12345",
    "agent": {"id": "agent-001"}
  },
  "result": true,
  "timestamp": "2026-03-22T10:00:00.000000Z",
  "metrics": {
    "timer_rego_query_eval_ns": 48230
  },
  "bundles": {
    "authz": {"revision": "abc123"}
  }
}
```

**Verdict:** OPA has the strongest built-in audit story. For regulated environments (financial services), the combination of decision logging, replay capability, and Styra DAS compliance monitoring is a significant advantage.

### 3.6 Dynamic Policy Updates

| Approach | Hot-Reload Mechanism | Downtime |
|----------|---------------------|----------|
| **OPA Bundles** | OPA polls bundle server periodically. Atomic update. Signed bundles prevent tampering. | Zero downtime |
| **OPA REST API** | Push policies via `PUT /v1/policies/<id>`. Immediate effect. | Zero downtime |
| **OpenShell YAML** | Dynamic sections (network, inference) hot-reloadable via `openshell policy set`. Static sections (filesystem, process) require sandbox recreation. | Partial (static requires restart) |
| **Casbin** | Reload from file/database. Adapter pattern for persistence. | Depends on adapter |
| **Cedar (AVP)** | Update policy store via API. Immediate effect. | Zero downtime |

### 3.7 Testability

**OPA:**
- Built-in `opa test` command with `test_` prefix convention
- Coverage reporting (`opa test --coverage`)
- Data mocking via `with` keyword
- Function mocking for built-in functions
- Parameterized data-driven tests
- Conftest for testing configuration files against policies in CI/CD
- Styra DAS provides impact analysis before deployment

**Example test with mocking:**

```rego
package agent.authz_test

mock_tool_configs := {
    "update_compliance_status": {
        "allowed_scopes": ["compliance"],
        "approval_policy": "single_approval"
    }
}

test_dual_approval_needs_two if {
    not authz.allow with input as {
        "tool_name": "execute_trade",
        "context_id": "ctx-1",
        "data_scope": "trading",
        "agent": {"assigned_context_id": "ctx-1"},
        "approvals": [{"approved": true}]
    }
    with data.tool_configs as {
        "execute_trade": {
            "allowed_scopes": ["trading"],
            "approval_policy": "dual_approval"
        }
    }
}
```

**YAML-based:** Testing depends entirely on the custom engine. No standard framework exists. You would need to build your own test harness.

**Cedar:** AWS provides the Cedar CLI with a `cedar validate` command for static analysis and `cedar authorize` for testing. Formal verification can prove properties about policies.

### 3.8 Developer Experience

| Dimension | OPA/Rego | YAML (Custom) | Cedar |
|-----------|----------|---------------|-------|
| **Learning curve** | **Steep.** Datalog-like syntax unfamiliar to most developers. Requires learning a new paradigm. | **Low.** YAML is familiar. But conditional logic is limited. | **Moderate.** Readable syntax but PARC model has constraints. |
| **Debugging** | `opa eval --partial` for step-by-step, `print()` statements, Styra DAS visualizer | Depends on custom engine | `cedar authorize --verbose` |
| **IDE support** | VS Code extension, syntax highlighting, linting | Generic YAML support | VS Code extension |
| **Documentation** | Extensive (CNCF project, large community) | Must be self-documented | Good (AWS-backed) |
| **Community** | Large, mature, many examples | N/A (custom) | Growing rapidly |
| **Time to first policy** | Hours (need to learn Rego) | Minutes (just YAML) | 30 minutes |

### 3.9 Hierarchical Policies (Global Defaults + Per-Context Overrides)

**OPA approach:**

```rego
package agent.authz

import rego.v1

# Global defaults
default_config := data.policies.global_defaults

# Per-context overrides
context_config := data.policies.contexts[input.context_id]

# Merged config: context overrides take precedence
effective_config := object.union(default_config, context_config)

# Tool config with hierarchy
tool_config := object.union(
    effective_config.tools[input.tool_name],
    object.get(context_config, ["tool_overrides", input.tool_name], {})
)
```

**Data structure:**

```json
{
  "policies": {
    "global_defaults": {
      "tools": {
        "get_account_details": {
          "allowed_scopes": ["account_read"],
          "approval_policy": "none"
        }
      }
    },
    "contexts": {
      "ctx-high-risk": {
        "tool_overrides": {
          "get_account_details": {
            "approval_policy": "single_approval"
          }
        }
      }
    }
  }
}
```

**YAML approach:**

```yaml
# global-defaults.yaml
tools:
  get_account_details:
    allowed_scopes: [account_read]
    approval_policy: none

# context-overrides/ctx-high-risk.yaml
inherits: global-defaults
tool_overrides:
  get_account_details:
    approval_policy: single_approval
```

**Verdict:** OPA handles hierarchical policies natively through its data namespace and `object.union`. YAML requires a custom merge mechanism in the evaluation engine.

---

## 4. Financial Services Usage

### 4.1 Banks Using OPA

| Bank | Use Case | Scale |
|------|----------|-------|
| **Goldman Sachs** | Cloud Entitlements Service (OCES): multi-tenant OPA on ECS Fargate, multi-regional deployment, policies authored in GitLab with CI/CD pipeline. | Enterprise-wide cloud authorization |
| **Goldman Sachs** | Kubernetes admission control in multi-tenant clusters: RBAC, PV, Quota provisioning. | All K8s clusters |
| **Capital One** | Validating admission controller: image registry allowlisting, label requirements, resource limits, container privilege restrictions. | All K8s clusters |
| **BNY Mellon** | Sidecar-based access control using Active Directory context + internal service attributes. | Application authorization |
| **Marsh McLennan** | OPA Gatekeeper + authorization decision point for ingress traffic. Also used as a rules engine. | Multi-purpose |

### 4.2 Financial Services Patterns

**Goldman Sachs OCES architecture:**
- Multi-tenanted: each business unit gets a dedicated OPA tenant
- Deployed on ECS Fargate (reduces infrastructure management overhead)
- Multi-regional for resilience
- Policies authored in GitLab, pushed via CI/CD pipeline
- Subject to standard SDLC: approval, testing, baking in lower environments before production

**Key financial services requirements that favor OPA:**

1. **Audit trail** -- OPA's decision logging produces a complete record of every authorization decision with full context, satisfying regulatory requirements for explainability
2. **Policy versioning** -- Git-based policy management with CI/CD provides change tracking, approval workflows, and rollback capability
3. **Separation of duties** -- Policy authors, reviewers, and deployers can be different people with different access levels
4. **Reproducibility** -- Decision logs + bundle versioning allow replaying any historical decision against the exact policy version in effect
5. **Compliance reporting** -- Styra DAS provides pre-built compliance templates for PCI DSS, NIST, CIS Benchmarks

### 4.3 Regulatory Considerations

| Requirement | OPA Advantage | YAML Advantage |
|-------------|--------------|----------------|
| **SOX compliance** (change management, audit trails) | Built-in decision logs, bundle versioning, Git-based workflow | Simpler to audit visually (YAML is human-readable) |
| **Data residency** | OPA runs locally, no external calls at decision time | Same |
| **Explainability** | Decision logs capture full input + result + policy version | Depends on implementation |
| **Access control reviews** | Styra DAS dashboards; policies are code (auditable) | YAML is directly readable |
| **Change approval** | Standard Git PR workflow for policy changes | Same |

**No regulation explicitly mandates OPA or any specific policy engine.** The requirements are for audit trails, access control, change management, and explainability -- which OPA satisfies out of the box, and YAML-based approaches can satisfy with additional engineering effort.

---

## 5. Hybrid Approaches

### 5.1 YAML for Config, OPA/Rego for Logic

The most practical pattern separates concerns:

- **YAML defines WHAT** -- tool permissions, allowed scopes, approval requirements, context configurations
- **Rego defines HOW** -- evaluation logic, conditional rules, approval counting, hierarchical merging

This is already OPA's native model. The `data.*` namespace in Rego is loaded from JSON/YAML files.

**Example:**

```
policies/
  rego/
    authz.rego              # Evaluation logic (Rego)
    authz_test.rego         # Tests
  data/
    tool_configs.yaml       # Tool permission definitions (YAML)
    context_configs.yaml    # Per-context overrides (YAML)
    role_mappings.yaml      # Role-to-permission mappings (YAML)
```

**tool_configs.yaml:**

```yaml
tool_configs:
  update_compliance_status:
    allowed_scopes:
      - compliance
      - regulatory
    approval_policy: single_approval
    audit_level: full
    risk_level: high

  get_account_details:
    allowed_scopes:
      - account_read
    approval_policy: none
    audit_level: standard
    risk_level: low

  execute_trade:
    allowed_scopes:
      - trading
    approval_policy: dual_approval
    audit_level: full
    risk_level: critical
    conditions:
      max_amount: 1000000
```

**authz.rego:**

```rego
package agent.authz

import rego.v1

default allow := false

# Load tool config from YAML data
tool_config := data.tool_configs[input.tool_name]

allow if {
    tool_config                                           # Tool exists
    context_boundary_ok                                   # Context match
    scope_ok                                              # Data scope allowed
    approval_ok                                           # Approval requirements met
    custom_conditions_ok                                  # Any tool-specific conditions
}

context_boundary_ok if {
    input.context_id == input.agent.assigned_context_id
}

scope_ok if {
    input.data_scope in tool_config.allowed_scopes
}

approval_ok if {
    tool_config.approval_policy == "none"
}

approval_ok if {
    tool_config.approval_policy == "single_approval"
    count([a | some a in input.approvals; a.approved]) >= 1
}

approval_ok if {
    tool_config.approval_policy == "dual_approval"
    count([a | some a in input.approvals; a.approved]) >= 2
}

# Default: no extra conditions
default custom_conditions_ok := true

# Trade amount check
custom_conditions_ok if {
    input.tool_name == "execute_trade"
    input.parameters.amount <= tool_config.conditions.max_amount
}
```

### 5.2 Benefits of the Hybrid Approach

1. **Non-engineers can modify tool permissions** by editing YAML (add a new tool, change approval level)
2. **Complex logic stays in Rego** where it can be tested, versioned, and formally reviewed
3. **YAML data can be updated independently** of Rego logic (separate bundles, different update cadences)
4. **OPA's bundle system** distributes both YAML data and Rego policies atomically
5. **Testing covers both layers** -- Rego tests mock the YAML data, YAML schema validation ensures structural correctness

### 5.3 When Pure YAML Is Sufficient

Use pure YAML (no OPA) when:
- All policies are simple allow/deny on tool name + context_id (no conditional logic)
- No approval workflows
- No hierarchical policy merging needed
- You control the evaluation engine and can keep it simple
- Sub-microsecond latency is critical (avoiding even OPA's overhead)

### 5.4 When OPA Is Required

Use OPA when:
- Approval logic varies by tool, context, and risk level
- Hierarchical policy inheritance (global + context + tool overrides)
- Audit trail with decision logging is a regulatory requirement
- Policy testing must be automated in CI/CD
- Multiple teams author policies independently
- Dynamic data (role mappings, schedules) affects decisions
- You need partial evaluation for data filtering

---

## 6. Recommendation for Agent Tool Access Control

For a financial services AI agent platform evaluating tool calls with context boundaries, data scoping, and approval requirements:

**Use the hybrid approach: YAML data + OPA/Rego logic.**

| Layer | Technology | Maintained By |
|-------|-----------|---------------|
| Tool permission definitions | YAML files in Git | Product/compliance team |
| Context configurations | YAML files in Git | Operations team |
| Evaluation logic | Rego policies | Engineering team |
| Policy testing | `opa test` in CI/CD | Engineering team |
| Policy distribution | OPA bundles | Platform team |
| Audit trail | OPA decision logs | Automatic |
| Compliance monitoring | Styra DAS (or custom) | Compliance team |

**Why not pure YAML:** The approval logic (single vs dual, conditional on risk level) and hierarchical overrides require evaluation logic that YAML alone cannot express without building a custom engine.

**Why not pure Rego:** Tool permission definitions change more frequently than evaluation logic. YAML is more accessible to non-engineers who need to manage tool configurations.

**Why not Cedar:** Cedar lacks aggregation (cannot count approvals), cannot produce non-boolean outputs (cannot return audit metadata alongside decisions), and has a smaller ecosystem. However, if your policies are strictly PARC-model and performance is paramount, Cedar is worth evaluating.

**Why not Casbin:** Casbin is excellent for simple RBAC/ABAC but lacks OPA's decision logging, bundle distribution, partial evaluation, and testing framework -- all critical for a regulated environment.

---

## Sources

- [OPA Integration Patterns](https://www.openpolicyagent.org/docs/integration)
- [OPA Bundles Documentation](https://www.openpolicyagent.org/docs/latest/management-bundles/)
- [OPA Decision Logs](https://www.openpolicyagent.org/docs/management-decision-logs)
- [OPA Policy Testing](https://www.openpolicyagent.org/docs/policy-testing)
- [OPA Policy Performance](https://www.openpolicyagent.org/docs/policy-performance)
- [OPA Envoy Performance Benchmarks](https://www.openpolicyagent.org/docs/envoy/performance)
- [OPA WebAssembly](https://www.openpolicyagent.org/docs/wasm)
- [OPA ADOPTERS.md](https://github.com/open-policy-agent/opa/blob/main/ADOPTERS.md)
- [Goldman Sachs: Scaling OPA for Cloud Entitlements](https://developer.gs.com/blog/posts/scaling-opa-for-oces)
- [Goldman Sachs: Kubernetes Policy Enforcement Using OPA (KubeCon 2019)](https://kccncna19.sched.com/event/UaaX)
- [Red Hat: Advanced Authentication and Authorization for MCP Gateway](https://developers.redhat.com/articles/2025/12/12/advanced-authentication-authorization-mcp-gateway)
- [NVIDIA NemoClaw](https://github.com/NVIDIA/NemoClaw)
- [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell)
- [OpenShell Policy Schema Reference](https://docs.nvidia.com/openshell/latest/reference/policy-schema.html)
- [OpenShell First Network Policy Tutorial](https://docs.nvidia.com/openshell/latest/tutorials/first-network-policy.html)
- [Cedar Policy Language Reference](https://docs.cedarpolicy.com/)
- [Cedar Policy Examples](https://docs.cedarpolicy.com/policies/policy-examples.html)
- [OPA vs Cedar: Policy as Code (Permit.io)](https://www.permit.io/blog/opa-vs-cedar)
- [OPA vs Cedar vs Zanzibar: 2025 Policy Engine Guide (Oso)](https://www.osohq.com/learn/opa-vs-cedar-vs-zanzibar)
- [MCP Access Control: OPA vs Cedar (Natoma)](https://natoma.ai/blog/mcp-access-control-opa-vs-cedar-the-definitive-guide)
- [Security Benchmarking Authorization Policy Engines (Teleport / Trail of Bits)](https://goteleport.com/blog/benchmarking-policy-languages/)
- [Casbin: How It Works](https://casbin.org/docs/how-it-works/)
- [Casbin Model Syntax](https://casbin.org/docs/syntax-for-models/)
- [OPA vs Casbin Comparison (GitHub Gist)](https://gist.github.com/StevenACoffman/1644ec1157a793eb7d868aa22b260e91)
- [Cerbos vs OPA](https://www.cerbos.dev/blog/cerbos-vs-opa)
- [Kyverno vs OPA](https://www.plural.sh/blog/open-policy-agent-vs-kyverno/)
- [Styra DAS](https://www.styra.com/styra-das/)
- [Styra Enterprise OPA Platform](https://www.styra.com/enterprise-opa-platform/)
- [AWS IAM Policy Element Reference](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements.html)
- [Kubernetes RBAC Authorization](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)
- [AWS Prescriptive Guidance: OPA ABAC Examples](https://docs.aws.amazon.com/prescriptive-guidance/latest/saas-multitenant-api-access-authorization/opa-abac-examples.html)
- [NemoClaw Enterprise Launch (VentureBeat)](https://venturebeat.com/technology/nvidia-lets-its-claws-out-nemoclaw-brings-security-scale-to-the-agent)
- [NemoClaw Enterprise Security (Lopez Research)](https://www.lopezresearch.com/nemoclaw-gives-enterprise-ai-agents-the-security-layer-theyve-been-missing/)
- [Conftest: Policy Testing for Configuration Files](https://github.com/open-policy-agent/conftest)
- [OPA Rego Deep Dive (CalmOps)](https://calmops.com/devops/opa-rego-policy-code-deep-dive/)
- [Komodor: OPA Features and Use Cases](https://komodor.com/learn/open-policy-agent-opa-features-use-cases-and-how-to-get-started/)
- [AWS: Deploying OPA as Sidecar on ECS](https://aws.amazon.com/blogs/opensource/deploying-open-policy-agent-opa-as-a-sidecar-on-amazon-elastic-container-service-amazon-ecs/)
