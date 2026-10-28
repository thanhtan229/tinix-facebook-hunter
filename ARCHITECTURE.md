# ARCHITECTURE.md

> **Current Technical Architecture**
>
> This document describes the durable technical structure of this project: major components, boundaries, data flow, runtime model, storage, integrations, and architectural constraints.
>
> It should reflect the system **as it currently exists or has been explicitly decided**, not speculative future architecture.

---

## 0. Architecture Metadata

**Project:** TBD  
**Architecture Version:** 1.0  
**Status:** Draft | Active  
**Last Updated:** YYYY-MM-DD  

---

## 1. System Overview

Describe the system at a high level.

Include:

- what the application does technically;
- major runtime components;
- where core responsibilities live;
- major external dependencies.

Example shape:

```text
User Interface
      ↓
Application Layer
      ↓
Domain / Services
      ↓
Storage / External Providers
```

Replace this with the actual project architecture.

---

## 2. Architecture Goals

List the main architectural priorities.

Examples:

- simplicity;
- maintainability;
- local-first behavior;
- offline support;
- modularity;
- low operational complexity;
- performance;
- portability;
- reliability.

Project-specific goals:

- TBD
- TBD
- TBD

---

## 3. System Context

Describe the system boundary.

### Users / Clients

- TBD

### External Systems

- TBD

### External Providers / APIs

- TBD

### Trust Boundaries

- TBD

---

## 4. Runtime Components

Document each major runtime component.

### Component: TBD

**Responsibility:** TBD  
**Runtime:** TBD  
**Entry point:** TBD  
**Owns:** TBD  
**Depends on:** TBD  
**Communicates with:** TBD  

Repeat for major components only.

Examples may include:

- frontend;
- desktop shell;
- backend/API;
- worker;
- scheduler;
- database;
- local service;
- media processor.

---

## 5. Module Boundaries

Describe important code/module boundaries.

Example:

```text
UI
↓
Application Services
↓
Domain Logic
↓
Infrastructure
```

For each important module:

### Module: TBD

**Purpose:** TBD  
**May depend on:** TBD  
**Must not depend on:** TBD  

Avoid documenting every folder.

Focus on boundaries agents must preserve.

---

## 6. Repository Structure

Document only important directories.

```text
/
├── TBD/        # responsibility
├── TBD/        # responsibility
├── TBD/        # responsibility
└── TBD/        # responsibility
```

Do not mirror the entire repository tree.

---

## 7. Main Data Flow

Describe the important end-to-end data paths.

### Flow 1 — TBD

```text
Input
→ Component
→ Service
→ Storage / Provider
→ Result
```

Explain:

- source;
- transformations;
- persistence;
- output;
- failure boundary.

Add additional flows only when architecturally meaningful.

---

## 8. State Ownership

Document where important state lives.

| State | Owner | Persistence | Notes |
|---|---|---|---|
| TBD | TBD | TBD | TBD |

Clarify when relevant:

- frontend state;
- server state;
- database state;
- filesystem state;
- cache;
- job state;
- session state.

Avoid duplicated ownership.

---

## 9. Data Storage

### Primary Storage

**Technology:** TBD  
**Purpose:** TBD  

### Filesystem / Object Storage

- TBD

### Cache

- TBD

### Local Storage

- TBD

### Data Ownership Rules

- TBD

If a storage type is not used, mark it `N/A`.

---

## 10. API / IPC / Communication Boundaries

Document how components communicate.

Examples:

- HTTP/REST;
- GraphQL;
- WebSocket;
- IPC;
- message queue;
- filesystem;
- direct in-process calls.

### Boundary: TBD

**Producer / Caller:** TBD  
**Consumer:** TBD  
**Protocol / Mechanism:** TBD  
**Contract:** TBD  
**Error behavior:** TBD  

Public or durable contracts should be clearly distinguished from internal implementation details.

---

## 11. Background Jobs and Async Processing

If none:

`Not applicable.`

Otherwise document:

- worker model;
- queue;
- scheduler;
- retries;
- idempotency;
- cancellation;
- progress state;
- failure handling.

### Job: TBD

**Trigger:** TBD  
**Executor:** TBD  
**State storage:** TBD  
**Retry policy:** TBD  
**Completion behavior:** TBD  

---

## 12. External Integrations

### Integration: TBD

**Purpose:** TBD  
**Direction:** Inbound | Outbound | Bidirectional  
**Authentication:** TBD  
**Failure behavior:** TBD  
**Rate/usage constraints:** TBD  
**Ownership boundary:** TBD  

Do not include secrets.

---

## 13. Authentication and Authorization

If not applicable:

`Not applicable.`

Otherwise document:

