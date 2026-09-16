# Tinix Design System & Product UX Principles

> **Global UI/UX Standard for the Tinix Ecosystem**

This document defines the shared **visual language, interaction principles, UX standards, and design compliance rules** for applications in the Tinix ecosystem.

It is intentionally **framework-agnostic and architecture-agnostic**.

It does **not** mandate a specific frontend framework, backend stack, database, packaging strategy, operating system runtime, browser automation model, or deployment topology.

Those implementation decisions belong in each project's own:
- `PROJECT_SPEC.md`
- `ARCHITECTURE.md`
- `AGENTS.md`
- relevant ADRs and subsystem specifications

If a project-specific specification explicitly overrides a rule in this document, the project-specific rule takes precedence for that project.

---

# 1. Purpose

Tinix applications should feel like members of the same product family even when they are implemented with different technologies.

The purpose of this document is to ensure consistency in:

- visual identity
- typography
- color semantics
- spacing
- component behavior
- navigation patterns
- feedback states
- form behavior
- motion
- accessibility
- information hierarchy
- UX writing
- responsive behavior
- design review and compliance

The goal is not to force every Tinix app to have the exact same layout.

The goal is to ensure every Tinix app shares the same **design language and interaction philosophy**.

---

# 2. Core Product Philosophy

Every Tinix application should follow these product principles unless the project explicitly requires otherwise.

## 2.1. Clarity Before Decoration

The interface should make the user's next action obvious.

Prefer:
- clear hierarchy
- descriptive labels
- predictable controls
- meaningful whitespace
- visible system status

Avoid:
- decorative complexity
- excessive gradients
- unnecessary animation
- ambiguous icon-only actions
- visual effects that compete with content

## 2.2. Professional but Warm

Tinix should feel:
- polished
- professional
- approachable
- editorial
- modern
- calm
- trustworthy

Avoid interfaces that feel overly technical, sterile, aggressively futuristic, game-like, or visually noisy.

## 2.3. Predictable Interaction

The same interaction should behave the same way across the application.

Examples:
- primary actions use the same visual treatment
- destructive actions always look destructive
- validation errors appear in a consistent location
- loading indicators follow the same pattern
- dialogs behave consistently
- navigation active states are always recognizable

## 2.4. Progressive Disclosure

Show the user what they need first. Advanced or infrequently used controls should be collapsed, placed under advanced settings, moved to secondary actions, or shown contextually.

## 2.5. Human-Readable System State

The UI should clearly communicate what is happening, what completed, what failed, whether progress was preserved, what requires user action, and what to do next.

---

# 3. Visual Identity

Tinix visual identity should communicate reliability, precision, warmth, creative confidence, productivity, and modern craftsmanship.

The visual language should remain restrained enough for long working sessions.

---

# 4. Typography

Tinix uses a two-family typography system.

## 4.1. Display Font

```css
--font-display: "Lora", Georgia, serif;
```

Preferred use:
- main page titles
- hero titles
- selected editorial emphasis

Default page title:

```css
font-family: var(--font-display);
font-size: 32px;
font-weight: 400;
line-height: 1.25;
letter-spacing: -0.02em;
```

Do not overuse the display font in dense operational interfaces.

## 4.2. UI Font

```css
--font-ui: "Plus Jakarta Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
```

Use for body copy, navigation, buttons, forms, tables, labels, dialogs, and secondary headings.

Default body:

```css
font-family: var(--font-ui);
font-size: 14px;
line-height: 1.5;
```

## 4.3. Typography Hierarchy

```text
Display / Page Title     32px / 400
Section Heading          20–24px / 600
Subsection Heading       16–18px / 600
Body                     14px / 400
Small / Secondary        12–13px / 400–500
Label                    12–13px / 600
Eyebrow                  11px / 700 / uppercase
Caption                   11–12px / 400
```

## 4.4. Eyebrow Labels

```css
font-size: 11px;
font-weight: 700;
text-transform: uppercase;
letter-spacing: 0.14em;
color: var(--color-primary);
```

Use sparingly.

---

# 5. Color System

All colors should be expressed as semantic design tokens. Do not hard-code arbitrary colors directly inside individual components unless there is a documented reason.

## 5.1. Brand Colors

```css
:root {
  --color-primary: #FF4800;
  --color-primary-hover: #C93700;
  --color-primary-active: #9F2800;
  --color-primary-subtle: rgba(255, 72, 0, 0.10);
  --color-primary-focus: rgba(255, 72, 0, 0.15);
  --color-teal-dark: #124548;
  --color-teal-medium: #2F7579;
  --color-navy-deep: #15295A;
  --color-navy-medium: #180BB1;
}
```

