# Reference[KT]: the knowledge base

*KT = knowledge transfer.* Everything needed to understand CAM and its client's world, from the basics of an RFQ to the formulas inside Centum's Excel files, is here. It is **reference material**: read it, cite it, but build in [`../CAM-Source`](../CAM-Source).

## Folders

| Folder | What it holds | Read it when |
|---|---|---|
| [`DOMAIN KNOWLEDGE/basic`](DOMAIN%20KNOWLEDGE/basic) | **Teaching Series, kid to specialist** (7 notes). What an RFQ is (the kid version), reading the BOM, one RFQ start to finish, the money math, the 12 formula families decoded, how mistakes get caught | you are new to the domain: read it first, in order (Teach 0 is the map) |
| [`DOMAIN KNOWLEDGE/adv`](DOMAIN%20KNOWLEDGE/adv) | **Domain Knowledge, RFQ and CAM** (5 notes). The source-findings log, the enquiry-to-quote process at Centum, Centum and CAM end to end, every Excel input and output mapped, what the formulas actually compute | you know the basics and need the working detail |
| [`Extras`](Extras) | Four encyclopedias (the complete column dictionary; every formula kind decoded; every abbreviation and full form; the rules and the web around the files) and the **Reverse Engineering** of CAM 3.3's outputs (below) | you need to look something up |
| [`Full Details`](Full%20Details) | The whole history, CAM 1.0 to 4.1: the API master document, the complete 3.4 documentation, the version-separated analysis, the architecture companion, the synthesis, the tech-stack comparison, and the **MAP** of how it all connects | you need the why, or the history of a decision |
| [`Source Code`](Source%20Code) | The related repositories: the CAM 3.3 reference snapshot and the BAM front end | you need to read how 3.3 or BAM actually does something |

## Reverse Engineering (inside `Extras`)

| Part | What it is |
|---|---|
| `(1) CAM formula extraction` | Cell-level formulas of the 3.3 outputs, in eight zip archives (`cell_level_formulas_part1` to `part8`; the archives differ from each other) |
| `(2) CAM Internal folder and RE docs - copies, originals untouched` | Copies of the Centum internal folder material: six observation screenshots and the synthetic Scrub BOM and QuoteWin test workbooks (`Synthetic Scrub and QW Files - copies`). The originals were not touched |
| `(3) Internal sheets - formula extraction` | The report on the internal sheets |
| `(4) Analytics` | The analytics report, the generation-logic overview, and one **Generation Logic** note for each of the 16 report tabs (A-Class parts, batch-wise cash-flow, BOM matrix, CBOM VL, Ex Inv VL, lead time, missing notes, price control, revision history, summary and the rest) |
| `RE 1` and `RE 2` | How every output is produced, reverse-engineered from the project folders; and recommendations for making the pipeline robust and reliable |
| `README_and_insights_log.md` | How this material was produced and what was learnt |

## Where to start, by question

| I want to know | Open |
|---|---|
| what an RFQ and a BOM are | `DOMAIN KNOWLEDGE/basic`, Teach 0 to 3 |
| what a column or an abbreviation means | `Extras`, Encyclopedia 1 or 3 |
| how a report tab is computed | `Extras/Reverse Engineering/(4) Analytics/Generation Logic` |
| how the JSON manifests relate to the code, and what the 3.4 steps are | `Full Details/CAM 3.3 to 3.4 - how the JSON manifests meet the code.md` |
| how everything connects and where it lives | `Full Details/MAP - how the material connects and where it lives.md` |
| the complete picture of 3.4 with diagrams and app screenshots | `Full Details/CAM 3.4 - Complete Documentation (WORKING DRAFT).md` and the extracted `CAM_3.4_documentation_package_2026-11-05` folder (PDF, diagrams, app evidence, manifest copies) |
| which repository is which | `Source Code/README - which repo is the main code.md` |

## Reading conventions

The documents label every claim: **source** (read in code), **doc** (a team document says it), **reported** (said in a meeting or chat), **target** (a 4.x plan), **open** (unknown). "Listing" means inventoried, not read in full. Snapshots are copies of a moment in time.
