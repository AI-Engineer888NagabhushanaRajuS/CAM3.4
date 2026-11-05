# CAM 3.4 User Guide

This guide is what the RFQ assistant reads when you ask how to use the tool, and it cites these sections. It describes the screens as they are built in `apps/web` (checked against the source on 2026-11-05). It contains no RFQ data: figures about a specific RFQ come only from that RFQ's results.

## 1. What CAM 3.4 does

CAM 3.4 (for Centum) turns a customer's bill of materials (BOM) into a costed quote. You create an RFQ, upload its BOM and volume files, and the pipeline standardizes the BOM, fetches online prices, consolidates price sources, lets you review the decisions that need a person, and exports the costed BOM (CBOM) and quote workbooks. The assistant in the middle of the screen answers questions about the results.

## 2. Sign in

Open the CAM page in the browser and sign in with your account. On a development machine the login page also offers a **Sign in as Tester** button. The account menu at the top right (the avatar) lets you sign out, and the **Settings** icon next to it opens Settings.

## 3. The screen: three panes

- Left pane, **RFQ Pipeline**: a search box ("Search by RFQ ID, customer, or project") and the list of pipeline stages with their status (Completed, Running, Waiting, Failed, Not in this profile).
- Middle pane, **RFQ Assistant**: the chat. It stays on screen after every answer.
- Right pane, **See your work, flowing here**: live progress of the selected RFQ, review screens, and downloads.

The button at the top that collapses the panels gives the right pane more room; use it again to restore them. The panes can be resized by dragging the dividers between them.

## 4. Create an RFQ

1. In the left pane open the first stage, **Upload file** (Intake & Normalization).
2. Choose **Create RFQ**. A form opens in the right pane.
3. Pick a **Customer** from the searchable list. If the list is empty, add the customer first in Settings, under the Project Tracking tab.
4. Pick a **Project**. The list shows only the projects of the chosen customer.
5. Check the **RFQ ID**. It is suggested automatically; you can edit it, but it must be unique. The form tells you when the ID already exists.
6. Press **Create RFQ**. The RFQ now exists and appears in the left pane search.

## 5. Upload the BOM and volume files

1. After creating the RFQ, choose **Ingest BOM and Volume file** under the first stage (or continue from the Create RFQ step).
2. In the **Upload RFQ Files** dialog, drop or browse for the **BOM File** (`.xlsx`, `.xls` or `.csv`). It is required.
3. Add the **Volume File** (`.xlsx`, `.xls` or `.csv`). It is required: the pipeline cannot import the BOM without it.
4. Optionally add the **Gerber ZIP** (`.zip`). If you leave it out, feature extraction skips itself.
5. Press **Upload & Proceed**. The dialog closes and the progress appears at once. Files are scanned for viruses as the first automatic step (shown as "Scan for virus").

## 6. Follow the progress

The right pane lists every step that has run or is running for the selected RFQ, in order, with a tick when it is finished, a warning when it failed, and a spinner while it runs. The left pane shows the stage statuses. The stages are: Upload file, Extract features, Get online pricing, ERP & Quoting tools, Analyze feasibility & Risks (not available yet), Consolidate Pricing Sources, Finalize price, Quote Readiness, Reports & Analytics.

If a step fails, the right pane shows which one. Fix the cause and upload again or resume the RFQ (see section 9).

## 7. Reviews that need a person

When the pipeline needs a decision (for example choosing between alternate parts or confirming a price source), it stops and the right pane shows the review screen for that RFQ. Make your choices there and submit them with the button on that screen (Approve or Resume); the same pipeline run then continues. The assistant tells you when an RFQ is waiting for review if you ask about its status.

If the intake needs the ERP and QuoteWin or Costing Sheet files, the left pane offers the upload for them only when the run is actually waiting for it.

## 8. Download the results

When the pipeline reaches **Quote Readiness**, the right pane says the reports are ready and shows one row per file that really exists (the CBOM workbook, the Consolidated BOM, the Final Quote). Press the download button on a row to get the `.xlsx` file. If a row is missing, that file has not been exported for this RFQ. The assistant can only answer questions about numbers once the workbook exists.

## 9. Find and reopen an RFQ

Type an RFQ ID, a customer or a project in the left search box. Matching RFQs are listed under it; click one, or type the full ID and press Enter, to reopen it. The left pane and the right pane jump to the stage that RFQ has reached.

## 10. Ask the assistant

The assistant is a normal chat first: you can say hello or ask how to use the tool and it answers from this guide.

When you ask about an RFQ's results and no RFQ is chosen, the assistant lists your RFQs in a picker (customer, project, steps done, review pending, export available). Tick one or more RFQs, or press **All context**, and then ask anything about that choice. Selecting an RFQ in the left pane also sets the assistant to that RFQ. The chosen RFQs are shown as chips at the top of the chat and you can change them at any time.

