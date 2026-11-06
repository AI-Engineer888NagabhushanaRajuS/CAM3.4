import { TabbedMasterPage } from './TabbedMasterPage';

export function ProjectPage() {
  return (
    <TabbedMasterPage
      title="Project Master"
      subtitle="Manage projects, RFQs, suppliers, and workflow templates"
      excelUrl="/data/project-master.xlsx"
    />
  );
}
