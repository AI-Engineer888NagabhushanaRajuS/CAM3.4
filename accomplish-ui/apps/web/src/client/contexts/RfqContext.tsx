import { createContext, useContext, type ReactNode } from 'react';

/**
 * Exposes the middle pane's currently-active RFQ (App.tsx's own
 * `activeRfqId` state) to the routed chat pages (HomePage/ExecutionPage)
 * without prop-drilling through the router outlet or coupling taskStore
 * (about tasks, not RFQ browsing state) to RFQ state App.tsx already owns
 * and manages the lifecycle of.
 *
 * `activeRfqId` is distinct from App.tsx's `customRfqId` (which updates on
 * every keystroke of the RFQ-ID search box) -- it only changes at explicit
 * RFQ-switch points, so it's the right value for "which RFQ should a newly
 * created chat task be scoped to."
 */
export interface RfqContextValue {
  activeRfqId: string;
}

const RfqContext = createContext<RfqContextValue>({ activeRfqId: '' });

export function RfqProvider({ activeRfqId, children }: { activeRfqId: string; children: ReactNode }) {
  return <RfqContext.Provider value={{ activeRfqId }}>{children}</RfqContext.Provider>;
}

export function useRfqContext(): RfqContextValue {
  return useContext(RfqContext);
}
