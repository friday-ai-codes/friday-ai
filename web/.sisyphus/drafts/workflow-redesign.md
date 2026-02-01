# Draft: Workflow List Redesign
## Requirements (confirmed)
- Target Page: `web/src/pages/workflows/index.vue`
- Visual Style: Modern, professional, "developer-grade" (Vercel/Linear/GitHub style).
- Layout: Table/List view (primary) instead of Grid.
- Features:
 - Columns: Status, Name/Description, Trigger, Success Rate/Last Run, Actions.
 - Header: Search/Filter UI.
 - Empty State: Professional design.
 - Responsive: Mobile fallback.
- Explicit Exclusion: Remove "background decorations" (blobs).
## Technical Decisions
- **Framework**: Vue 3 + Shadcn Vue.
- **Component**: Use `Table` (Shadcn) for the main list.
- **Icons**: Lucide Vue (standard with Shadcn).
## Open Questions
- Do we have the `Table` component installed?
- What exactly constitutes "Success Rate"? Do we have this data in the `Workflow` object?
- "Last Status" vs "Last Run" - are these the same?
- Do we need pagination now or is infinite scroll/load all fine?
## Scope Boundaries
- IN: `index.vue` redesign, new components for Table/Empty State if missing.
- OUT: changing backend API, modifying individual workflow detail pages (unless shared components change).
