# PLAN.md

> **Project / Feature Implementation Plan**
>
> This document defines what will be built, why it is needed, how it will be implemented, how it will be verified, and what completion means.
>
> Use this file for substantial, multi-step, high-risk, or multi-system work. Small scoped tasks normally do not require a separate plan file.

---

## 0. Plan Metadata

**Project / Feature:** TBD  
**Plan Version:** 1.0  
**Status:** Draft | Ready | In Progress | Blocked | Completed  
**Owner / Primary Agent:** TBD  
**Created:** YYYY-MM-DD  
**Last Updated:** YYYY-MM-DD  

---

## 1. Objective

Describe the intended outcome in a few sentences.

Focus on:

- what problem is being solved;
- what user or system outcome is expected;
- what success looks like.

Avoid implementation detail here unless it is essential to understanding the goal.

---

## 2. Scope

### In Scope

- TBD
- TBD
- TBD

### Out of Scope

- TBD
- TBD
- TBD

Clearly separating scope prevents feature creep and unrelated refactoring.

---

## 3. Background / Current State

Summarize only the context needed to understand why this plan exists.

Include when relevant:

- current behavior;
- current limitations;
- existing implementation;
- known constraints;
- relevant previous decisions.

Do not duplicate `ARCHITECTURE.md`.

---

## 4. Requirements

### Functional Requirements

1. TBD
2. TBD
3. TBD

### Non-Functional Requirements

Consider when relevant:

- performance;
- reliability;
- security;
- accessibility;
- maintainability;
- compatibility;
- observability;
- scalability.

### Constraints

- TBD
- TBD

---

## 5. Acceptance Criteria

The work is complete when all applicable criteria are satisfied.

- [ ] TBD
- [ ] TBD
- [ ] TBD

Acceptance criteria should describe observable outcomes, not vague implementation intent.

---

## 6. Proposed Solution

Describe the intended implementation approach.

Include:

- main components/modules involved;
- data flow;
- major logic changes;
- UI/workflow changes;
- integration points;
- important tradeoffs.

Keep this section implementation-focused but concise.

---

## 7. Affected Areas

List the expected areas of the repository that may change.

```text
Frontend:
- TBD

Backend:
- TBD

Database / Storage:
- TBD

Shared code:
- TBD

Configuration:
- TBD

Tests:
- TBD

Documentation:
- TBD
```

Do not treat this as permission to modify unrelated files.

---

## 8. Data / API / Contract Changes

If none:

`None.`

Otherwise document:

### Data Model Changes

- TBD

### API Changes

- TBD

### Public Contract Changes

- TBD

### Backward Compatibility

- TBD

### Migration Requirements

- TBD

Any durable architectural effect should also be reflected in `ARCHITECTURE.md`.

---

## 9. UI / UX Changes

If the task affects UI, describe:

- screens/components affected;
- user workflow;
- loading/error/empty states;
- accessibility considerations;
- responsive/platform behavior.

Implementation must follow `UX_UI.md`.

If no UI changes:

`None.`

---

## 10. Implementation Phases

Break substantial work into independently understandable phases.

### Phase 1 — TBD

**Goal:** TBD

Tasks:

- [ ] TBD
- [ ] TBD

Verification:

- [ ] TBD

### Phase 2 — TBD

**Goal:** TBD

Tasks:

- [ ] TBD
- [ ] TBD

Verification:

- [ ] TBD

### Phase 3 — TBD

**Goal:** TBD

Tasks:

- [ ] TBD
- [ ] TBD

Verification:

- [ ] TBD

Add or remove phases as needed.

Do not create artificial phases for trivial work.

---

## 11. Testing Strategy

Define the minimum meaningful verification.

Consider:

### Targeted Tests

- TBD

### Unit Tests

- TBD

### Integration Tests

- TBD

### UI / Runtime Verification

- TBD

### Regression Tests

- TBD

### Build / Typecheck / Lint

- TBD

Follow `DEVELOPMENT_WORKFLOW.md` for build, reload, restart, and health-check behavior.

---

## 12. Migration / Compatibility Plan

If not applicable:

`Not applicable.`

Otherwise document:

- migration steps;
- compatibility requirements;
- rollback expectations;
- data preservation;
- version considerations;
- deployment sequencing.

---

## 13. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| TBD | TBD | TBD |
| TBD | TBD | TBD |

Focus on realistic implementation or product risks.

Do not create speculative risk lists without value.

---

## 14. Dependencies

### Internal Dependencies

- TBD

### External Dependencies

- TBD

### Blocking Decisions

- TBD

If none:

`None.`

---

## 15. Rollback / Recovery

For risky changes, describe how to recover if implementation fails.

Examples:

- feature flag;
- configuration rollback;
- schema rollback strategy;
- previous implementation retained temporarily;
- reversible migration.

If rollback is trivial or unnecessary:

`No special rollback procedure required.`

---

## 16. Completion Checklist

Before marking this plan complete:

- [ ] Scope implemented.
- [ ] Acceptance criteria satisfied.
- [ ] Relevant tests/checks passed.
- [ ] Runtime verification completed where applicable.
- [ ] No unrelated behavior intentionally changed.
- [ ] `ARCHITECTURE.md` updated if durable architecture changed.
- [ ] `PROJECT_STATUS.md` updated if the project uses it and a durable checkpoint changed.
- [ ] Known limitations documented.
- [ ] Plan status changed to `Completed`.

---

## 17. Notes / Decisions

Use only for plan-specific decisions that do not belong in `ARCHITECTURE.md`.

- TBD

Keep this section short.

---

## 18. Plan Maintenance Rule

This file is a plan, not a development diary.

Update it when:

- scope changes;
- implementation strategy changes;
- phases change;
- acceptance criteria change;
- a major blocker changes execution order.

Do not update it for every small code edit.
