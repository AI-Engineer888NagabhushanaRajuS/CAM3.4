import { themeQuartz } from 'ag-grid-community';

// AG Grid Theming API (v33+) -- replaces the legacy ag-theme-alpine-dark CSS
// class every grid in the app used before.
//
// The BOM review grids (StageExecutionOutput's intake/CBOM/RFQ/pricing
// preview grids -- everywhere this theme is used) intentionally use their
// OWN dedicated palette (--bom-grid-header-bg/-header-text/-icon/-row-bg/
// -alt-row-bg/-border, defined in styles/globals.css) rather than the app's
// shared --muted/--foreground/--border chrome tokens. This is a deliberate
// exception for this grid's own branded "spreadsheet" look -- do not revert
// it back to the shared tokens. To retune the BOM grid's colors, edit the
// --bom-grid-* variables in globals.css (both the :root light values and the
// .dark values), not the strings below.
export const myTheme = themeQuartz.withParams({
  accentColor: 'hsl(var(--primary))',
  backgroundColor: 'var(--bom-grid-row-bg)',
  borderColor: 'var(--bom-grid-border)',
  borderRadius: 2,
  browserColorScheme: 'dark',
  cellHorizontalPaddingScale: 0.7,
  chromeBackgroundColor: {
    ref: 'backgroundColor',
  },
  columnBorder: false,
  fontFamily: {
    googleFont: 'Inter',
  },
  fontSize: 13,
  foregroundColor: 'hsl(var(--foreground))',
  headerBackgroundColor: 'var(--bom-grid-header-bg)',
  headerFontSize: 13,
  headerFontWeight: 400,
  headerTextColor: 'var(--bom-grid-header-text)',
  iconButtonColor: 'var(--bom-grid-icon)',
  oddRowBackgroundColor: 'var(--bom-grid-alt-row-bg)',
  rowBorder: true,
  rowVerticalPaddingScale: 0.8,
  sidePanelBorder: true,
  spacing: 6,
  wrapperBorder: false,
  wrapperBorderRadius: 2,
});
