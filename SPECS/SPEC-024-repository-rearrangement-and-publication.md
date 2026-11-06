# SPEC-024: repository rearrangement, duplicate merge, document polish and publication

| | |
|---|---|
| Status | In progress (plan written 2026-11-06, results are filled in at the end of this file) |
| Owner | Harish / Nagabhushana Raju S (Digibull) |
| Depends on | SPEC-001 to SPEC-023 (nothing in `CAM-Source` changes behaviour) |
| Safety net | Full copy of the folder (without `node_modules`) at `C:\CAM[3.4]-RFQ_centum_BACKUP-2026-11-06` (5,765 files, 1,270 MB, verified file-for-file) |

## 1. Context

The project folder `C:\CAM[3.4]-RFQ_centum` has grown by hand for two weeks: reference diagrams, the CAM 3.3 and BAM source snapshots, the domain knowledge base, the SPECS, the handoff notes of four agent sessions, proof recordings and the working source in `CAM-Source`. It is now to be published to GitHub (`AI-Engineer888NagabhushanaRajuS/CAM3.4`). Before that it needs to be readable by someone who has never seen it: one front door, one index per folder, no accidental copies, and the rough notes typed in a hurry turned into proper documents.

## 2. Rules (decided by the owner)

1. **Same folder format.** The top-level layout stays: `.claude`, `CAM-Source`, `Eng_Diagram [ Must follow ]`, `Reference[KT]` (with `DOMAIN KNOWLEDGE`, `Extras`, `Full Details`, `Source Code`), `SPECS`, `acceptance_evidence`. No new top-level folders. Loose files at the top move into the existing `SPECS\handoff`.
2. **Nothing is removed that carries information.** Credentials, logins, test accounts, setup scripts and the old session log stay (the file `SECRETS.md` holds only environment-variable placeholders; the test login `srim-test-2026` is part of `LoginPage.tsx`). Rough notes are rewritten, and the verbatim originals are kept in `SPECS\handoff\original-notes\`.
3. **Only these are git-ignored:** `node_modules/`, the bundled Node runtime (`accomplish-ui/apps/desktop/resources/nodejs/`, 87 MB `node.exe` x2) and `.env` files (`.env.example` stays). Everything else is pushed. Rules that already exist in nested `.gitignore` files (for example `CAM-Source/.gitignore`: client BOM uploads, `*.duckdb`, `dist/`, logs) keep working; they are listed in section 6.
4. **Merge only true duplicates.** A file is merged away only when it is byte-identical to a kept copy AND it is a leftover or a wrapper (a repeated test upload, a download zip of a folder that is already extracted, a copy of a document placed in a "copies" folder). Identical files that belong to a self-contained unit (a source snapshot's own `desktop` and `web` apps, one proof take's screenshots) stay, so each unit stays complete. Every merge is logged.
5. **Documents are polished, not reinterpreted.** Wording is cleaned, structure and headings added, Google-Docs escape artefacts removed; facts, labels (SOURCE / DOC / REPORTED / PROPOSAL / OPEN) and open questions are carried over unchanged.

## 3. Rearrangement (old to new)

| Old | New | Why |
|---|---|---|
| `Start Here.txt`, `001.txt` | `README.md` (front door) and `Start Here.md` (reading order); originals in `SPECS\handoff\original-notes\` | two rough notes that said the same thing in two places |
| `HANDOFF-2026-11-03.md`, `HANDOFF-2026-11-05.md`, `CAM-3.4-HANDOFF.md`, `CAM-3.4-RUNNING-STACK.md`, `MEMORY-TRANSFER-2026-11-05.md`, `old-session.jsonl` | `SPECS\handoff\` | one place for session history; the folder already held the recipes and the patch |
| `Reference[KT]\Full Details\json ,. .. other topics.txt` | `Reference[KT]\Full Details\CAM 3.3 to 3.4 - how the JSON manifests meet the code.md` | a working note with a pasted chat reply at the end |
| `Reference[KT]\Source Code\SSource Code REPO Confussion.txt` | `Reference[KT]\Source Code\README - which repo is the main code.md` | a note typed in haste, now the folder's guide |
| `Reference[KT]\Full Details\CAM_3.4_documentation_package_2026-11-05_WORKING_DRAFT.zip` | extracted to `...\CAM_3.4_documentation_package_2026-11-05\` | the PDF, diagrams and manifest copies become viewable on GitHub |
| `GOAL_PROMPT.md`, `.claude\CLAUDE.md` | same place, paths and folder map refreshed | they pointed at the old locations |
| (new) `README.md` in the root, `Reference[KT]`, `Eng_Diagram [ Must follow ]`, `SPECS`, `acceptance_evidence` | index pages | each folder says what it holds |

## 4. Duplicate merge

| Group | Kept | Merged away | Reason |
|---|---|---|---|
| `Encyclopedia 4 - ... (1).md` | the file without `(1)` | 1 file | byte-identical |
| `RE 1` and `RE 2` documents inside `(2) CAM Internal folder and RE docs - copies, originals untouched` | the copies directly in `Extras\Reverse Engineering` | 2 files | byte-identical |
| Google Drive download zips of `Domain Knowledge` and `Teaching Series` | the extracted folders | 2 zips | every entry already extracted, same size |
| `BAM-full-ui--main.zip` (53 MB) | the extracted `BAM-full-ui--main` | 1 zip | all 131 entries identical on disk |
| repeated test uploads in `BuLLMQuote-SRIM\fastmcp-router\staged\inbox` | one file per content hash (or the copy in `acceptance_evidence\test_inputs`) | see the log | runtime leftovers, 93 identical Harness BOMs and 27 identical Gerber zips among them |
| `cell_level_formulas_part1..8.zip` | all eight | none | the eight archives differ (checked by hash) |

The complete list (every removed path, its kept twin and the hash) is in `SPEC-024-rearrangement-log.csv`.

## 5. Publication

1. A top-level git repository is created at `C:\CAM[3.4]-RFQ_centum`. The 67 commits of `CAM-Source` are kept: they are merged in under the `CAM-Source/` prefix (subtree-style merge, no history rewritten). The nested `.git` of the CAM 3.3 snapshot (`BuLLMQuote-SRIM`) is flattened into the tree; its own repository folder is kept in the backup.
2. Pushed to `main` of `AI-Engineer888NagabhushanaRajuS/CAM3.4` in chunks of about 200 to 300 MB, one commit per chunk (see section 7).
3. The repository is made private before the first push (it holds Centum material).

## 6. Acceptance

- [ ] Backup exists and matches the source file for file.
- [ ] Every merged file is in the CSV log with its kept twin; nothing else was deleted.
- [ ] No path that existed before is unreachable: moved files are listed in section 3, every reference to a moved file was updated (checked by search).
- [ ] The five polished notes keep all their facts (originals preserved).
- [ ] `git status` shows nothing untracked except what rule 3 ignores and what the nested `.gitignore` files already ignored (listed in section 8).
- [ ] `git push` finished for every chunk; the repository on GitHub shows the same file count as the local index.
- [ ] `CAM-Source` still builds and its tests still pass (nothing in it changed except two documentation paths).

## 7. Results

*(filled in at the end of the work)*
