/**
 * @vitest-environment jsdom
 */

import '@testing-library/jest-dom/vitest';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AboutTab } from '@/components/settings/AboutTab';
import { PRODUCT_VERSION } from '@/lib/productVersion';

describe('AboutTab', () => {
  it('shows CAM4 for Centum and the product version, never 3.2', () => {
    render(<AboutTab appVersion="" />);
    expect(screen.getByText('CAM4 (for Centum)')).toBeInTheDocument();
    expect(screen.getByText(PRODUCT_VERSION)).toBeInTheDocument();
    expect(PRODUCT_VERSION).toBe('4');
    expect(screen.queryByText('3.2')).not.toBeInTheDocument();
  });

  it('describes the three panes', () => {
    render(<AboutTab appVersion="" />);
    expect(screen.getByText(/^Left: workflow stages/)).toBeInTheDocument();
    expect(screen.getByText(/^Middle: Assistant/)).toBeInTheDocument();
    expect(screen.getByText(/^Right: events and output/)).toBeInTheDocument();
  });

  it('shows the app build only when it is a real version', () => {
    const { rerender } = render(<AboutTab appVersion="0.0.0-browser" />);
    expect(screen.queryByText('App build')).not.toBeInTheDocument();
    rerender(<AboutTab appVersion="0.5.17" />);
    expect(screen.getByText('App build')).toBeInTheDocument();
    expect(screen.getByText('0.5.17')).toBeInTheDocument();
  });
});
