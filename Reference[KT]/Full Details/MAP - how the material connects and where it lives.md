# MAP - how the material connects, with where each piece lives (28 Oct 2026)
Companion to 00 - START HERE. Tags: source = read in code, doc = a team document says it, reported = said in a meeting or chat, target = 4.x plan, open = unknown. Listing means inventoried, not read in full. Snapshots are copies of that moment.


## STAGE A - decisions and history (why)

Home folders 1 to 6: tl;dv meetings (https://drive.google.com/drive/folders/1QBuQaYxwWFOzBfyMmpd4YLkOd1IsqSz3), ClickUp (https://drive.google.com/drive/folders/1z9YLhoEpet8D8x0rg31cdFPc4gI0fNUt), Gemini and ChatGPT histories for solutions and getleads (folders 3 to 6). Gap: the getleads ChatGPT export is waiting on a phone sign-in approval; a second export request has not arrived; the solutions-account videos and Gemini exports under 25MB are now copied; 3 videos over 25MB are pending (see ledger).  
User note: NEXT STEPS / Read this (doc 1tce5hZvZd8CDgw-BSA2Q3FgjofViUEyiZcmF7IPUr6Q).


## STAGE B - what was built (BAM and CAM code)

9 - GitHub repos (source archive): https://drive.google.com/drive/folders/14BbHdtvucQ-77vWMtE5gTex8uT33WapI. Zips for BAM, BAM Mock UI, dbhub, ISATVON-prompting, CAM, BuLLMQuote, BuLLMQuote_SRIM, BuLLQR, BuLLQR-In, SRIM, DGB-BuLLm-Quote, db_implementation, Quote-deployment. Entry points: MANIFEST.md (https://drive.google.com/file/d/1Pu-oUGvNcsvmi-KbjgC1x4he6NHSciQW/view), FINDINGS-20261028.md (https://drive.google.com/file/d/1kr1qdO3rOWDm6NCP5Rv9Mpm96JSfkN2z/view), ISATVON-path-explained (https://drive.google.com/file/d/1Hs-3NXI5V34xDdip6kWBWH0mxf40d5ax/view). Marked incomplete: CAM harvest (frontend pending) and BuLLMQuote_SRIM harvest (UI subtrees pending). Newest BAM commit read: 9e6749d (source).


## STAGE C - manifests, skills, tools (what is defined)

Original folder JSON Manifest (Harish, shared, untouched): https://drive.google.com/drive/folders/1k9ZtcjIHKGCET4wCGAOCcW-d9f4XteGm . Private snapshot: inside folder 10 (see below). Contents and status: agent_manifest and skill_01..10 are v1.5.0-draft of 27 Oct (placeholder hash); cam_isatvon_manifest.json is v0.1.0 DRAFT of 16 Oct. Skills master doc (draft): https://docs.google.com/document/d/1dtHGCBsSeqdvkBffwIEnkR48XT3f-yQYmYLwENG9mzY/edit?tab=t.0#heading=h.obfmuv1gf8vp  
Source finding: build_manifest is real and hardcodes the Dify/Jungle/SRIM UI platform; codegen, gates, tests and certify are stubs.


## STAGE D - runtime (what runs)

Two generations stay separate: Dify/Jungle (Oct 16 report manifest, SRIM runtime chain in drawing) and Temporal/Bifrost (Oct 27 agent manifest, reported replacement). Open: no importer from manifest to runtime found; no verified manifest importer or registry writer found (a system_skills_registry exists in the inspected runtime; what populates it is unverified). Evidence: BAM and SRIM zips in folder 9; SRIM docs snapshotted in folders 7 and 11 (SRIM architecture, DMR, PostgreSQL 17 multitenant, local deployment).  
Drawing: CAM - connected architecture (live in nagabhushanasraju@gmail.com): https://docs.google.com/drawings/d/1WNnWL7hdp-3jQCjcgmP8R0x2CU5fyFw0gA_iLsJKSx8/edit ; high-res snapshots are in INSTINCT BRAIN (https://drive.google.com/drive/folders/1EXsYMNlqikC6wTUAQ4YCwtsIreucHlD3).


## STAGE E - CAM4 and API upgrade (target)

API Master v0.3 and API Governance v0.2 (BuLLM docs, drafts) in folder 7 and 11 snapshots. Target: 7 REST operations plus one webhook, three reportTypes that do not map to the 16 CBOM tabs. Analysis and companion: 8 - Analysis (https://drive.google.com/drive/folders/1_9HoJMXNlMNviZr3Me18exg4CNHRDZ8d), companion PDF (https://drive.google.com/file/d/1-TXDjlMQXZU5Y67ugpfL6dTmpQK-ZUrG/view), synthesis, Version map, Project facts, Decisions and open questions in INSTINCT BRAIN.


## COPIES OF SHARED MATERIAL (private, owner-only, originals untouched)

Folder 10: https://drive.google.com/drive/folders/1I9jcO30UXKVGLGqIi7L9nOELOa4s_57C - JSON Manifest copy (13 of 13), CAM copy (617 of 621 non-folder items; 4 shortcuts unresolved), and these ledgers/inventories: CAM and JSON Manifest copy ledger (https://drive.google.com/file/d/1a6pIBayLA17KoqKLqGJuIUhpf0pcD5CA/view), home inventory (https://drive.google.com/file/d/1FRUZNnSYFhG_xnpnwIuD-RVzmW6Xb8OB/view), solutions-account inventory (https://drive.google.com/file/d/1fqnEQuypFUv9y1zEUWx3c2e3nwvO_Z5m/view), solutions-account ledger (https://drive.google.com/file/d/1rnGxH7-q85xmNan-QlUzFX25V-KIpkxf/view).  
Folder 11: https://drive.google.com/drive/folders/168aYfgD0iPl8m7yyiY1GQ61ANcgr6ENX - 358 solutions-account docs (download and upload snapshots, native files exported to docx/xlsx/pptx).


## CONTRADICTIONS AND OPEN GAPS

\- OKF means three things: a JSON bundle (implemented in the inspected BAM source), a Markdown directory (documented proposal) and chat variants; see https://docs.google.com/document/d/1mR60Zv9v4aD6uj_Qz-xhs41iFJTbVB-gZOAassdoZW4/edit  
\- Runtime generations conflict (Dify/Jungle vs Temporal/Bifrost); folder or date does not show which is approved.  
\- Manifest to runtime handover: no verified path.  
\- API reportTypes vs 16 CBOM tabs: no mapping.  
\- Added 28 Oct 18:15-18:19: the RFQ Automation subfolders (ISATVON, API, Reporting, Tech Stack, Infrastructure, UI, Deployment, FDE, Intelligence, Manufacturing Workflow, Quality, REPEL) were inventoried and copied by folder lineage (134 items). WordPress Build and BuLLMaps Marketing docs were read and excluded with reasons; their non-doc files are not content-checked. Not copied: 672 MB zip BuLLMQuote-SRIM (3).zip (solutions account, link only), 5 files over 25MB with no supported byte path (3 videos, 2 zips), 4 CAM shortcuts, BuLLM UI accomplish-ui zip (846 MB, link only) and 6 structure items (shortcuts/forms).  
\- Relevance of the 358 snapshots comes from name and text-hit rules plus first-700-character reads, not full review. 17 items were excluded after reading (marketing, SEO, website, unrelated SOW), each with a reason in the ledger.  
\- Inventory of home folder 9 was taken at 13:45 on 28 Oct and re-checked at 18:12: 24 items, none new, none shared. CAM shortcut targets: not resolved (Drive tools do not expose them; the browser profile is signed in only as a personal account with no access to the CAM folder; digibull sign-in needs MFA).


## UPDATE 29 Oct 2026, 11:55 IST (digibull sign-in worked; read-only checks)

\- 4 CAM shortcut targets resolved with the digibull account: (1) "CAM RFQ automation in BAM: skills, sub-skills and steps (draft)" Google Doc, owner srinath.r, copied as private DOCX id 1qleU6f9A8X5MMN1CMbJSKt_OF9gf_kwH in folder 10; (2) "CAM Testing Tracker" Google Sheet, owner harish.t, copied as private XLSX id 1nLw6qmU3wMh6EaPgCWPbn9vwAYAbh4Jo in folder 10; (3) "Synthetic Scrub & QW Files" folder 1Yl1PICqr5MMPg3MnLKBFGyrbxgNWnvln, owner sriniketh.s, 19 synthetic test sheets, NOT copied (pointer only); (4) "API Proposal for Centum - Draft" id 1oXenrXKXvUkFk6TrkNfYmN1UllnLYhEK: "Can't access item" even when signed in as digibull, no access.  
\- Large-file transfer test (CAM 2.0 Demo.mp4, 64,058,834 bytes): the Drive download action still fails over 25 MB (26214400 byte limit) with the digibull account. The Drive copy action has no destination option, and the digibull account is a writer on the source folder, so a copy would land inside the collaborator's source folder. Not done. Result: no verified private route. The 5 over-25MB files stay as user-transfer items with their exact sizes and source URLs.  
\- Full 3.3 to 3.4 write-up added in INSTINCT BRAIN: https://docs.google.com/document/d/1B2ekDQgpPm17Ff0gtFdeZUmev51rn6QvOmHU3RYbfdM/edit  
