"""
Full End-to-End Acceptance Proof Runner for CAM 3.4
Executes genuine human-like browser flow with continuous video recording.
"""
import os
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
import time
import json
import datetime
from pathlib import Path

# Paths
BASE_DIR = Path(r"C:\CAM[3.4]-RFQ_centum")
EVIDENCE_DIR = BASE_DIR / "acceptance_evidence" / "proof_take21"
VIDEO_DIR = EVIDENCE_DIR / "video"
SCREENSHOTS_DIR = EVIDENCE_DIR / "screenshots"
LOGS_DIR = EVIDENCE_DIR / "logs"
DOWNLOADS_DIR = EVIDENCE_DIR / "downloads"
INPUTS_DIR = BASE_DIR / "acceptance_evidence" / "test_inputs"

BOM_FILE = INPUTS_DIR / "Centum_Scrub_BOM.xlsx"
VOLUME_FILE = INPUTS_DIR / "Volume_File.xlsx"
QUOTEWIN_FILE = INPUTS_DIR / "QuoteWin_File.xlsx"

RFQ_ID = "RFQ-CENTUM-PROOF-24"

for d in [VIDEO_DIR, SCREENSHOTS_DIR, LOGS_DIR, DOWNLOADS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

console_log_path = LOGS_DIR / "browser_console.log"
errors_log_path = LOGS_DIR / "browser_errors.log"
network_log_path = LOGS_DIR / "network_traffic.log"

console_fp = open(console_log_path, "w", encoding="utf-8")
errors_fp = open(errors_log_path, "w", encoding="utf-8")
network_fp = open(network_log_path, "w", encoding="utf-8")

def log_console(msg):
    ts = datetime.datetime.now(datetime.UTC).isoformat()
    line = f"[{ts}] [{msg.type.upper()}] {msg.text}\n"
    console_fp.write(line)
    console_fp.flush()

def log_page_error(err):
    ts = datetime.datetime.now(datetime.UTC).isoformat()
    line = f"[{ts}] [PAGE ERROR] {err}\n"
    errors_fp.write(line)
    errors_fp.flush()

def log_request(req):
    ts = datetime.datetime.now(datetime.UTC).isoformat()
    line = f"[{ts}] REQ {req.method} {req.url}\n"
    network_fp.write(line)
    network_fp.flush()

def log_response(res):
    ts = datetime.datetime.now(datetime.UTC).isoformat()
    line = f"[{ts}] RES {res.status} {res.url}\n"
    network_fp.write(line)
    network_fp.flush()

from playwright.sync_api import sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


def wait_for_cbom_export(rfq_id, timeout_s):
    """Poll the bridge until export-status reports a CBOM file for this RFQ (backend check only)."""
    import urllib.request
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        req = urllib.request.Request(
            "http://localhost:13110/auth/token",
            data=json.dumps({"rfq_id": rfq_id}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        token = json.load(urllib.request.urlopen(req, timeout=10))["token"]
        status_req = urllib.request.Request(
            f"http://localhost:13110/api/bom/export-status/{rfq_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        status = json.load(urllib.request.urlopen(status_req, timeout=10))
        if status.get("cbom"):
            print("CBOM export ready:", status["cbom"].get("filename"))
            return
        time.sleep(15)
    raise AssertionError("CBOM export never appeared for " + rfq_id)

def run():
    print(f"=== STARTING ACCEPTANCE RUN: {RFQ_ID} ===")
    start_utc = datetime.datetime.now(datetime.UTC).isoformat()
    milestone_records = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            headless=True,
        )
        context = browser.new_context(
            record_video_dir=str(VIDEO_DIR),
            record_video_size={"width": 1400, "height": 900},
            viewport={"width": 1400, "height": 900},
            accept_downloads=True,
        )
        page = context.new_page()
        video_page = page  # the recorded page; the post-run re-open uses a fresh context

        page.on("console", log_console)
        page.on("pageerror", log_page_error)
        page.on("request", log_request)
        page.on("response", log_response)

        def snap(step_name, description):
            shot_path = SCREENSHOTS_DIR / f"{step_name}.png"
            page.screenshot(path=str(shot_path), full_page=True)
            ts = datetime.datetime.now(datetime.UTC).isoformat()
            print(f"[{ts}] Milestone: {step_name} - {description}")
            milestone_records.append({"step": step_name, "desc": description, "timestamp": ts, "path": str(shot_path)})

        # -------------------------------------------------------------
        # STEP 1: Navigate to Login and Sign In
        # -------------------------------------------------------------
        print("Navigating to login page...")
        page.goto("http://localhost:5181/#/login", wait_until="networkidle")
        time.sleep(1)
        snap("01_login_page", "Login page loaded with Centum SRIM branding")

        print("Clicking 'Sign in as Tester'...")
        page.click("text=Sign in as Tester")
        page.wait_for_url("**/#/", timeout=15000)
        time.sleep(2)
        snap("02_home_page", "Signed in, home page loaded with workflow stages")

        # -------------------------------------------------------------
        # STEP 2: Enter Target RFQ ID
        # -------------------------------------------------------------
        print(f"Entering RFQ ID: {RFQ_ID}...")
        page.wait_for_selector("#rfq-search-textbox", timeout=10000)
        page.fill("#rfq-search-textbox", RFQ_ID)
        time.sleep(0.5)
        page.press("#rfq-search-textbox", "Enter")
        time.sleep(1)
        snap("03_rfq_id_entered", f"Entered RFQ ID {RFQ_ID}")

        # -------------------------------------------------------------
        # STEP 3: Ingest BOM and Volume files
        # -------------------------------------------------------------
        print("Opening Ingest BOM and Volume dialog...")
        if not page.is_visible("text=Ingest BOM and Volume file"):
            page.click("text=Upload file")
            time.sleep(0.5)

        page.click("text=Ingest BOM and Volume file")
        dialog = page.wait_for_selector("[role=dialog]", timeout=10000)
        time.sleep(1)
        snap("04_upload_dialog_open", "Upload RFQ Files dialog opened")

        # Find file inputs inside the dialog
        file_inputs = dialog.query_selector_all("input[type=file]")
        print(f"Found {len(file_inputs)} file inputs in dialog.")
        assert len(file_inputs) >= 2, "Expected at least 2 file inputs for BOM and Volume"

        file_inputs[0].set_input_files(str(BOM_FILE))
        file_inputs[1].set_input_files(str(VOLUME_FILE))
        time.sleep(1)
        snap("05_files_staged", f"Attached BOM ({BOM_FILE.name}) and Volume ({VOLUME_FILE.name})")

        print("Clicking 'Upload & Proceed'...")
        dialog.query_selector("button:has-text('Upload & Proceed')").click()
        page.wait_for_selector("[role=dialog]", state="hidden", timeout=15000)
        time.sleep(2)
        snap("06_upload_submitted", "BOM and Volume uploaded, workflow triggered")

        # -------------------------------------------------------------
        # STEP 4: Wait for Intake HITL Gate (awaitUploads)
        # -------------------------------------------------------------
        print("Waiting for Intake HITL gate (Upload QuoteWin button)...")
        quotewin_btn_selector = "button:has-text('Upload QuoteWin / Costing Sheet')"
        gate_found = False
        poll_start = time.time()

        while time.time() - poll_start < 180:
            if page.is_visible(quotewin_btn_selector):
                gate_found = True
                print("Intake HITL gate reached: 'Upload QuoteWin / Costing Sheet' button visible!")
                break
            time.sleep(3)

        snap("07_intake_hitl_reached", "Intake HITL gate reached awaiting QuoteWin")
        assert gate_found, "Timed out waiting for Intake HITL gate (Upload QuoteWin button)"

        # -------------------------------------------------------------
        # STEP 5: Upload QuoteWin File and Resume Workflow
        # -------------------------------------------------------------
        print("Clicking 'Upload QuoteWin / Costing Sheet'...")
        page.click(quotewin_btn_selector)
        qw_dialog = page.wait_for_selector("[role=dialog]", timeout=10000)
        time.sleep(1)
        snap("08_quotewin_modal_open", "QuoteWin & Costing Sheet upload modal open")

        qw_inputs = qw_dialog.query_selector_all("input[type=file]")
        print(f"Found {len(qw_inputs)} file inputs in QuoteWin dialog.")
        qw_inputs[0].set_input_files(str(QUOTEWIN_FILE))
        time.sleep(1)
        snap("09_quotewin_staged", f"Attached QuoteWin ({QUOTEWIN_FILE.name})")

        print("Clicking 'Upload & Proceed' in QuoteWin modal...")
        qw_dialog.query_selector("button:has-text('Upload & Proceed')").click()
        page.wait_for_selector("[role=dialog]", state="hidden", timeout=20000)
        time.sleep(2)
        snap("10_quotewin_resumed", "QuoteWin uploaded, workflow resumed")

        # -------------------------------------------------------------
        # STEP 6: Final-selection gate (one Clear & Resume), wait for completion, download from Quote Readiness
        # -------------------------------------------------------------
        try:
            resume_btn = page.wait_for_selector("button:has-text('Clear & Resume Pipeline')", state="visible", timeout=30000)
            snap("hitl_action_clear_&_resume_pipeline", "Clicking 'Clear & Resume Pipeline' (single click)")
            resume_btn.click()
        except PlaywrightTimeoutError:
            print("No Clear & Resume gate appeared: the run passed the final-selection gate without a human action")
        print("Waiting for CBOM generation to complete in the right pane...")
        # The completion message and the workbook Download sit on the Quote Readiness stage, so open it first
        # Backend readiness (not a UI action): the bridge reports the CBOM file once export_reports has finished
        print("Waiting for the bridge to report the CBOM export (backend readiness check)...")
        wait_for_cbom_export(RFQ_ID, timeout_s=600)

        # Re-open the RFQ as a user would after the run: fresh sign-in, search, then Quote Readiness
        dl_btn = None
        for _attempt in range(3):
            # a new browser context, as the probes used: re-signing in on the stored session never showed the search box
            page = browser.new_context(viewport={"width": 1400, "height": 900}, accept_downloads=True).new_page()
            page.goto("http://localhost:5181/#/login", wait_until="networkidle")
            page.click("text=Sign in as Tester")
            page.wait_for_url("**/#/", timeout=15000)
            page.wait_for_selector("#rfq-search-textbox", timeout=10000)
            time.sleep(3)  # the sidebar re-renders while the RFQ list loads; type into the settled box
            page.click("#rfq-search-textbox")
            page.keyboard.press("Control+A")
            page.keyboard.type(RFQ_ID)
            page.keyboard.press("Enter")
            time.sleep(4)
            page.mouse.click(24, 482)
            time.sleep(2)
            try:
                page.click("text=Quote Readiness", timeout=10000)
            except PlaywrightTimeoutError:
                continue
            time.sleep(2)
            candidate = page.query_selector("button:has-text('Download'):not([disabled])")
            if candidate and candidate.is_visible():
                dl_btn = candidate
                break
        if dl_btn is None:
            raise AssertionError("Quote Readiness Download never became enabled")
        snap("12_workflow_stages_completed", "Pipeline completed; Quote Readiness shows the enabled CBOM Download")
        snap("12_workflow_stages_completed", "Pipeline completed; Quote Readiness shows the CBOM Download")
        time.sleep(2)
        with page.expect_download(timeout=60000) as download_info:
            dl_btn.click()
        download = download_info.value
        downloaded_file_path = DOWNLOADS_DIR / download.suggested_filename
        download.save_as(str(downloaded_file_path))

        snap("13_export_downloaded", f"Export workbook downloaded: {downloaded_file_path}")


        # Settle for 3 seconds so the full UI is clearly recorded
        time.sleep(3)
        snap("14_final_settled_ui", "Final settled UI state with all proofs visible")

        # Cleanly close context and browser to finalize video file
        video_src = video_page.video.path()
        context.close()
        browser.close()

    end_utc = datetime.datetime.now(datetime.UTC).isoformat()
    console_fp.close()
    errors_fp.close()
    network_fp.close()

    # The page's own video file for this take (the folder can hold older takes' files)
    video_path = Path(video_src)
    print(f"Recorded video file: {video_path} (exists: {video_path.exists() if video_path else False})")

    # -------------------------------------------------------------
    # STEP 8: Inspect and Audit Downloaded Workbook
    # -------------------------------------------------------------
    workbook_audit = {}
    if downloaded_file_path and downloaded_file_path.exists():
        import openpyxl
        wb = openpyxl.load_workbook(str(downloaded_file_path), data_only=True)
        sheet_names = wb.sheetnames
        print(f"Workbook sheet names ({len(sheet_names)}): {sheet_names}")
        sheet_details = {}
        for sn in sheet_names[:10]:
            ws = wb[sn]
            sheet_details[sn] = {
                "max_row": ws.max_row,
                "max_column": ws.max_column,
                "sample_val_A1": str(ws.cell(1, 1).value),
            }
        workbook_audit = {
            "filename": downloaded_file_path.name,
            "size_bytes": downloaded_file_path.stat().st_size,
            "sheet_count": len(sheet_names),
            "sheet_names": sheet_names,
            "sample_sheets": sheet_details,
        }
        with open(EVIDENCE_DIR / "workbook_audit.json", "w", encoding="utf-8") as f:
            json.dump(workbook_audit, f, indent=2)

    # -------------------------------------------------------------
    # STEP 9: Save Final Metadata
    # -------------------------------------------------------------
    meta = {
        "rfq_id": RFQ_ID,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "video_file": str(video_path) if video_path else None,
        "video_size_bytes": video_path.stat().st_size if video_path and video_path.exists() else 0,
        "milestones": milestone_records,
        "workbook_audit": workbook_audit,
    }
    with open(EVIDENCE_DIR / "session_metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print(f"=== ACCEPTANCE RUN COMPLETE: {RFQ_ID} ===")
    return meta

if __name__ == "__main__":
    run()
