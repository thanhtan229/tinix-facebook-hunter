# RESEARCH.md

> **Pre-Implementation / Focused Technical Research**
>
> This document captures technical research performed before implementation or for one focused technical topic.
>
> Its purpose is to establish evidence, reduce uncertainty, identify viable technical directions, and provide reliable inputs for `PLAN.md` and `ARCHITECTURE.md`.
>
> This is a research document, not an implementation plan and not a progress log.

---

## 0. Research Metadata

**Project:** TBD  
**Research Topic:** TBD  
**Research Type:** Pre-Implementation | Focused Technical Research  
**Status:** Draft | In Progress | Ready | Ready with Limitations | More Research Required | Blocked  
**Research Date:** YYYY-MM-DD  
**Last Updated:** YYYY-MM-DD  

### Scope

Describe what this research covers.

- TBD
- TBD

### Out of Scope

- TBD
- TBD

---

## 1. Project Understanding

Summarize the project or problem being researched.

### Product / System Objective

TBD

### Core User / System Workflows

- TBD
- TBD
- TBD

### Functional Requirements

- TBD
- TBD

### Non-Functional Requirements

Consider when relevant:

- reliability;
- performance;
- security;
- maintainability;
- extensibility;
- accessibility;
- offline/local-first behavior;
- deployment constraints;
- operational simplicity.

Project-specific requirements:

- TBD
- TBD

### Technical Constraints

- TBD
- TBD

### Assumptions

List assumptions that have not yet been fully verified.

- TBD
- TBD

Do not present assumptions as facts.

---

## 2. Research Objectives

State what this research must determine.

Examples:

- identify the most suitable architecture;
- determine whether an existing framework/repository can be reused;
- evaluate storage or messaging approaches;
- understand provider limitations;
- find reliable patterns for retries, queues, or synchronization;
- determine whether a POC is required.

Research objectives:

1. TBD
2. TBD
3. TBD

---

## 3. Research Questions

List the technical questions that must be answered before implementation.

1. TBD
2. TBD
3. TBD
4. TBD

Research only questions that may materially affect implementation, architecture, risk, or long-term maintainability.

---

## 4. Research Method

Describe how evidence was gathered.

Possible methods:

- official documentation;
- official repository/source code;
- source-code inspection;
- tests/examples;
- releases/changelog;
- issues/discussions;
- technical standards;
- API/provider documentation;
- mature open-source implementations;
- targeted experiments or POCs.

Methods used:

- TBD
- TBD

---

## 5. Sources / Repositories Researched

Use one subsection per significant source.

### Source 1 — TBD

**Name:** TBD  
**Type:** Repository | Official Documentation | API Documentation | Standard | Issue / Discussion | Other  
**Source / URL:** TBD  
**Version / Release / Tag / Commit:** TBD  
**Date Checked:** YYYY-MM-DD  
**Why Relevant:** TBD  

### Source 2 — TBD

**Name:** TBD  
**Type:** TBD  
**Source / URL:** TBD  
**Version / Release / Tag / Commit:** TBD  
**Date Checked:** YYYY-MM-DD  
**Why Relevant:** TBD  

Add or remove entries as needed.

For repositories, record the exact version, release, tag, or commit when practical.

---

## 6. Existing Project / Repository Assessment

Use this section only when an implementation already exists.

If this is a greenfield project, write:

`Greenfield project — no existing implementation to assess.`

Otherwise document only the parts relevant to the research.

### Current Architecture

TBD

### Reusable Components / Existing Strengths

- TBD
- TBD

### Relevant Technical Debt / Constraints

- TBD
- TBD

### Existing Behaviors That Must Be Preserved

- TBD

Do not duplicate the full contents of `ARCHITECTURE.md`.

---

## 7. Key Findings

Use one subsection per important finding.

### Finding 1 — TBD

**Evidence:**  
TBD

**Analysis:**  
TBD

**Relevance to This Project:**  
TBD

**Confidence:** High | Medium | Low

**Implication:**  
TBD

---

### Finding 2 — TBD

**Evidence:**  
TBD

**Analysis:**  
TBD

**Relevance to This Project:**  
TBD

**Confidence:** High | Medium | Low

**Implication:**  
TBD

Add or remove findings as needed.

### Evidence Rule

Clearly distinguish:

- **Evidence / Fact** — directly supported by source code, docs, tests, releases, or other evidence.
- **Analysis / Inference** — technical interpretation based on evidence.
- **Recommendation** — proposed direction for this project.

Do not present inference as verified fact.

---

## 8. Relevant Technical Architecture / Behavior

Document only architecture or implementation behavior relevant to the research.

Consider when applicable:

- runtime components;
- module boundaries;
- data flow;
- persistence;
- APIs;
- IPC;
- callbacks/webhooks;
- queues/workers;
- retries;
- idempotency;
- synchronization;
- authentication;
- authorization;
- configuration;
- lifecycle;
- extension points;
- observability;
- deployment model.

### Relevant Flow / Pattern 1

TBD

### Relevant Flow / Pattern 2

TBD

Do not document unrelated parts of external systems.

---

## 9. Alternatives Considered

Document meaningful alternatives.

### Option A — TBD

**Description:** TBD

**Strengths:**

- TBD

**Weaknesses / Tradeoffs:**

- TBD

**Fit for This Project:** High | Medium | Low

**Notes:** TBD

---

### Option B — TBD

**Description:** TBD

**Strengths:**

- TBD

