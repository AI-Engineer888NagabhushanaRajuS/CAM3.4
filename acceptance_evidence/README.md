# acceptance_evidence: proof that it works

Real browser runs of CAM 3.4, with the recordings, screenshots, logs and scripts that produced them. "Done" in this project means evidence from here or a passing test run, never a statement.

| Folder | What it holds |
|---|---|
| `proof_take1` to `proof_take21` | **End-to-end acceptance runs** driven by `acceptance_runner.py` (a human-like browser flow with continuous video). Each take has `video/` (the recording, `.webm`), `screenshots/` (numbered steps, for example `01_login_page.png`), `logs/` (`browser_console.log`, `browser_errors.log`, `network_traffic.log`) and `downloads/` (the Excel reports the run produced, for example `CBOM_Report_RFQ_CENTUM_PROOF_23_...xlsx`) |
| `runs/` | The console log of each take (`take10_run.log` and on) |
| `probes/` | Small one-off scripts and their output that checked a single behaviour (clicks, downloads, the chat and stage screenshots of one RFQ) |
| `spec019/` | The live proofs of the later work, SPEC-019 to SPEC-023: numbered screenshots and the network captures of the assistant, the manifest editor, run history, the intake dashboard, tracking by user, the files-in-chat and pre-flight proofs. The `*.cjs` scripts are the Playwright scripts that drove them (for example `files_live.cjs`, `fix_confirm_live.cjs`, `pane_live.cjs`); `fixtures/` holds the bad BOM used to prove the fix dialog; `matrix/`, `intake/`, `changes/`, `tracking/`, `files/`, `pane/` hold the screenshots of each |
| `test_inputs/` | The four input files used for the proofs: a BOM, a Scrub BOM, a QuoteWin file and a Volume file |
| `acceptance_runner.py` | The runner behind the `proof_take*` runs |

## Running a proof again

The Playwright scripts use the system Chrome and expect the stack to be up (web app on port 5181, daemon on 9334); see [`../SPECS/handoff/CAM-3.4-RUNNING-STACK.md`](../SPECS/handoff/CAM-3.4-RUNNING-STACK.md). Every script opens the real app, signs in with the test login and prints what it observed; none of them calls an API in place of a click unless it says so.

## What these runs do and do not show

- Every claim of a SPEC marked "proven live" points at files in this folder, and the matching handoff section (`SPECS/handoff/HANDOFF-2026-11-05.md`, section 9) names which.
- No run has reached the report-export step with a human review completed, so the automatic download of the finished report is not proven here (stated in SPEC-023).
- Each run creates test RFQs (`RFQ-CENTUM-PROOF-nn`, and a few `RFQ-0000nn`); they are left in the database on purpose.
- The proof videos are large (about 600 MB in total); the screenshots and logs next to them carry the same information in readable form.
