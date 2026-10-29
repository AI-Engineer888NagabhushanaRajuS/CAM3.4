import { TabbedMasterPage } from './TabbedMasterPage';

export function CostingPage() {
  return (
    <TabbedMasterPage
      title="Quote Master"
      subtitle="Manage quote structure, BOM, pricing, and assembly routing"
      excelUrl="/data/quote-master.xlsx"
    />
  );
}
