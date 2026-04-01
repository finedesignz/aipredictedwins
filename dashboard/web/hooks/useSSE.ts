"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import type { ActivityEvent } from "@/types";

interface UseSSEResult {
  events: ActivityEvent[];
  connected: boolean;
  error: string | null;
  clear: () => void;
}

const MAX_EVENTS = 100;
const RECONNECT_DELAY = 3000;

export function useSSE(url: string): UseSSEResult {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
    null
  );

  const clear = useCallback(() => {
    setEvents([]);
  }, []);

  useEffect(() => {
    function connect() {
      if (sourceRef.current) {
        sourceRef.current.close();
      }

      const source = new EventSource(url);
      sourceRef.current = source;

      source.onopen = () => {
        setConnected(true);
        setError(null);
      };

      source.onmessage = (event) => {
        try {
          const parsed: ActivityEvent = JSON.parse(event.data);
          setEvents((prev) => {
            const next = [parsed, ...prev];
            return next.slice(0, MAX_EVENTS);
          });
        } catch {
          // skip malformed events
        }
      };

      source.onerror = () => {
        setConnected(false);
        setError("Connection lost. Reconnecting...");
        source.close();

        reconnectTimeoutRef.current = setTimeout(() => {
          connect();
        }, RECONNECT_DELAY);
      };
    }

    connect();

    return () => {
      if (sourceRef.current) {
        sourceRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, [url]);

  return { events, connected, error, clear };
}