Primary orange is the main Tinix brand accent. Use it for primary actions, focus emphasis, key interactive highlights, and selected brand moments. Do not flood the interface with orange.

## 5.2. Neutral Surfaces

```css
:root {
  --color-bg-body: #F8F5EE;
  --color-bg-surface: #FFFFFF;
  --color-bg-subtle: #FCFCFA;
  --color-border: #CFCCCB;
  --color-border-subtle: #EAE8E4;
  --color-text-primary: #1F1F1F;
  --color-text-secondary: #5F6368;
  --color-text-muted: #9B9897;
}
```

Projects with different environmental needs may adapt the surface palette while preserving semantic roles.

## 5.3. Semantic Status Colors

```css
:root {
  --color-success: #124548;
  --color-success-bg: #DFF2E7;
  --color-success-border: #B8E4CC;
  --color-warning: #8A5700;
  --color-warning-bg: #FFF0C9;
  --color-warning-border: #E9C66E;
  --color-danger: #D9002B;
  --color-danger-bg: #F7DFDC;
  --color-danger-border: #E8A4A1;
  --color-info: #15295A;
  --color-info-bg: #CAEBFF;
  --color-info-border: #A6DCFF;
}
```

Do not communicate status using color alone. Pair color with text, icon, label, or badge.

---

# 6. Spacing System

Tinix uses an 8px-oriented spacing scale with 4px half-step support.

```css
--space-2xs: 4px;
--space-xs: 8px;
--space-sm: 12px;
--space-md: 16px;
--space-lg: 20px;
--space-xl: 24px;
--space-2xl: 32px;
--space-3xl: 40px;
--space-4xl: 64px;
```

Use spacing tokens rather than arbitrary values.

---

# 7. Border Radius

```css
--radius-sm: 4px;
--radius-md: 8px;
--radius-lg: 16px;
--radius-xl: 24px;
--radius-full: 9999px;
```

Recommended use:

```text
4px      small chips / compact controls
8px      buttons / inputs / selects
16px     cards / panels / dialogs
24px     large hero or feature containers
full     badges / avatars / pills
```

---

# 8. Elevation

Tinix favors relatively flat layouts with selective depth.

```css
--shadow-base: none;
--shadow-raised: 0 2px 4px rgba(33, 51, 67, 0.08), 0 1px 2px rgba(33, 51, 67, 0.04);
--shadow-elevated: 0 4px 12px rgba(33, 51, 67, 0.10), 0 2px 4px rgba(33, 51, 67, 0.06);
--shadow-floating: 0 20px 40px rgba(0, 0, 0, 0.16);
```

Use raised for cards, elevated for hover/selected surfaces, and floating for modal/popover/toast.

---

# 9. Motion

Motion should support comprehension, not decoration.

```text
Hover / button transitions     ~150ms
Panel / tab transitions        ~200–250ms
Dialog / drawer transitions    ~200–300ms
```

Avoid long animation, bouncing effects in productivity flows, continuous decorative motion, or transitions that delay actions. Respect reduced-motion preferences where relevant.

---

# 10. Layout Principles

There is no single mandatory Tinix layout for every product. Layout should match the application type while preserving Tinix visual language.

## 10.1. Desktop Productivity Apps

Preferred default:

```text
Fixed or collapsible sidebar
        +
Fluid main workspace
```

Typical sidebar width: `220–260px`.
Typical workspace max width: `1280–1440px`.

## 10.2. Simple Utilities

A single-purpose tool may use a compact app header and one primary workspace. Do not force a sidebar when navigation depth does not justify one.

## 10.3. Creative Tools

Creative/editorial apps may use a top bar, left tool rail, central canvas/workspace, and optional right inspector.

## 10.4. Mobile Apps

Use stack navigation, bottom navigation, tab navigation, or contextual action sheets. Do not reproduce desktop sidebar patterns on mobile.

## 10.5. SaaS / Responsive Web

Responsive apps may use desktop sidebar, tablet compact sidebar, and mobile drawer or bottom navigation.

---

# 11. Navigation

Navigation should be predictable, shallow where possible, consistently positioned, and visually obvious when active.

Rules:
- one dominant primary navigation pattern per app
- active state must be clearly visible
- destructive actions should be separated from routine navigation
- breadcrumbs only when hierarchy is deep enough to justify them

Numbered navigation items may be used in workflow-heavy desktop tools, but are not mandatory.

---

# 12. Buttons

Every Tinix app should define consistent button roles:

```text
Primary
Secondary
Ghost / Tertiary
Danger
```

Primary is for the most important action in context. Danger is only for destructive or irreversible actions. Disabled controls should look disabled, remain legible, and reject interaction.

---

# 13. Form Controls

Recommended desktop/web control height: `36–40px`, default `38px`.

