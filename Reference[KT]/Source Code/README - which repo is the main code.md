# Source Code: which repository is the main code?

This folder holds the repositories that are directly or indirectly connected to CAM. An earlier agent lost track of which one carries the main code, so this page records what is known, what the owner decided, and what to do with each folder.

*Labels: **REPORTED** = said by the owner or an earlier agent in chat; **DOC** = written in a project document; **OPEN** = not settled.*

## What is in this folder

| Folder or file | What it is | Use it for |
|---|---|---|
| `BuLLMQuote-SRIM-containerization-delivery/BuLLMQuote-SRIM/` | The Centum copy of the RFQ system: backend (`fastmcp-router`, `mcp-tools`), frontend (`accomplish-ui`) and the containerisation work (`docker`, `k8s`, `infra`, `docs`). This is the **CAM 3.3 reference and base** that CAM 3.4 is built from | Reading how 3.3 works: the 16 reports, the intake tools, the routing, the Dify flow |
| `BAM-full-ui--main/` | The BAM front end (the build-time "manifest to tool" system) | Ideas and patterns only; BAM is the 4.0 track, not part of 3.4 |
| `image.png`, `image (1).png`, `image (2).png` | Three screenshots of an earlier agent explaining which repository is which (transcribed below) | Context for the table in the next section |

The folder is **read-only reference**. Build in `CAM-Source`, never here. One caution recorded in the project rules: the BuLLMQuote-SRIM copy was changed by an earlier agent (it carried SPEC-001 to SPEC-003 work, a `manifests/` folder and an untracked `accomplish-ui`), so for "what did CAM 3.3 look like" use the `v3.3-baseline` tag inside `CAM-Source` rather than this copy.

## The owner's guidance (REPORTED)

- Install the relevant repositories and run them if that helps to see the real behaviour.
- **Do not install the `accomplish` repository**: it is not needed. Its technology and items have already been replaced, so only what is still needed should be kept.
- The repository the owner believes to be the main code is **https://github.com/solutionsDigibull/CAM**. Look closer there.
- Ignore empty repositories, and new repositories that have no substance.

## What the earlier agent's screenshots say (REPORTED)

The three images record one conversation. Transcribed:

| | CAM | Centum / BuLLMQuote-SRIM |
|---|---|---|
| Local path (then) | `Downloads\accomplish-ui\accomplish-ui` (frontend) and `Documents\SRIM\Tools\...\centum intake` (backend) | `Documents\BuLLMQuote-SRIM` (backend, frontend and all the containerisation work) |
| GitHub remote | `solutionsDigibull/CAM.git` (backend and frontend pushed there) | `solutionsDigibull/BuLLMQuote_SRIM.git` |
| Status then | Pushed, up to date | One commit pushed; the rest was local only |

- The CAM front end's own, original repository is `solutionsDigibull/SRIM-UI.git`. `CAM.git` was created later as a consolidated, one-time backup of CAM's backend and that front end (scoped to `apps/web` and `apps/daemon`).
- **CAM** is the earlier, original, parent deployment: the one a real client uses live. **Centum / BuLLMQuote-SRIM** was forked from it (the Centum databases `logic_db_2` and `file_metadata_db_2` were split off from CAM's own) and holds everything for Centum only, with no CAM code.
- The relationship is **sibling, not container**: `CAM (live) -> forked -> BuLLMQuote-SRIM (in development)`. The front end of CAM runs on port 5180, the Centum one on 5281.

## Open point

**OPEN:** the owner's view (`solutionsDigibull/CAM` is the main code) and the earlier agent's account (BuLLMQuote-SRIM is the comprehensive Centum project, CAM the live parent) are not the same statement. For CAM 3.4 the working rule stands: the BuLLMQuote-SRIM copy in this folder is the reference and base, `CAM-Source` is where the work happens, and any new fact about the repositories is written here.

*This page replaces the rough note `SSource Code REPO Confussion.txt`; its verbatim text is kept in `SPECS/handoff/original-notes/`.*
