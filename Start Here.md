# Start Here

*The reading order for anyone, human or agent, who opens this folder for the first time. The project overview is in [`README.md`](README.md); this page says what to read, in which order, and why.*

## The situation in five lines

- **Digibull** builds an RFQ-automation system called **CAM** for its client **Centum**.
- **CAM 3.3** already runs at Centum. **CAM 4.0** has been proposed, but it would replace about 80 % of the technology stack, so it is deliberately left for later.
- The job now is **CAM 3.4**: understand exactly how 3.3 works, then build the agreed delta on top of it.
- The whole of Centum's history, from CAM 1.0 to 4.1 (APIs, features, decisions), is mapped in `Reference[KT]/Full Details`.
- An earlier agent started this work, built roughly half of it, and then lost the thread because its context was compacted too often. That is why the specs, the handoffs and the evidence in this folder are written the way they are.

## Reading order

1. **Learn the domain.** [`Reference[KT]/DOMAIN KNOWLEDGE`](Reference%5BKT%5D/DOMAIN%20KNOWLEDGE): `basic` is the teaching series (what an RFQ is, how to read a BOM, the money math, the 12 formula families); `adv` is the working knowledge (the enquiry-to-quote process at Centum, every Excel input and output, what the formulas compute).
2. **Look up anything specific.** [`Reference[KT]/Extras`](Reference%5BKT%5D/Extras): four encyclopedias (column dictionary, formula kinds, abbreviations, the rules around the files) and the reverse-engineering of CAM 3.3's outputs.
3. **See the whole history.** [`Reference[KT]/Full Details`](Reference%5BKT%5D/Full%20Details), beginning with the MAP document, which says how the material connects and where it lives.
4. **Read the architecture.** [`Eng_Diagram [ Must follow ]`](Eng_Diagram%20%5B%20Must%20follow%20%5D). The diagrams are the source of truth. Their text transcription, what replaced what, the install notes and the verified defects are in [`SPECS/handoff/CAM-3.4-HANDOFF.md`](SPECS/handoff/CAM-3.4-HANDOFF.md).
5. **Read the work orders.** [`SPECS`](SPECS): the specifications, in numbered order, then the newest handoff, [`SPECS/handoff/HANDOFF-2026-11-05.md`](SPECS/handoff/HANDOFF-2026-11-05.md), section 9 first.
6. **Build.** [`CAM-Source`](CAM-Source) is where everything from the other folders is turned into product.

## Where the related source code lives

[`Reference[KT]/Source Code`](Reference%5BKT%5D/Source%20Code) holds the repositories that are directly or indirectly connected to CAM. Its [README](Reference%5BKT%5D/Source%20Code/README%20-%20which%20repo%20is%20the%20main%20code.md) says which one is the main code and which to ignore. In short: the CAM 3.3 source is the reference and base; the BAM UI is a source of ideas; the accomplish app is not to be installed again.

## Tools the coding agent should use

- **Memory** (MCP `memory`): load the stored context first (`search_nodes("CAM 3.4")`), and write decisions back.
- **context7**: pull the live documentation of any library before touching its API.
- **serena**: find code by symbol instead of reading whole trees.
- **nagabhushana-personas** (https://www.mr-nagabhushanaraju-s.engineer/api/mcp): thinking panels for design review, bug hunting and code review; more features are being added to it, and anything it already offers should be used.
- The standing agent setup, with the full list of plugins and rules, is in [`.claude/CLAUDE.md`](.claude/CLAUDE.md). Check that it is installed before starting.

## The history of this note

This page is the polished form of two rough notes written at the start of the project (`Start Here.txt` and `001.txt`). Their verbatim originals are kept in [`SPECS/handoff/original-notes`](SPECS/handoff/original-notes).
