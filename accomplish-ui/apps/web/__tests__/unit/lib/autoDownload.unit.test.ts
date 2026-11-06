import { describe, it, expect, beforeEach, vi } from 'vitest';
import { autoDownloadEnabled, claimAutoDownload, saveFromUrl, setAutoDownload } from '@/lib/autoDownload';

describe('auto download of the finished report (SPEC-023)', () => {
  beforeEach(() => localStorage.clear());

  it('is on until the user turns it off, and remembers the choice', () => {
    expect(autoDownloadEnabled()).toBe(true);
    setAutoDownload(false);
    expect(autoDownloadEnabled()).toBe(false);
    setAutoDownload(true);
    expect(autoDownloadEnabled()).toBe(true);
  });

  it('claims an RFQ once per page load, so a browser never gets a second automatic download to prompt about', () => {
    expect(claimAutoDownload('RFQ-1')).toBe(true);
    expect(claimAutoDownload('RFQ-1')).toBe(false);
    expect(claimAutoDownload('RFQ-2')).toBe(true);
  });

  it('saves through a hidden link that is removed again', () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    saveFromUrl('http://bridge/api/bom/export/RFQ-1/download');
    expect(click).toHaveBeenCalledTimes(1);
    expect(document.querySelector('a[href="http://bridge/api/bom/export/RFQ-1/download"]')).toBeNull();
    click.mockRestore();
  });
});