- authentication model;
- authorization model;
- session/token ownership;
- trust boundaries;
- privileged operations.

Do not store credentials or secret values in this file.

---

## 14. Configuration and Environment

Document configuration categories, not secret values.

Examples:

```text
Runtime configuration: TBD
Environment variables: TBD
Feature flags: TBD
Local development configuration: TBD
Production configuration source: TBD
```

Clarify which settings are:

- startup-only;
- runtime-reloadable;
- environment-specific.

---

## 15. Error Handling Strategy

Describe architectural error behavior.

Consider:

- where errors are caught;
- where errors are translated;
- user-facing vs internal errors;
- retry boundaries;
- logging responsibilities;
- failure isolation.

Rules:

- do not silently swallow errors;
- avoid duplicated error translation across layers;
- preserve actionable diagnostic context.

---

## 16. Logging and Observability

Document:

- logging owner;
- log locations;
- log levels;
- health endpoints;
- metrics;
- traces;
- crash reporting;
- audit logs;

when applicable.

```text
Application logs: TBD
Backend logs: TBD
Health check: TBD
Metrics: TBD
Tracing: TBD
Crash reporting: TBD
```

---

## 17. Security Boundaries

Document durable security assumptions.

Consider:

- secrets;
- local vs remote trust;
- file access;
- user input validation;
- external APIs;
- privileged actions;
- sandboxing;
- data exposure boundaries.

Do not include sensitive values.

---

## 18. Performance-Critical Areas

If none are currently known:

`None identified.`

Otherwise:

### Area: TBD

**Why critical:** TBD  
**Current strategy:** TBD  
**Constraints:** TBD  

Do not add speculative optimization plans here.

---

## 19. Platform-Specific Architecture

If the project has platform-specific behavior, document it here.

Examples:

### Desktop

- main process;
- renderer;
- IPC;
- local backend;
- updater.

### Web

- browser runtime;
- server rendering;
- API backend;
- CDN.

### Mobile

- native shell;
- platform services;
- local persistence.

### Hybrid

- TBD

If not applicable:

`N/A.`

---

## 20. Deployment / Distribution Model

Describe how the system is run outside development.

Examples:

- hosted web;
- desktop package;
- mobile store package;
- container;
- on-premise service;
- local-only tool.

```text
Deployment model: TBD
Distribution artifact: TBD
Runtime dependencies: TBD
Upgrade/update model: TBD
```

Detailed build/restart behavior belongs in `DEVELOPMENT_WORKFLOW.md`.

---

## 21. Architectural Constraints

List constraints coding agents must preserve.

Examples:

- module A must not import module B;
- frontend must not access database directly;
- provider-specific logic stays behind an adapter;
- shared domain logic must remain platform-independent;
- writes must go through service X.

Project constraints:

- TBD
- TBD
- TBD

This is one of the most important sections for preventing accidental architecture drift.

---

## 22. Durable Architectural Decisions

Record only important decisions that affect future implementation.

### Decision: TBD

**Status:** Accepted  
**Context:** TBD  
**Decision:** TBD  
**Reason:** TBD  
**Consequences:** TBD  

For complex or controversial decisions, use a separate ADR if the project adopts ADRs.

Do not turn this section into a change log.

---

## 23. Known Architectural Limitations

List known structural limitations that materially affect future work.

- TBD

If none:

`None currently documented.`

Distinguish architectural limitations from temporary bugs.

---

## 24. Architecture Change Rules

Update this file when a task introduces or changes a **durable architectural decision**, for example:

- adding/removing a major runtime component;
- changing module boundaries;
- changing primary storage;
- adding a major external provider;
- changing authentication architecture;
- introducing a queue/worker;
- changing core data flow;
- changing deployment/runtime model;
- introducing an important shared abstraction.

Do **not** update this file merely because:

- a bug was fixed;
- UI changed;
- a button was added;
- CSS changed;
- a local handler changed;
- tests changed;
- a project phase completed.

`ARCHITECTURE.md` is a current technical map, not a progress log.

---

## 25. Source of Truth

When implementation and this document disagree:

1. verify whether the implementation changed intentionally;
2. verify the latest explicit project decision;
3. update whichever is stale.

Do not knowingly leave `ARCHITECTURE.md` describing an architecture that no longer exists.

---

## 26. Relationship to Other Documents

```text
AGENTS.md
→ How should coding agents work?

DEVELOPMENT_WORKFLOW.md
→ How is code validated, run, reloaded, restarted, and packaged?

UX_UI.md
→ How should the product look and behave for users?

ARCHITECTURE.md
→ How is the technical system structured?

PLAN.md
→ What are we planning to implement?

PROJECT_STATUS.md
→ Where are we currently in execution?
```
