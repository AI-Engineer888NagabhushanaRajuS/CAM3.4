import { useState, useCallback, useEffect, useMemo } from 'react';
import { getAccomplish, type Customer, type Project } from '@/lib/accomplish';
import { createLogger } from '@/lib/logger';

const logger = createLogger('ProjectTrackingPanel');

export interface UseProjectTrackingPanelResult {
  loading: boolean;
  customers: Customer[];
  projects: Project[];
  selectedCustomerId: string | null;
  error: string | null;
  setSelectedCustomerId: (id: string | null) => void;
  addCustomer: (name: string) => Promise<boolean>;
  editCustomer: (id: string, name: string) => Promise<boolean>;
  deleteCustomer: (id: string) => Promise<boolean>;
  addProject: (name: string) => Promise<boolean>;
  editProject: (id: string, name: string) => Promise<boolean>;
  deleteProject: (id: string) => Promise<boolean>;
}

/** Newly added customers/projects show up immediately in every dropdown that
 * reads from this same hook -- there's no separate cache to invalidate, each
 * mutation just re-fetches its own list. */
export function useProjectTrackingPanel(): UseProjectTrackingPanelResult {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [allProjects, setAllProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedCustomerId, setSelectedCustomerId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reloadCustomers = useCallback(async () => {
    const { customers: next } = await getAccomplish().listCustomers();
    setCustomers(next);
  }, []);

  const reloadProjects = useCallback(async () => {
    const { projects: next } = await getAccomplish().listProjects({});
    setAllProjects(next);
  }, []);

  useEffect(() => {
    let isCurrent = true;
    Promise.all([reloadCustomers(), reloadProjects()])
      .catch((err: unknown) => logger.error('Failed to load customers/projects:', err))
      .finally(() => { if (isCurrent) { setLoading(false); } });
    return () => { isCurrent = false; };
  }, [reloadCustomers, reloadProjects]);

  const projects = useMemo(
    () => (selectedCustomerId ? allProjects.filter((p) => p.customer_id === selectedCustomerId) : []),
    [allProjects, selectedCustomerId],
  );

  const runMutation = useCallback(async (action: () => Promise<void>) => {
    setError(null);
    try {
      await action();
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return false;
    }
  }, []);

  const addCustomer = useCallback(
    (name: string) => runMutation(async () => {
      await getAccomplish().createCustomer({ customerName: name });
      await reloadCustomers();
    }),
    [runMutation, reloadCustomers],
  );

  const editCustomer = useCallback(
    (id: string, name: string) => runMutation(async () => {
      await getAccomplish().updateCustomer({ customerId: id, customerName: name });
      await reloadCustomers();
    }),
    [runMutation, reloadCustomers],
  );

  const deleteCustomer = useCallback(
    (id: string) => runMutation(async () => {
      await getAccomplish().deleteCustomer({ customerId: id });
      await reloadCustomers();
      if (selectedCustomerId === id) { setSelectedCustomerId(null); }
    }),
    [runMutation, reloadCustomers, selectedCustomerId],
  );

  const addProject = useCallback(
    (name: string) => runMutation(async () => {
      if (!selectedCustomerId) { throw new Error('Select a customer first'); }
      await getAccomplish().createProject({ customerId: selectedCustomerId, projectName: name });
      await reloadProjects();
    }),
    [runMutation, reloadProjects, selectedCustomerId],
  );

  const editProject = useCallback(
    (id: string, name: string) => runMutation(async () => {
      await getAccomplish().updateProject({ projectId: id, projectName: name });
      await reloadProjects();
    }),
    [runMutation, reloadProjects],
  );

  const deleteProject = useCallback(
    (id: string) => runMutation(async () => {
      await getAccomplish().deleteProject({ projectId: id });
      await reloadProjects();
    }),
    [runMutation, reloadProjects],
  );

  return {
    loading,
    customers,
    projects,
    selectedCustomerId,
    error,
    setSelectedCustomerId,
    addCustomer,
    editCustomer,
    deleteCustomer,
    addProject,
    editProject,
    deleteProject,
  };
}