Controls should use semantic border tokens, consistent padding, `--radius-md`, and visible focus state.

```css
box-shadow: 0 0 0 3px var(--color-primary-focus);
```

---

# 14. Form UX

Forms should use:
- visible labels
- concise help text
- inline validation
- errors near the relevant field
- clear required-field indication
- reasonable defaults
- double-submit prevention
- visible loading state

Do not rely on placeholder text as the only label.

---

# 15. Cards and Panels

Cards should group related information, not merely decorate the layout.

Default panel:

```text
white surface
subtle border
16px radius
raised shadow
20–24px internal padding
```

Avoid excessive nested cards.

---

# 16. Status Badges

Use pill-shaped compact badges with semantic text and color.

```text
Success     green/mint
Warning     amber/yellow
Error       red/rose
Info        blue/navy
Neutral     gray
```

---

# 17. Tables and Data-Dense Interfaces

For data-heavy screens, support when relevant:
- sorting
- filtering
- search
- pagination
- virtualization
- sticky headers
- bulk selection
- bulk actions

Do not render extremely large datasets into the DOM at once.

---

# 18. Loading States

Use the least disruptive loading pattern appropriate to context.

```text
Small control action
→ inline spinner

Local component loading
→ skeleton / component placeholder

Full page first load
→ structured page skeleton

Long-running process
→ progress UI with status text
```

Avoid full-screen blocking spinners for small local operations.

---

# 19. Empty States

A useful empty state explains:
1. what is empty
2. why it may be empty
3. what the user can do next

Avoid generic “No data.” messages when a useful next action is available.

---

# 20. Error States

Errors should be actionable. Whenever possible include:
- what failed
- why
- whether progress was preserved
- what the user can do next

Technical details may be available in logs or expandable diagnostics.

---

# 21. Success Feedback

Use success feedback proportionally.

```text
Small completed action
→ toast or inline confirmation

Major workflow completion
→ persistent success state / summary

Background operation
→ status update + notification when relevant
```

Do not use a modal for every successful action.

---

# 22. Notification Hierarchy

Use:
- Toast for short-lived success/info
- Inline message for contextual local issues
- Banner for persistent page/application issues
- Modal for blocking decisions or irreversible confirmation

Do not use modal dialogs as generic notifications.

---

# 23. Destructive Actions

Destructive actions should:
- use danger styling
- describe what will happen
- require confirmation when irreversible or high impact
- be separated from routine actions where practical

Confirmation text should be specific rather than generic.

---

# 24. Long-Running Operations

For operations that take meaningful time, show:
- current state
- progress where measurable
- processed count where useful
- failure count where useful
- pause/cancel controls if supported
- completion summary

The interface must not appear frozen.

---

# 25. Accessibility

Minimum expectations where applicable:
- keyboard-accessible controls
- visible focus states
- semantic HTML or native semantics
- labels for form controls
- meaningful accessible names for icons
- sufficient contrast
- state not represented by color alone
- appropriate heading hierarchy
- reduced-motion consideration

---

# 26. Responsive Design

Responsive complexity should match the actual product.

Desktop-only apps should not overinvest in mobile layouts. Responsive web apps should intentionally define desktop, tablet, and mobile behavior.

---

# 27. Iconography

Use one primary icon family per project.

Rules:
- consistent stroke/fill style
- consistent sizing
- icons reinforce text rather than replace essential labels unnecessarily
- destructive icons must be unambiguous

---

# 28. UX Writing

Tinix UI copy should be concise, direct, calm, specific, and human-readable.

Prefer action labels like:

```text
Create project
Export files
Retry upload
Reconnect account
Save changes
```

Avoid vague labels like “OK”, “Process”, or “Execute” when a more specific verb exists.

---

# 29. Content Hierarchy

Recommended order:

```text
Context / eyebrow
Page title
Short explanation
Primary action
Primary content
Secondary information
Advanced controls
```

Not every page requires every layer.

---

# 30. Component Reuse Rules

Coding agents and developers must:
- reuse existing components before creating new ones
- use design tokens instead of arbitrary hard-coded values
- avoid duplicate button/input/card variants
- avoid changing shared component behavior locally without a documented reason
- update shared components when a change should apply globally

A local exception should not silently become a second design system.

---

# 31. Design Token Rules

Design tokens are the preferred source of truth for color, typography, spacing, radius, elevation, motion, and layout constants.

Projects may map these tokens into CSS variables, Tailwind theme, React theme objects, Flutter ThemeData, SwiftUI styles, Android Compose themes, or another native system.

Technology may differ; semantic roles should remain recognizable.

---

# 32. Framework Independence

Tinix Design System does not require React, Vue, Svelte, vanilla JavaScript, Flutter, SwiftUI, Jetpack Compose, or any specific frontend framework.

