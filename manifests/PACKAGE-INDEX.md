# CAM 3.4 documentation package - WORKING DRAFT (5 Nov 2026)

Status: WORKING DRAFT pending NRS's promised 3.4 material and review. Private - contains
internal project material; no credentials are included. Do not share outside the project.

## What is what

### Main document
- `CAM 3.4 - Complete Documentation (WORKING DRAFT - 5 Nov 2026).pdf` - the full 3.4 doc
  (36 pages) with all diagrams and live app evidence embedded at readable resolution.
  Living source: Google Doc "CAM 3.4 - Complete Documentation (WORKING DRAFT)" in the
  INSTINCT BRAIN > Architecture and project archive folder (private).

### diagrams/ - engineering diagrams referenced by the doc (full-resolution PNGs)
- cam34_d1_runtime.png - CAM 3.3 runtime architecture, as built (measured from source)
- cam34_d2_formulas.png - formula system and generation rules
- cam34_d3_migration.png - CAM 3.4 migration plan, phases 0-6
- cam34_d4_domain.png - RFQ domain map

### app-evidence/ - live captures from the deployed app, 5 Nov 2026 (read-only check)
- cam34_app02_login.png - login page, branded "CAM 3.3"
- cam34_app03_three_pane.png - three-pane layout (left 9-stage wizard / middle Assistant / right results)
- cam34_app05_rfq232_done.png - RFQ-000232 Quote Readiness Package, eight [DONE] rows (matches NRS's photo)
- cam34_app07_stub.png - Assistant answering a generic prompt with the "coming soon" stub
- cam34_app12_query.png - advertised query "How many FGs does RFQ-000167 contain?" returned
  "RFQ RFQ-000167 contains 1 FG." (returned value, not independently validated)
- cam34_app14_stage8_locked.png - navigation limitation: stage 8 locks after advancing to stage 9
- cam34_app17_fresh.png - fresh page load restores the Quote Readiness view
- cam34_app19_superset.png - stage-9 analytics = embedded Apache Superset (port 8088);
  displayed values, not independently validated
- user_ui_annotated.png - NRS's original UI photo, annotated (middle-pane label updated to
  the 5 Nov reproduced finding)

### harish-jsons-DRAFTS/ - Harish's ISATVON JSON manifests (Drive "JSON Manifest" folder)
ALL DRAFTS describing the 3.4/4.0 design direction. None of this is implemented runtime.
- agent_manifest__v1.5.0-DRAFT__CAM4.0-labels.json - 1 agent, 10 skills, 40 sub-skills;
  labelled "CAM 4.0 RFQ Automation Agent", Temporal + Bifrost orientation. (The Drive folder
  holds two identical copies of this file; one is included.)
- skill_01..skill_10__v1.5.0-DRAFT.json - the ten skills (Input Standardization, Feature
  Extraction, Feasibility & Risk, Distributor & Source Selection, Supplier RFQ/Quoting Tools,
  SAP/API Cost Extraction, Quote Validation & Comparison, Costed BOM, Reporting via BullMind,
  Sales Quote), 4 sub-skills each. All v1.5.0-draft, status DRAFT.
- cam_isatvon_manifest__v0.1.0-DRAFT.json - Centum CAM 16-Report Workbook Generator,
  one manifest covering all 16 reports (Dify + Jungle orientation). v0.1.0, status DRAFT.

### repo-manifests-v1.4.0-APPROVED/ - the AS-BUILT tool manifests (CAM repo, backend/docs)
These describe the tools as they exist today (written after the code). Separate generation
from Harish's drafts above - do not mix them.
- 4 intake + 6 reporting manifests, all v1.4.0: 8 APPROVED, 2 APPROVED_INACTIVE
  (Standardize ERP Export and Enrich CBOM with ERP Data - "not currently exposed").

### supporting-docs/
- CAM Reports - Unified ISATVON JSON Manifest + Conversion Prompts (for Harish).pdf -
  the unified-manifest conversion notes exported from the Drive Google Doc.

## Key distinctions this package preserves
- v1.4.0 APPROVED manifests = what is built. v1.5.0-draft / v0.1.0 DRAFT = design inputs
  for 3.4/4.0, not implemented runtime.
- App evidence is from a read-only hands-on check (5 Nov 2026, 4:33-4:58 PM IST). No workflow
  was run, no business data changed, no skill invoked.
- Dashboard numbers and assistant answers are displayed/returned values, not independently
  validated business facts.
