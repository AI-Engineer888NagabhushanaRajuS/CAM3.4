# Eng_Diagram: the architecture that must be followed

These are the diagrams the owner designed to explain every repository involved and exactly what CAM 3.4 has to become. **They are the source of truth. If a document and a diagram disagree, the diagram wins**, and the conflict is logged in the SPEC that touches it.

## Files

| File | What it is |
|---|---|
| `CAM 3.4 architecture with manifest pipeline (interactive).html` | The interactive version of the final diagram (diagram 8): the architecture with the manifest pipeline. Open it in a browser |
| `WhatsApp Image 2026-10-29 at 12.30.48 PM.jpeg`, `12.30.52`, `12.30.56`, `12.31.01` | Diagrams 1 to 4 in the order they were sent: system design; architecture by layer and generation; the workflow-manifest-to-tool flow (BAM side, **out of scope**); internal calling for one RFQ (the CAM 3.3 call graph) |
| `WhatsApp Image 2026-10-29 at 12.37.52 PM.jpeg`, `12.37.57`, `12.38.01` | Diagrams 5 to 7: CAM 3.3 against 3.4 side by side (ten layers, the delta); the call flow of 3.3 against 3.4 for the same RFQ; the migration path (six steps, each with an exit check and an open question) |
| `WhatsApp Image 2026-10-29 at 12.47.22 PM.jpeg` | Diagram 8: the architecture with the manifest pipeline |

The file names are the ones the images arrived with; they are kept unchanged so that older notes still find them.

## Reading them without seeing the images

A text transcription of all eight diagrams, with the legend of the labels on every box (SOURCE = exists in code, PROPOSAL / MISSING / OPEN = not built or undecided), is in [`../SPECS/handoff/CAM-3.4-HANDOFF.md`](../SPECS/handoff/CAM-3.4-HANDOFF.md), section 3. Section 4 of the same file says what is replaced with what between 3.3 and 3.4.

## The decisions the diagrams lock

- No CAM 4.0 in this work. No code generation. No further change of architecture.
- Orchestration moves from Dify to Temporal, with human-in-the-loop by signal.
- One manifest per **real** tool, derived from code. The ten manifests drawn in the BAM-side diagram are not files that must be found; the runtime set lives in `CAM-Source/manifests`.