The design system governs what the interface should feel and behave like, not how implementation must be written.

---

# 33. Dark Mode

Dark mode is optional unless the project requires it.

If implemented:
- preserve semantic roles
- preserve brand identity
- do not simply invert colors
- validate contrast
- keep surface hierarchy distinguishable

---

# 34. Design Exceptions

A project may override Tinix Design System when there is a concrete product requirement, such as mobile platform convention, accessibility requirements, specialist creative canvas, kiosk/touch interface, high-density enterprise grid, or embedded environment.

When overriding a major global rule:
1. document the reason
2. keep unaffected Tinix principles intact
3. prefer a project-specific specification or ADR

Do not silently diverge.

---

# 35. Project-Specific UI Specification

Every non-trivial Tinix application should maintain a project-specific UI specification, recommended as:

```text
docs/UI_UX_SPEC.md
```

It should define:
- application-specific layout
- navigation structure
- screen list
- special components
- domain-specific workflows
- project-specific overrides

Relationship:

```text
TinixDesign.md
      ↓
Global design language

docs/UI_UX_SPEC.md
      ↓
Project-specific application
```

---

# 36. Coding Agent Rules

Before implementing or modifying frontend/UI, a coding agent must:

1. Read `TinixDesign.md`.
2. Read the project's `UI_UX_SPEC.md` if present.
3. Inspect existing shared components and design tokens.
4. Reuse the existing design system.
5. Avoid creating new visual conventions without a clear requirement.

The agent must not:
- invent arbitrary colors
- introduce a second typography system
- create one-off button variants unnecessarily
- use inconsistent spacing
- bypass shared components without reason
- redesign unrelated screens while implementing a scoped feature

---

# 37. UI Quality Gate

Before completing any phase that changes UI, review:

- [ ] Does the screen follow Tinix visual language?
- [ ] Are typography roles consistent?
- [ ] Are semantic color tokens used?
- [ ] Is spacing based on the defined scale?
- [ ] Are radius/elevation patterns consistent?
- [ ] Are existing components reused?
- [ ] Are loading states handled?
- [ ] Are empty states handled?
- [ ] Are error states actionable?
- [ ] Is primary/secondary/destructive action hierarchy clear?
- [ ] Are forms labeled and validated consistently?
- [ ] Is accessibility appropriate?
- [ ] Is navigation consistent with the rest of the app?
- [ ] Does the screen avoid unnecessary visual noise?
- [ ] Are large datasets handled efficiently?
- [ ] Are project-specific deviations documented?

Any significant inconsistency should be fixed before the phase is considered complete.

---

# 38. Tinix Global Design Compliance Checklist

## Brand
- [ ] Primary Tinix visual identity is recognizable.
- [ ] Typography follows the shared hierarchy.
- [ ] Brand orange is used intentionally rather than excessively.

## Components
- [ ] Buttons follow common roles.
- [ ] Forms use consistent height, radius, and focus behavior.
- [ ] Cards/panels follow shared grouping patterns.
- [ ] Status colors use semantic roles.

## Layout
- [ ] Navigation matches the product type.
- [ ] Page hierarchy is clear.
- [ ] Spacing is consistent.
- [ ] Dense content remains readable.

## States
- [ ] Loading states exist.
- [ ] Empty states are useful.
- [ ] Errors are actionable.
- [ ] Long-running operations communicate progress.

## Interaction
- [ ] Destructive actions are clearly distinguished.
- [ ] Confirmation is used when appropriate.
- [ ] Feedback is proportionate to the action.
- [ ] Interaction patterns are predictable.

## Accessibility
- [ ] Focus states are visible.
- [ ] Controls have appropriate labels.
- [ ] Color is not the sole carrier of state.
- [ ] Contrast is sufficient for normal use.

## Consistency
- [ ] No second ad-hoc design system has appeared inside the project.
- [ ] Project-specific exceptions are documented.
- [ ] New UI matches existing Tinix applications in overall visual language.

---

# 39. Source-of-Truth Rule

For Tinix applications, use this design priority unless the project explicitly defines another order:

```text
1. Latest explicit user/product decision
2. Project-specific UI_UX_SPEC.md
3. TinixDesign.md
4. Existing shared component implementation
5. Individual screen implementation
```

If a screen conflicts with the design system, the screen should normally be corrected rather than redefining the system.

---

# 40. Final Principle

Tinix applications do not need to look identical.

They should feel related.

A user moving from one Tinix product to another should immediately recognize:
- the typography
- the warmth
- the spacing discipline
- the interaction hierarchy
- the visual restraint
- the semantic feedback
- the product philosophy

That consistency is the purpose of this document.
