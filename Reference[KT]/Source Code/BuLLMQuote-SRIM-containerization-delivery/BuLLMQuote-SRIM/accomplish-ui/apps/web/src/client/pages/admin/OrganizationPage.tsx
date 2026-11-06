import { TabbedMasterPage } from './TabbedMasterPage';

export function OrganizationPage() {
  return (
    <TabbedMasterPage
      title="Organization Master"
      subtitle="Manage tenants, employees, customers, and organizational structure"
      excelUrl="/data/organization-master.xlsx"
    />
  );
}