What you can ask once an RFQ is chosen: costs and prices, suppliers, lead times, A-class parts, MOQ, price control, what is still missing, the go / no-go status. Every answer shows the cells it came from (a sheet name and a cell range, such as `Sheet!A1:C1`). A figure that is not in the cited cells is never shown. If the results do not contain the answer, or a part number is not in the results, the assistant says so instead of guessing.

With several RFQs or All context, the assistant answers as a table with one line per RFQ, up to 25 RFQs at a time; above that it asks you to narrow the choice. If a part number appears in more than one RFQ with different values, or an RFQ ID is not found, it tells you, shows both sides with their cells, and asks you to choose.

The assistant uses the language model chosen in Settings. If the model cannot be reached it shows the matching rows from the results exactly as they are.

## 11. Attach files in the chat

1. Pick an RFQ (the **+** button in the chat box is disabled until one is chosen).
2. Press **+** (Add files), or drop files on the chat box.
3. In the dialog tick the files to send and untick the rest. Accepted types: `.xlsx`, `.xls`, `.csv`, `.tsv`, `.txt`, `.md`, `.json`, `.docx`, `.pdf`. Limits: 10 files per scan, 25 MB per file, 60 MB in total. Duplicates and unsupported files are turned away with a reason.
4. Press **Scan N files**. Each file is checked by two security engines, **BuLL*Sav** and **Repel**. A file reaches the assistant only when both say it is clean; anything else is quarantined and you see the verdict per file; press **Done** to close the dialog.
5. Released files appear as chips above the chat box. You can ask about their content, and remove a chip to withdraw the file.

## 12. Create an RFQ from the chat

Tell the assistant you want to create an RFQ, and attach the BOM (and volume file) as in section 11. The assistant checks what it needs (customer, project, the files), asks for what is missing, and then shows a confirmation card with the exact parameters. Nothing is created until you press **Confirm**. **Cancel** creates nothing. A file that was quarantined is never used. After Confirm the assistant reports each step and the new RFQ ID; the RFQ then appears in the left pane.

## 13. Settings

Open Settings with the gear icon at the top right. The tabs include: Providers (model API keys, for example the OpenRouter key the assistant uses; without a key the assistant uses the local model), Skills (which pipeline skills are on), Project Tracking (customers and projects), Currencies and Users (administrators only), General and About. A key saved in Settings is used by the assistant for the next question; no restart is needed.

## 14. If something looks wrong

- "I can't reach the results service": the Python bridge is down or still starting; try again in a moment. Nothing was guessed.
- A part number is "not in the results": check the spelling, or ask what the results contain. The assistant never answers from memory.
- Many cells have no stored value: the workbook was exported before values were stored. Export the RFQ again.
- The assistant is slow: the local model needs a while on a small graphics card; add an OpenRouter key in Settings for faster answers, or press the stop button and ask again.
- An upload is rejected: check the file type and the 25 MB limit, and that both the BOM and the volume file are chosen.

## 15. What the assistant can do for you

Besides answering questions, the assistant can work the app for you. It never changes the screen or writes anything by itself: it shows a button or a confirmation card and you press it. Say it in plain words, for example "open RFQ-00007".

- **Open an RFQ**: "open RFQ-00007", "go to RFQ-00007". The assistant shows an **Open RFQ-00007** button (named after the RFQ); pressing it opens that RFQ in the left and right panes. An RFQ ID that does not exist is refused and the real ones are offered.
- **Check progress**: "what stage is RFQ-00007 at?", "is it stuck?", "is it waiting for review?". The assistant answers from the database: stage n of 9 with its name, whether a review is pending, and the last steps with a tag ([DONE], [RUNNING]). With one RFQ chosen you can leave the ID out ("what stage is it at?"). This is the pipeline, not the workbook: "what is the go / no-go status?" is a question about the results and is answered from the workbook with cited cells.
- **Resume or start the pipeline**: "resume the pipeline for RFQ-00007", "continue RFQ-00007". The assistant shows a confirmation card; nothing runs until you press **Confirm**, and **Cancel** starts nothing. It refuses, in plain words and without starting anything, when the RFQ does not exist, has not been uploaded yet, has already finished, or is waiting for a person to review it (resolve that on the review screen in the right pane).
- **Download the reports**: "export the reports for RFQ-00007", "download the workbook". When the RFQ has exported reports the assistant shows a **Download reports for RFQ-00007** button; otherwise it says that none exist yet.
- **Upload files**: "upload a file", "attach the BOM". The assistant shows a **Choose files** button (accepted: .xlsx, .xls, .csv, .pdf, .docx, .txt). Both security engines scan every file first, and only clean files reach the chat. To create an RFQ from the files, say so (section 12).
- **Create an RFQ**: "create an RFQ for customer X, project Y" with the files attached (section 12), again behind a confirmation card.
- **Open Settings**: "change the model", "OpenRouter API key", "settings". The assistant shows an **Open Settings** button that opens Settings, Providers. The **Local / OpenRouter / Auto** switch for the language model is in the assistant header, not in Settings.
- **Answer how-to questions**: "what can you do", "how do I upload the BOM file", answered from this guide.
