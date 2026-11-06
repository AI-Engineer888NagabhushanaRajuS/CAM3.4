# SPEC-022: Intake dashboard (Uppy + auto-sorted roles + animated scan) and manifest change view

Status: implemented and proven live 2026-11-06 (handoff/HANDOFF-2026-11-05.md section 9.15 has the evidence and what is NOT verified). Changes during the build: drafts store checked and not taken (the page already asks before leaving a dirty file); a hint to repeat the whole create request; the Changes tab also reloads earlier versions after a save. Source of ideas: Harish's BAM repo (`BAM-full-ui--main`): the Uppy tile dashboard in front of the twin-engine scan, and the SOW editor's colour-coded generated-vs-edited comparison (`sowCompare.ts`, `sowDiff.ts`, `sow.tsx`). Ported as RULES, not code (BAM's SOW diff is a prose/LCS engine on TipTap; the manifests are JSON in Monaco).

## I - Instructions
1. File selection for the assistant uses an Uppy Dashboard (tiles, remove, add more, drag and drop) in front of the existing scan. After the scan, every released workbook is recognised by what is IN it (auto-sorted: BOM workbook, volume file, QuoteWin, unknown) and shown with its role and a plain-words warning when the run would reject it. The user does not drag files into boxes; the sorting is automatic. Creating the RFQ goes through the existing confirmation card.
2. During the scan the dashboard animates what is really happening (wave n of m, per-file verdict landing), nothing invented.
3. The Manifests page gets a "Changes" tab: a GitLens-style inline diff of the text in the editor against a baseline (saved on disk, or the previous saved version), with coloured added / removed / modified lines and counts.
4. Cognee stays as built (backend of the assistant: memory service, bounded writes, status card). Nothing new there.

## S - Source
- The default routing (`Standard_BOM_Flow` in the live manifests) runs `standardize_scrub_bom`, which reads ONLY the file stored as role BOM: a workbook with a sheet named `SCRUB BOM` (case and spaces ignored, `_resolve_sheet_name`), optional `Settings` (volume) and `Batch` sheets. The separate Volume file is a required form field of `/api/rfq/upload` that this tool never reads (RFQ-000018: 4 volume + 4 batch rows came from the workbook's own sheets).
- `create_rfq` (daemon `rfq-chat-actions-parse.ts`) picks BOM and Volume among the released attachments by the words "bom" / "volume" in the file NAME.
- Real inputs: `Centum_Scrub_BOM.xlsx` (sheets SCRUB BOM, Settings, Batch), `Centum_BOM.xlsx` (sheet BOM: CPN, Description, MPN, Quantity ...), `Volume_File.xlsx` (Sheet1: CPN, Description, MPN, Vl1), `QuoteWin_File.xlsx` (Sheet0, "Awards Part Number" template). No costing-sheet sample exists: that role is NOT guessed.
- Save of a manifest writes `JSON.stringify(doc, null, 2)`; the copy kept in `manifests/.history/` is the original bytes, so a raw diff after the first save shows layout noise.

## A - Automation (decisions)
- Nothing is read before both engines pass. Recognition happens in the BRIDGE, on the released copy (openpyxl, read-only), and is reported as `role`, `role_label`, `role_reason`, `problems[]` in each scan result and in the attachment listing. The browser never parses a workbook.
- Roles: `scrub_bom` (sheet SCRUB BOM present), `bom` (a BOM sheet without SCRUB BOM: header CPN/MPN/Quantity), `volume` (header CPN + a Vl/V/Volume column, no BOM sheet), `quotewin` (the "Awards Part Number" template), `unknown`. A recognised `bom` carries the problem "this workbook has no 'SCRUB BOM' sheet; the first step would reject it (invalid input)".
- `create_rfq` prefers the role over the file name; a BOM without a SCRUB BOM sheet is refused with the plain reason and no confirmation card is issued (it would fail the same way). Unknown files fall back to the old name rule and the old questions.
- QuoteWin files are recognised and labelled with the stage they belong to; they are NOT sent through this dialog (their own upload calls stay as they are).
- Uppy is used only as picker and tiles: no upload plugin, no "Powered by Uppy", `triageFiles` stays the one source of the acceptance rules. Drag to a slot is not built (the sorting is automatic); the role is changed by asking the assistant, never by a hidden control.
- Manifest baselines: (1) "Saved on disk" = the text as loaded or last saved; (2) "Previous saved version" = the newest `.history` copy. Both sides are compared on normalised JSON (parse, 2-space stringify) when both parse, and the tab says so; with no earlier version it says that instead of showing a fake diff. History is read through two new GET routes whose file names are built on the server from the validated manifest path and a strict timestamp pattern; no client-supplied path reaches the file system.

## T - Tech stack
Allowed: `@uppy/core`, `@uppy/dashboard`, `@uppy/react` (v4, already installed), framer-motion (`useReducedMotion`), `@monaco-editor/react` DiffEditor (already installed), openpyxl in the bridge, existing daemon manifest routes. Not allowed: the `xlsx` package on untrusted files (known advisories), an upload plugin, new containers, anything in `docker-*` / `mcpjungle-server`.

## V - Variables
- Recognition reads at most the first 12 rows of at most 8 sheets per workbook, 25 MB cap already enforced by triage; a file that cannot be opened is `unknown` with the reason.
- History: newest 30 copies listed; one copy readable at a time (512 KB cap like the manifest itself).

## O - Output
- Scan result and attachment listing gain `role`, `role_label`, `role_reason`, `problems`.
- Dashboard result view: one row per file with a role chip, the verdict, and the problems; a "Create RFQ from these files" button that sends the sentence to the assistant (the confirmation card still follows).
- Manifests: tab "Changes" with a baseline selector, a colour legend and `+added / -removed / ~modified` counts.

## N - Non-goals / limits
- No costing-sheet recognition (no sample), no gerber ZIP in this dialog (not an accepted attachment type), no per-file role override control, no drag-to-slot.
- The "Volume file" is still demanded by `/api/rfq/upload` even though the scrub step ignores it; changing that endpoint is out of scope and is reported as a finding.
