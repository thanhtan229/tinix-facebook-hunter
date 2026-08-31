---
name: Hubspot
colors:
  primary: "#124548"
  secondary: "#180BB1"
  surface: "#000000"
  on-surface: "#FFFFFF"
  error: "#FF4800"
typography:
  body-md:
    fontFamily: HubSpot Serif Page Header Human
    fontSize: 80px
    fontWeight: 300
rounded:
  md: 8px
---

# Design System Inspired by HubSpot

## 1. Visual Theme & Atmosphere

HubSpot's design system embodies a modern, professional enterprise aesthetic with warmth and accessibility at its core. The visual language combines a sophisticated neutral foundation with vibrant accent colors that convey energy and action. The system prioritizes clarity and usability for complex business applications while maintaining an approachable, human-centered feel. Typography is elegant and hierarchical, leveraging serif headers for impact against clean sans-serif body text. The overall mood is confident yet inclusive, designed to inspire trust in a platform that manages critical business relationships.

**Key Characteristics**
- Clean, minimal aesthetic with generous whitespace
- Vibrant orange-red accents commanding attention for primary actions
- Sophisticated dark teal and navy secondary palette for depth
- Professional serif display type paired with humanist sans-serif body
- High contrast ratios supporting accessibility and readability
- Enterprise-grade polish with approachable warmth

## 2. Color Palette & Roles

### Primary
- **HubSpot Orange** (`#FF4800`): Primary call-to-action buttons, hero actions, and brand-defining interactive elements requiring maximum visibility and engagement.
- **Orange Dark** (`#C93700`): Hover and active states for primary actions, deepening the intensity during interaction.

### Accent Colors
- **Teal Dark** (`#124548`): Most frequently used secondary color; navigation elements, secondary headers, and data visualization accents creating visual hierarchy.
- **Teal Medium** (`#2F7579`): Supporting accent for sections, badges, and tertiary interactive elements.
- **Teal Light** (`#CAEBFF`): Background tints and soft hover states for information hierarchy.
- **Navy Deep** (`#15295A`): Dark accent for contrast and emphasis in specialized sections.
- **Navy Medium** (`#180BB1`): Interactive overlays and secondary accent highlights.
- **Brown Warm** (`#425B76`): Subtle accent for borders and dividers maintaining warmth.

### Interactive
- **Error Red** (`#D9002B`): Critical error states and destructive actions requiring immediate attention.
- **Warm Beige** (`#FCC6B1`): Gentle hover states and low-priority background tints.
- **Dust Brown** (`#9F2800`): Historical or deprecated action states.

### Neutral Scale
- **Text Primary** (`#1F1F1F`): Primary body text, labels, and most interface content—ensures readability and accessibility.
- **Text Secondary** (`#9B9897`): Disabled text, helper text, and de-emphasized information.
- **Text Muted** (`#B9CDBE`): Subtle dividers and very light secondary content.
- **Border Gray** (`#CFCCCB`): Input borders, divider lines, and subtle separators.
- **Background Light** (`#FCFCFA`): Minimal off-white background for forms and subtle containers.
- **Background Cream** (`#F8F5EE`): Warm off-white for larger surface areas, creating visual softness.
- **White** (`#FFFFFF`): Pure white for elevated surfaces, cards, and high-contrast backgrounds.
- **Black** (`#000000`): Reserved for dark mode support and maximum contrast overlays.

### Surface & Borders
- **Card Surface** (`#FFFFFF`): Elevated container backgrounds for grouped content.
- **Border Thin** (`1px solid rgba(0, 0, 0, 0.47)`): Input and form field borders.
- **Border Medium** (`2px solid rgba(0, 0, 0, 0.11)`): Button stroke outlines for secondary variants.

## 3. Typography Rules

### Font Family
**Primary Display:** HubSpot Serif Page Header Human (Georgia, serif fallback) — elegant, high-impact headers and hero messaging.

**Primary Body & UI:** HubSpot Sans (Lato, Helvetica, sans-serif fallback) — clean, modern interface text ensuring legibility across devices and sizes.

### Hierarchy

