"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { apiFetch, APIError } from "@/lib/api";
import type { APIResponse } from "@/types";

interface UseAPIResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useAPI<T>(
  url: string | null,
  pollInterval?: number
): UseAPIResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchData = useCallback(async () => {
    if (!url) {
      setLoading(false);
      return;
    }

    try {
      const response: APIResponse<T> = await apiFetch<T>(url);
      setData(response.data);
      setError(null);
    } catch (err) {
      if (err instanceof APIError) {
        setError(`${err.message}`);
      } else {
        setError("Failed to fetch data");
      }
    } finally {
      setLoading(false);
    }
  }, [url]);

  useEffect(() => {
    setLoading(true);
    fetchData();

    if (pollInterval && pollInterval > 0) {
      intervalRef.current = setInterval(fetchData, pollInterval);
    }

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [fetchData, pollInterval]);

  return { data, loading, error, refetch: fetchData };
}
