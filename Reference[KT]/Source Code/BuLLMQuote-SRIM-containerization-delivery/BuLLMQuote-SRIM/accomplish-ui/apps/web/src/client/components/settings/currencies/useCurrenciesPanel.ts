import { useCallback, useEffect, useState } from 'react';
import { getAccomplish, type Currency } from '@/lib/accomplish';

export interface CreateCurrencyParams {
  currencyCode: string;
  currencyName: string;
  conversionRate: number;
}

export interface UpdateCurrencyParams {
  currencyName?: string;
  conversionRate?: number;
  isActive?: boolean;
}

export interface UseCurrenciesPanelResult {
  loading: boolean;
  currencies: Currency[];
  defaultCurrencyCode: string;
  pendingCurrencyCode: string | null; // which row has an in-flight mutation, for per-row disabling
  error: string | null;
  handleCreate: (params: CreateCurrencyParams) => Promise<void>;
  handleUpdate: (currencyCode: string, patch: UpdateCurrencyParams) => Promise<void>;
  handleDelete: (currencyCode: string) => Promise<void>;
  handleToggleActive: (currencyCode: string, nextActive: boolean) => Promise<void>;
  handleSetDefault: (currencyCode: string) => Promise<void>;
}

// Mirrors useUsersPanel.ts's shape -- fetch-once + mutate + refetch, full
// refetch after every mutation rather than optimistic local patching (same
// reasoning: rows have server-derived fields, and the list is small).
export function useCurrenciesPanel(): UseCurrenciesPanelResult {
  const [currencies, setCurrencies] = useState<Currency[]>([]);
  const [defaultCurrencyCode, setDefaultCurrencyCode] = useState('USD');
  const [loading, setLoading] = useState(true);
  const [pendingCurrencyCode, setPendingCurrencyCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    const [{ currencies: fetched }, { currencyCode }] = await Promise.all([
      getAccomplish().listCurrencies(),
      getAccomplish().getDefaultQuoteCurrency(),
    ]);
    setCurrencies(fetched);
    setDefaultCurrencyCode(currencyCode);
  }, []);

  useEffect(() => {
    let isCurrent = true;
    setLoading(true);
    refetch()
      .catch((err: unknown) => {
        if (isCurrent) { setError(err instanceof Error ? err.message : 'Failed to load currencies'); }
      })
      .finally(() => {
        if (isCurrent) { setLoading(false); }
      });
    return () => { isCurrent = false; };
  }, [refetch]);

  const handleCreate = useCallback(async (params: CreateCurrencyParams) => {
    setError(null);
    try {
      await getAccomplish().createCurrency(params);
      await refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create currency');
      throw err;
    }
  }, [refetch]);

  const handleUpdate = useCallback(async (currencyCode: string, patch: UpdateCurrencyParams) => {
    setError(null);
    setPendingCurrencyCode(currencyCode);
    try {
      await getAccomplish().updateCurrency({ currencyCode, ...patch });
      await refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update currency');
      throw err;
    } finally {
      setPendingCurrencyCode(null);
    }
  }, [refetch]);

  const handleDelete = useCallback(async (currencyCode: string) => {
    setError(null);
    setPendingCurrencyCode(currencyCode);
    try {
      await getAccomplish().deleteCurrency({ currencyCode });
      await refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete currency');
      throw err;
    } finally {
      setPendingCurrencyCode(null);
    }
  }, [refetch]);

  const handleToggleActive = useCallback(async (currencyCode: string, nextActive: boolean) => {
    await handleUpdate(currencyCode, { isActive: nextActive });
  }, [handleUpdate]);

  const handleSetDefault = useCallback(async (currencyCode: string) => {
    setError(null);
    try {
      await getAccomplish().setDefaultQuoteCurrency({ currencyCode });
      await refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to set default quote currency');
      throw err;
    }
  }, [refetch]);

  return {
    loading,
    currencies,
    defaultCurrencyCode,
    pendingCurrencyCode,
    error,
    handleCreate,
    handleUpdate,
    handleDelete,
    handleToggleActive,
    handleSetDefault,
  };
}