| Role | Font | Size | Weight | Line Height | Letter Spacing | Notes |
|------|------|------|--------|-------------|-----------------|-------|
| Display / H1 | HubSpot Serif | 80px | 300 | 95px | 0px | Hero headlines, page titles |
| Heading 2 | HubSpot Sans | 18px | 500 | 28px | 0px | Section headers, subsection titles |
| Heading 3 | HubSpot Sans | 16px | 500 | 28px | 0px | Card headers, category labels |
| Body Large | HubSpot Sans | 16px | 300 | 28px | 0px | Primary body text, descriptions |
| Body Regular | HubSpot Sans | 14px | 300 | 22px | 0px | Standard body copy, long-form content |
| Button / Label | HubSpot Sans | 16px | 400 | 18.4px | 0px | Interactive button text |
| Caption / Span | HubSpot Sans | 12px | 500 | 20px | 0px | Meta information, badges, captions |

### Principles
- **Hierarchy through weight:** Use weight changes (300 → 500 → 700) to establish visual priority rather than size alone.
- **Generous line height:** Maintain minimum 1.4× line height for body text; 1.5× for long-form content to enhance readability.
- **Serif for impact:** Reserve serif typography for hero sections and primary headlines (H1). Use sans-serif universally for UI elements, buttons, and body text for consistency.
- **Font size consistency:** Avoid fractional sizes; always use full pixel increments for rendering stability.
- **Color contrast:** Ensure all text meets WCAG AA contrast ratios; use `#1F1F1F` on light backgrounds and `#FFFFFF` on dark backgrounds.

## 4. Component Stylings

### Buttons

**Primary Button**
- Background: `#FF4800`
- Text color: `#FFFFFF`
- Font size: `16px`
- Font weight: `400`
- Font family: `HubSpot Sans`
- Padding: `16px 24px`
- Border radius: `8px`
- Border: `0px none`
- Box shadow: `none`
- Line height: `18.4px`
- Height: `52px` (auto-adjusts with padding)
- Hover state: Background `#C93700`, text remains `#FFFFFF`
- Active state: Background `#9F2800`, text remains `#FFFFFF`
- Disabled state: Background `#CFCCCB` (80% opacity), text `#9B9897`, cursor `not-allowed`

**Secondary Button**
- Background: `rgba(0, 0, 0, 0)`
- Text color: `#1F1F1F`
- Font size: `16px`
- Font weight: `400`
- Font family: `HubSpot Sans`
- Padding: `16px 24px`
- Border radius: `8px`
- Border: `2px solid #1F1F1F`
- Box shadow: `none`
- Line height: `18.4px`
- Height: `52px`
- Hover state: Background `#F8F5EE`, border remains `2px solid #1F1F1F`
- Active state: Background `#FCFCFA`, border `2px solid #124548`
- Disabled state: Border `2px solid #CFCCCB`, text `#9B9897`

**Ghost Button**
- Background: `rgba(0, 0, 0, 0)`
- Text color: `#124548`
- Font size: `14px`
- Font weight: `500`
- Font family: `HubSpot Sans`
- Padding: `8px 15px`
- Border radius: `0px`
- Border: `0px none`
- Box shadow: `none`
- Line height: `22px`
- Height: `38px`
- Hover state: Text color `#2F7579`, background `rgba(202, 235, 255, 0.3)`
- Active state: Text color `#124548`, text decoration underline
- Disabled state: Text `#CFCCCB`, cursor `not-allowed`

### Cards & Containers

**Standard Card**
- Background: `#FFFFFF`
- Text color: `#1F1F1F`
- Font size: `16px`
- Font weight: `300`
- Font family: `HubSpot Sans`
- Padding: `12px 12px 12px 12px`
- Border radius: `16px`
- Border: `0px solid rgba(0, 0, 0, 0)`
- Box shadow: `rgba(33, 51, 67, 0.12) 0px 2px 4px 0px`
- Line height: `28px`
- Min height: `220px`

**Elevated Container**
- Background: `#FCFCFA`
- Text color: `#1F1F1F`
- Padding: `24px 24px 24px 24px`
- Border radius: `0px`
- Border: `1px solid #CFCCCB`
- Box shadow: `rgba(33, 51, 67, 0.12) 0px 2px 4px 0px`
- Hover state: Background `#F8F5EE`

### Inputs & Forms

**Text Input Default**
- Background: `#FFFFFF`
- Text color: `#1F1F1F`
- Font size: `16px`
- Font weight: `300`
- Font family: `HubSpot Sans`
- Padding: `8px 16px 8px 16px`
- Border radius: `4px`
- Border: `1px solid rgba(0, 0, 0, 0.47)`
- Box shadow: `none`
- Line height: `28px`
- Height: `44px`
- Placeholder text: `#9B9897`, italic
- Focus state: Border `1px solid #FF4800`, box shadow `0 0 0 3px rgba(255, 72, 0, 0.1)`
- Disabled state: Background `#FCFCFA`, text `#9B9897`, border `1px solid #CFCCCB`, cursor `not-allowed`

