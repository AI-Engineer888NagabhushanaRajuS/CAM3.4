import { useEffect, useRef, useState } from 'react';
import { embedDashboard, type EmbeddedDashboard } from '@superset-ui/embedded-sdk';
import { getAccomplish } from '@/lib/accomplish';
import { SpinningIcon } from './SpinningIcon';

// Matches the dashboard already registered for embedding in the local Superset install
// (see apps/daemon/src/superset-client.ts's default and C:\Superset's embedded_dashboards
// row) -- kept as one shared constant here rather than duplicating the literal UUID.
const DASHBOARD_UUID = '427cde1b-b788-4ff8-b247-1aa3345ec1f0';

interface SupersetDashboardPanelProps {
  // Scopes the embed to just this RFQ's rows via Superset Row Level Security
  // (see superset-client.ts) instead of showing every RFQ ever processed.
  // Omit for the previous unfiltered behavior.
  rfqId?: string;
}

// Stage 9 (Reports & Analytics) right-pane content: the live Superset dashboard,
// filling the available space responsively. Guest tokens are minted server-side by the
// daemon (superset.getGuestToken RPC) -- this component never talks to Superset
// directly except via the iframe the SDK creates.
export function SupersetDashboardPanel({ rfqId }: SupersetDashboardPanelProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isCurrent = true;
    let embedded: EmbeddedDashboard | null = null;

    setLoading(true);
    setError(null);

    (async () => {
      if (!mountRef.current) return;
      try {
        const { supersetDomain } = await getAccomplish().supersetGetGuestToken({ dashboardUuid: DASHBOARD_UUID, rfqId });
        if (!isCurrent || !mountRef.current) return;
        embedded = await embedDashboard({
          id: DASHBOARD_UUID,
          supersetDomain,
          mountPoint: mountRef.current,
          fetchGuestToken: () =>
            getAccomplish()
              .supersetGetGuestToken({ dashboardUuid: DASHBOARD_UUID, rfqId })
              .then((r) => r.guestToken),
          dashboardUiConfig: { hideTitle: false, filters: { expanded: false } },
        });
        if (!isCurrent) {
          embedded.unmount();
          return;
        }
      } catch (err) {
        if (isCurrent) {
          setError(err instanceof Error ? err.message : 'Failed to load dashboard');
        }
      } finally {
        if (isCurrent) setLoading(false);
      }
    })();

    return () => {
      isCurrent = false;
      embedded?.unmount();
    };
  }, [rfqId]);

  return (
    <div className="relative flex h-full w-full flex-1 flex-col overflow-hidden rounded-lg border border-border">
      {loading && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/80">
          <SpinningIcon className="h-8 w-8" />
        </div>
      )}
      {error && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-background p-6">
          <p className="max-w-sm text-center text-sm text-destructive">{error}</p>
        </div>
      )}
      <div ref={mountRef} className="h-full w-full flex-1 [&>iframe]:h-full [&>iframe]:w-full [&>iframe]:border-0" />
    </div>
  );
}