**Weaknesses / Tradeoffs:**

- TBD

**Fit for This Project:** High | Medium | Low

**Notes:** TBD

Avoid arbitrary numeric scoring unless a scoring method is explicitly defined.

---

## 10. Best Patterns to Adopt or Adapt

Identify patterns worth carrying into the project.

### Pattern 1 — TBD

**Source:** TBD  
**Problem Solved:** TBD  
**Why It Is Useful:** TBD  
**Required Adaptation:** TBD  
**Classification:** ADOPT | ADAPT | POC FIRST

### Pattern 2 — TBD

**Source:** TBD  
**Problem Solved:** TBD  
**Why It Is Useful:** TBD  
**Required Adaptation:** TBD  
**Classification:** ADOPT | ADAPT | POC FIRST

Do not copy external architecture blindly.

---

## 11. Patterns to Avoid

Document patterns that should not be adopted.

### Pattern 1 — TBD

**Source:** TBD  
**Reason to Avoid:** TBD  
**Risk to This Project:** TBD

### Pattern 2 — TBD

**Source:** TBD  
**Reason to Avoid:** TBD  
**Risk to This Project:** TBD

---

## 12. Failure Modes and Risks

Research must consider failure behavior, not only the happy path.

Consider when relevant:

- concurrency;
- data consistency;
- retries;
- idempotency;
- duplicate processing;
- webhook/callback failure;
- provider outages;
- authentication failure;
- rate limits;
- queue saturation;
- migration risk;
- scaling limits;
- security risk;
- vendor lock-in;
- maintenance burden;
- licensing;
- data loss.

| Risk / Failure Mode | Evidence / Reason | Project Impact | Mitigation / Direction |
|---|---|---|---|
| TBD | TBD | TBD | TBD |
| TBD | TBD | TBD | TBD |

---

## 13. Recommended Technical Direction

Describe the recommended technical direction at a level sufficient to inform planning and architecture.

Include when relevant:

- major runtime components;
- module boundaries;
- primary data flow;
- storage strategy;
- API/integration model;
- background processing;
- reliability/retry strategy;
- error handling;
- security boundaries;
- testing approach;
- deployment/runtime model.

### Recommended Direction

TBD

### Why This Direction

- TBD
- TBD

### Important Tradeoffs

- TBD
- TBD

### Complexity Check

Explain why this is the **smallest coherent architecture** that satisfies the actual requirements.

TBD

Do not turn this section into a file-by-file implementation plan.

---

## 14. Recommended Architecture Inputs

List decisions that should later be reflected in `ARCHITECTURE.md`.

- TBD
- TBD
- TBD

If none:

`No architecture changes or inputs recommended.`

Research findings do not automatically become architecture decisions until accepted.

---

## 15. Recommended Plan Inputs

List implementation-planning inputs that should later be reflected in `PLAN.md`.

Consider:

- implementation phases;
- major workstreams;
- dependencies;
- migrations;
- compatibility;
- testing requirements;
- validation;
- rollout;
- risks;
- acceptance criteria.

Recommended inputs:

- TBD
- TBD
- TBD

If none:

`No plan changes or inputs recommended.`

---

## 16. POC / Validation Required

Use this section for important questions that cannot be resolved confidently through research alone.

### POC 1 — TBD

**Question:** TBD  
**Why It Matters:** TBD  
**Minimum Experiment:** TBD  
**Pass Criteria:** TBD  
**Fail Criteria:** TBD  
**Decision Affected:** TBD  

### POC 2 — TBD

**Question:** TBD  
**Why It Matters:** TBD  
**Minimum Experiment:** TBD  
**Pass Criteria:** TBD  
**Fail Criteria:** TBD  
**Decision Affected:** TBD  

If none:

`No POC required.`

Do not implement a POC unless explicitly requested.

---

## 17. Open Questions / Blockers

List unresolved items.

### Open Question / Blocker 1

**Question / Problem:** TBD  
**Why It Matters:** TBD  
**What Is Needed to Resolve It:** TBD

If none:

`None.`

---

## 18. Final Research Summary

This section must remain concise and useful for quick handoff.

**STATUS:**  
`READY | READY WITH LIMITATIONS | MORE RESEARCH REQUIRED | BLOCKED`

**KEY FINDINGS:**

- TBD
- TBD
- TBD

**RECOMMENDED TECHNICAL DIRECTION:**

- TBD

**BEST PATTERNS TO ADOPT / ADAPT:**

- TBD
- TBD

**PATTERNS TO AVOID:**

- TBD

**ARCHITECTURE INPUTS:**

- TBD

**PLAN INPUTS:**

- TBD

**POC / VALIDATION REQUIRED:**

- TBD

**OPEN BLOCKERS:**

- TBD

---

## 19. Research Phase Boundary

Unless explicitly requested, research does **not** authorize:

- production code implementation;
- refactoring;
- dependency installation;
- migration;
- package/release creation;
- automatic modification of `PLAN.md`;
- automatic modification of `ARCHITECTURE.md`.

The purpose of this document is to provide evidence and recommendations for the next decision-making step.

---

## 20. Maintenance Rule

For pre-implementation project research, keep this file as:

`RESEARCH.md`

at the project root.

For later focused research, prefer:

`research/RESEARCH_<topic>.md`

Update this document when:

- key evidence changes;
- major source versions change;
- a blocking question is resolved;
- new research materially changes the recommendation.

Do not use this file as a development diary.