**Text Input with Icon**
- Background: `#FFFFFF`
- Text color: `#1F1F1F`
- Font size: `16px`
- Padding: `8px 16px 8px 40px` (left padding accommodates icon)
- Border radius: `4px`
- Border: `1px solid rgba(0, 0, 0, 0.47)`
- Icon placement: `12px` from left edge
- Icon color: `#9B9897`
- Focus state: Border `1px solid #FF4800`, icon color `#124548`

**Form Label**
- Font size: `16px`
- Font weight: `300`
- Font family: `HubSpot Sans`
- Color: `#1F1F1F`
- Line height: `28px`
- Margin bottom: `8px`
- Required indicator (`*`): Color `#FF4800`

### Navigation

**Navigation Bar**
- Background: `#FFFFFF`
- Text color: `#1F1F1F`
- Font size: `16px`
- Font weight: `300`
- Font family: `HubSpot Sans`
- Padding: `16px 0px 16px 0px`
- Height: `52px`
- Border bottom: `1px solid #CFCCCB`
- Box shadow: `rgba(33, 51, 67, 0.12) 0px 2px 4px 0px`
- Z-index: `100` (sticky positioning)

**Navigation Link**
- Text color: `#1F1F1F`
- Font size: `16px`
- Font weight: `500`
- Padding: `0px 16px`
- Hover state: Color `#124548`, background `rgba(202, 235, 255, 0.2)`
- Active state: Color `#FF4800`, border bottom `2px solid #FF4800`
- Disabled state: Color `#CFCCCB`, cursor `not-allowed`

**Dropdown Menu**
- Background: `#FFFFFF`
- Border: `1px solid #CFCCCB`
- Border radius: `8px`
- Box shadow: `0 10px 25px rgba(33, 51, 67, 0.15)`
- Z-index: `99`
- Item padding: `12px 16px`
- Item hover: Background `#F8F5EE`, text color `#124548`

## 5. Layout Principles

### Spacing System
Base unit: `8px`

**Spacing Scale:**
- **Micro:** `4px` — icon padding, tight component spacing
- **XS:** `8px` — gaps between inline elements, button icon spacing
- **S:** `12px` — input padding, small card padding
- **M:** `16px` — standard padding, medium gaps
- **L:** `20px` — section gaps, list item spacing
- **XL:** `24px` — card padding, subsection margins
- **2XL:** `32px` — section margins, container padding
- **3XL:** `40px` — major section gaps
- **4XL:** `64px` — large container padding, hero sections
- **Hero:** `180px` — margin between hero and content sections

### Grid & Container
- **Max width:** `1440px` (full viewport width capped)
- **Column strategy:** Flexible 12-column grid for desktop; collapses to single column on mobile
- **Container padding:** `40px` on desktop, `20px` on tablet, `16px` on mobile
- **Gutter width:** `16px` between columns

### Whitespace Philosophy
HubSpot employs generous whitespace to reduce cognitive load and create visual breathing room. Key principles:
- Sections separated by minimum `64px` vertical spacing
- Content margins (left/right) scale with viewport size
- Card groups use `20px` gap between items
- Hero sections use `180px` top margin to emphasize importance
- Empty states include `40px` minimum vertical padding

### Border Radius Scale
- **None:** `0px` — inputs with sharp definition, navigation items
- **Small:** `4px` — input fields, small modals
- **Medium:** `8px` — buttons, dropdowns, secondary containers
- **Large:** `16px` — primary cards, feature blocks
- **Extra Large:** `24px` — hero cards, modal windows (when applicable)

### Border Widths
- **Thin:** `1px` — form inputs, divider lines, subtle borders
- **Medium:** `2px` — secondary button outlines, focus states
- **Thick:** `4px` — primary focus rings, emphasized borders (reserved for accessibility)

## 6. Depth & Elevation

