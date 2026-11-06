import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Plus } from '@phosphor-icons/react';
import { loadMasterTabs, type MasterRow, type MasterTab } from '../../lib/masterExcel';
import { GenericMasterTable } from '../../components/admin/GenericMasterTable';
import { GenericRowModal } from '../../components/admin/GenericRowModal';
import { BulkUploadButton } from '../../components/admin/BulkUploadButton';
import { useAdminHeader } from '../../components/admin/AdminHeaderContext';

interface TabbedMasterPageProps {
  title: string;
  subtitle: string;
  excelUrl: string;
  /** Optional badge rendered next to the title -- e.g. a customer/org logo. */
  logo?: ReactNode;
}

/** Shared engine behind Organization / Project / Quote Master -- each sheet
 * in the source workbook becomes one horizontal tab, with its own columns
 * and rows (see lib/masterExcel.ts for the parsing contract). */
export function TabbedMasterPage({ title, subtitle, excelUrl, logo }: TabbedMasterPageProps) {
  const [tabs, setTabs] = useState<MasterTab[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);
  const [rowsByTab, setRowsByTab] = useState<Record<string, MasterRow[]>>({});
  const [search, setSearch] = useState('');
  const [modalOpen, setModalOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadMasterTabs(excelUrl)
      .then((loadedTabs) => {
        if (cancelled) { return; }
        setTabs(loadedTabs);
        setActiveTabId(loadedTabs[0]?.id ?? null);
        setRowsByTab(Object.fromEntries(loadedTabs.map((tab) => [tab.id, tab.rows])));
      })
      .catch((error: unknown) => {
        if (!cancelled) { setLoadError(error instanceof Error ? error.message : String(error)); }
      });
    return () => { cancelled = true; };
  }, [excelUrl]);

  const activeTab = tabs?.find((tab) => tab.id === activeTabId) ?? null;
  const activeRows = useMemo(
    () => (activeTabId ? rowsByTab[activeTabId] ?? [] : []),
    [activeTabId, rowsByTab],
  );

  const filteredRows = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q || !activeTab) { return activeRows; }
    return activeRows.filter((row) =>
      activeTab.columns.some((column) => String(row[column] ?? '').toLowerCase().includes(q)),
    );
  }, [activeRows, activeTab, search]);

  useAdminHeader({ title, count: filteredRows.length, total: activeRows.length });

  const handleTabClick = (tabId: string) => {
    setActiveTabId(tabId);
    setSearch('');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleAddRow = (values: Record<string, string>) => {
    if (!activeTabId) { return; }
    // Belt-and-suspenders: the modal's own Save button is already disabled
    // for an all-blank form, but guard here too rather than trust that as
    // the only thing standing between a click and a junk empty row.
    const hasAnyValue = Object.values(values).some((v) => v.trim() !== '');
    if (!hasAnyValue) { return; }
    setRowsByTab((prev) => {
      const existingRows = prev[activeTabId] ?? [];
      const newRow: MasterRow = { id: `${activeTabId}-new-${Date.now()}`, ...values };
      return { ...prev, [activeTabId]: [...existingRows, newRow] };
    });
    setModalOpen(false);
  };

  const handleCellChange = (rowId: string, column: string, value: string | boolean) => {
    if (!activeTabId) { return; }
    setRowsByTab((prev) => ({
      ...prev,
      [activeTabId]: (prev[activeTabId] ?? []).map((r) => (r.id === rowId ? { ...r, [column]: value } : r)),
    }));
  };

  const handleDeleteRow = (rowId: string) => {
    if (!activeTabId) { return; }
    if (!window.confirm('Delete this row?')) { return; }
    setRowsByTab((prev) => ({
      ...prev,
      [activeTabId]: (prev[activeTabId] ?? []).filter((r) => r.id !== rowId),
    }));
  };

  const handleBulkImport = (importedRows: MasterRow[]) => {
    if (!activeTabId) { return; }
    setRowsByTab((prev) => {
      const existingRows = prev[activeTabId] ?? [];
      return { ...prev, [activeTabId]: [...existingRows, ...importedRows] };
    });
  };

  if (loadError) {
    return (
      <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        Could not load {title}: {loadError}
      </div>
    );
  }

  if (!tabs || !activeTab) {
    return <div className="p-6 text-sm text-muted-foreground">Loading {title}...</div>;
  }

  return (
    <div>
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          {logo}
          <div>
            <h1 className="text-lg font-bold text-foreground">{title}</h1>
            <p className="mt-0.5 text-sm text-muted-foreground">{subtitle}</p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <BulkUploadButton tabId={activeTab.id} columns={activeTab.columns} onImport={handleBulkImport} />
          <button
            type="button"
            onClick={() => setModalOpen(true)}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-3.5 py-2 text-sm font-semibold text-primary-foreground transition hover:opacity-90"
          >
            <Plus className="h-4 w-4" weight="bold" />
            Add Row
          </button>
        </div>
      </div>

      <div className="mt-4 flex gap-1 overflow-x-auto border-b border-border dark:border-white/10">
        {tabs.map((tab) => {
          const tabRowCount = rowsByTab[tab.id]?.length ?? tab.rows.length;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => handleTabClick(tab.id)}
              className={`flex shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-3.5 py-2 text-sm font-medium transition ${
                tab.id === activeTabId
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              {tab.label}
              <span
                className={`inline-flex h-5 min-w-5 items-center justify-center rounded-full px-1 text-[11px] font-semibold ${
                  tab.id === activeTabId ? 'bg-primary/15 text-primary' : 'bg-muted text-muted-foreground'
                }`}
              >
                {tabRowCount}
              </span>
            </button>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center gap-2.5 py-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={`Search ${activeTab.label}...`}
          className="w-full max-w-xs flex-1 min-w-[200px] rounded-lg border border-border bg-card px-3 py-2 text-sm outline-none transition focus:border-primary/50 focus:ring-1 focus:ring-primary/30 dark:border-white/10 dark:bg-white/[0.03]"
        />
        <span className="ml-auto shrink-0 text-xs font-medium text-muted-foreground">
          {filteredRows.length} of {activeRows.length} rows
        </span>
      </div>

      <GenericMasterTable
        columns={activeTab.columns}
        rows={filteredRows}
        onCellChange={handleCellChange}
        onDeleteRow={handleDeleteRow}
      />

      <GenericRowModal
        open={modalOpen}
        onOpenChange={setModalOpen}
        tabLabel={activeTab.label}
        columns={activeTab.columns}
        initialValues={null}
        onSave={handleAddRow}
      />
    </div>
  );
}
