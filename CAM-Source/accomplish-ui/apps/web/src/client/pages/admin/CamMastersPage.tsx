import { TabbedMasterPage } from './TabbedMasterPage';

/** The CAM masters, exactly as the review workbook holds them: each sheet is one tab, with its fixed columns and rows. */
export function CamMastersPage() {
  return (
    <TabbedMasterPage
      title="CAM Masters"
      subtitle="Organisations, Skill factory and Tool Factory: the masters for CAM, as reviewed (contents for review, 17 Nov 2026)"
      excelUrl="/data/cam-masters.xlsx"
    />
  );
}