| Level | Treatment | Use |
|-------|-----------|-----|
| Base | No shadow | Flat text, neutral backgrounds, minimal surfaces |
| Raised | `rgba(33, 51, 67, 0.12) 0px 2px 4px 0px` | Navigation bars, standard cards, containers |
| Elevated | `rgba(33, 51, 67, 0.12) 0px 2px 4px 0px` + `0px 4px 12px rgba(33, 51, 67, 0.08)` | Modals, dropdowns, popovers |
| Floating | `0 20px 40px rgba(0, 0, 0, 0.16)` | Overlays, toast notifications, tooltips |

**Shadow Philosophy:**
HubSpot uses subtle, minimal shadows to create depth without visual clutter. Shadows are achieved through controlled opacity and directional blur, emphasizing layer hierarchy through soft, diffused light. The system avoids harsh shadows, instead using low-opacity dark overlays to suggest elevation. This creates a soft, professional appearance while maintaining clear visual hierarchy.

### Opacity Levels
- **Disabled state:** `30%` opacity (`0.30`) — reduces visual prominence of inactive elements
- **Hover overlay:** `11%` opacity (`0.11`) — subtle background tint on interactive hover
- **Focus ring:** `10%` opacity (`0.10`) — very subtle focus indicator overlay
- **Modal backdrop:** `50%` opacity (`0.50`) — significant darkening to emphasize modal focus
- **Ghost hover:** `1%` opacity (`0.01`) — imperceptible background lift for minimal hover feedback

### Z-index / Layering
- **Base:** `1` — Standard document flow content
- **Sticky Navigation:** `100` — Persists above scrolling content
- **Dropdown/Menu:** `95` — Below modals, above base content
- **Dropdown Nested:** `99` — Ensures nested dropdowns appear above siblings
- **Modal Overlay:** `9989` — Large value ensures prominence, prevents interference
- **Modal Window:** `9999` — Maximum standard z-index for critical focus elements

## 7. Do's and Don'ts

### Do
- **Use HubSpot Orange (`#FF4800`) for primary CTAs** — Ensures immediate visual recognition and drives user action with consistent, high-impact color.
- **Maintain 8px base spacing** — All layouts should derive padding, margins, and gaps from multiples of 8px for visual harmony.
- **Pair serif headers with sans-serif body** — Use HubSpot Serif only for H1 display text; all UI, buttons, and body copy use HubSpot Sans for consistency.
- **Ensure WCAG AA contrast ratios** — All text must meet minimum 4.5:1 contrast on backgrounds to support accessibility.
- **Use `#1F1F1F` for primary text** — Provides optimal readability while reducing eye strain compared to pure black (`#000000`).
- **Apply generous whitespace around hero sections** — Use minimum `180px` margin between hero and content sections to establish visual hierarchy.
- **Implement focus states with 3px blur rings** — Clearly indicate keyboard navigation with subtle but visible focus indicators using `rgba(255, 72, 0, 0.1)`.
- **Scale shadows subtly** — Use low-opacity shadows (`rgba(33, 51, 67, 0.12)`) to suggest depth without visual heaviness.

### Don't
- **Avoid using `#000000` (pure black) for text** — Use `#1F1F1F` instead for softer, more accessible typography.
- **Don't apply multiple shadow layers on standard cards** — Limit to single `0px 2px 4px` shadow; reserve compound shadows for modals only.
- **Avoid mixing fonts** — Don't use serif body text or sans-serif headers; maintain strict separation between display and UI typography.
- **Don't use orange accents for secondary actions** — Reserve `#FF4800` exclusively for primary CTAs; use teal (`#124548`) for secondary elements.
- **Avoid opacity stacking** — Don't layer multiple transparent overlays; instead, compound opacity into a single value (e.g., `rgba(0, 0, 0, 0.50)` instead of nested 30% + 20%).
- **Don't set border radius below 4px** — Maintains visual softness and prevents rendering artifacts on small elements.
- **Avoid color contrast below 4.5:1 for text** — Always test text-to-background ratios; don't assume pale backgrounds meet accessibility standards.
- **Don't override focus states** — Ensure all interactive elements have visible keyboard focus indicators; never use `outline: none` without replacement.

## 8. Responsive Behavior

### Breakpoints

| Breakpoint | Width | Key Changes |
|------------|-------|-------------|
| Mobile | 320px – 639px | Single-column layout, 16px container padding, 12px gaps between sections, bottom-aligned navigation |
| Tablet | 640px – 1023px | 2-column grid, 20px container padding, 20px section gaps, horizontal navigation with dropdown support |
| Desktop | 1024px – 1440px | 12-column grid, 40px container padding, 64px section gaps, full horizontal navigation, max-width container |
| Wide Desktop | 1441px+ | Centered max-width container at 1440px, 40px lateral margin buffers, enhanced spacing scale |

