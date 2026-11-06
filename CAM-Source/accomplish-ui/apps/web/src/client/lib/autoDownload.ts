/**
 * SPEC-023: when a run the user is watching finishes, its report workbook is saved to their computer without another click.
 * One file only, and once per RFQ: a browser asks "allow multiple downloads?" at the second automatic download of a page,
 * and a second prompt would hide the first file. The switch is the user's own and defaults to on.
 */
const KEY = 'cam-auto-download';

export function autoDownloadEnabled(): boolean {
  try {
    return localStorage.getItem(KEY) !== 'off';
  } catch {
    return true; // storage blocked: the default stands
  }
}

export function setAutoDownload(on: boolean): void {
  try {
    localStorage.setItem(KEY, on ? 'on' : 'off');
  } catch { /* the switch then lasts until the page reloads */ }
}

/** Saves `url` through a hidden link; the server's Content-Disposition names the file (the bridge answers with an attachment). */
export function saveFromUrl(url: string): void {
  const a = document.createElement('a');
  a.href = url;
  a.rel = 'noopener';
  a.download = '';
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

const done = new Set<string>();

/** True once per RFQ and per page load: the caller downloads only when this says so. */
export function claimAutoDownload(rfqId: string): boolean {
  if (done.has(rfqId)) return false;
  done.add(rfqId);
  return true;
}