### Touch Targets
- **Minimum size:** `44px × 44px` — All interactive elements (buttons, links, form controls) must meet this threshold for mobile accessibility.
- **Minimum spacing:** `8px` — Gaps between adjacent touch targets prevent accidental activation.
- **Button padding mobile:** `16px 24px` minimum to ensure comfortable touch interaction.
- **Input height mobile:** `48px` minimum on touch devices to facilitate accurate interaction.

### Collapsing Strategy
- **Navigation:** Collapses into hamburger menu below `640px` breakpoint; full horizontal navigation on tablet and above.
- **Cards:** Stack vertically on mobile (1 column), 2 columns on tablet, 3–4 columns on desktop based on container width.
- **Containers:** Reduce horizontal padding from `40px` (desktop) → `20px` (tablet) → `16px` (mobile).
- **Typography:** Reduce H1 from `80px` (desktop) → `48px` (tablet) → `32px` (mobile); maintain `300` weight throughout.
- **Spacing:** Scale section margins: `64px` (desktop) → `40px` (tablet) → `24px` (mobile).
- **Hero section:** Maintain `180px` top margin on desktop, reduce to `80px` on tablet, `40px` on mobile.

## 9. Agent Prompt Guide

### Quick Color Reference
- **Primary CTA:** HubSpot Orange (`#FF4800`)
- **Primary CTA Hover:** Orange Dark (`#C93700`)
- **Primary Text:** Text Primary (`#1F1F1F`)
- **Secondary Accent:** Teal Dark (`#124548`)
- **Tertiary Accent:** Teal Medium (`#2F7579`)
- **Background Default:** White (`#FFFFFF`)
- **Background Soft:** Background Cream (`#F8F5EE`)
- **Borders:** Border Gray (`#CFCCCB`)
- **Error State:** Error Red (`#D9002B`)
- **Disabled Text:** Text Secondary (`#9B9897`)

### Iteration Guide
1. **All primary CTAs use HubSpot Orange (`#FF4800`) on white background** — Implements 10.7:1 contrast ratio, exceeding WCAG AAA standards. Hover state darkens to `#C93700` with same contrast preservation.

2. **Typography follows strict size + weight hierarchy** — H1 uses `80px` / `300` weight, H2 uses `18px` / `500` weight, body uses `14px` / `300` weight. Never interpolate between these sizes; always use nearest scale value.

3. **Spacing derives exclusively from 8px base unit** — All padding, margins, and gaps use multiples of 8px (8, 12, 16, 20, 24, 32, 40, 64, 180). Ensures alignment integrity and visual consistency.

4. **Card shadows use single 2px blur layer only** — Apply `rgba(33, 51, 67, 0.12) 0px 2px 4px 0px` uniformly. Compound shadows (multiple layers) reserved for modal-level elevation only.

5. **Focus indicators use 3px blur orange ring at 10% opacity** — Implement `box-shadow: 0 0 0 3px rgba(255, 72, 0, 0.1)` on all interactive elements for keyboard accessibility without visual dominance.

6. **Form inputs use `4px` border-radius with `1px` solid border** — Border color is `rgba(0, 0, 0, 0.47)`. On focus, border becomes `#FF4800` with orange glow. Never remove border on focus.

7. **Buttons maintain 52px height (including padding)** — Primary buttons use `16px 24px` padding with `8px` border radius. Secondary buttons mirror dimensions with 2px outer border. Never reduce button height below `44px` for accessibility.

8. **Navigation bar is sticky at z-index 100** — Background `#FFFFFF` with `1px solid #CFCCCB` bottom border. Active navigation links display with `#FF4800` color and 2px bottom border. Dropdowns appear at z-index `99`.

9. **Hero sections implement 180px top margin on desktop, scale down on responsive breakpoints** — Tablet reduces to `80px`, mobile to `40px`. Maintains visual priority and breathing room around hero content.

10. **Disable states apply 30% opacity reduction with `#CFCCCB` backgrounds** — Disabled buttons, inputs, and links show reduced opacity (`0.30`) and use `#CFCCCB` (border gray) for text/fills. Cursor changes to `not-allowed` on interactive disabled elements.