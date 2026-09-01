/**
 * The single data source. One SSE connection owns every section; components read from
 * context and never fetch the same data independently (architecture section 9).
 */
import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from "react";
import type { ReactNode } from "react";
import { api, ApiError } from "./client";
import type { Envelope, NodeInfo, Snapshot } from "./types";

export type ConnState = "connecting" | "live" | "retrying" | "unauthorized" | "offline";

interface StreamValue {
  snapshot: Snapshot | null;
  conn: ConnState;
  nodes: NodeInfo[];
  nodeId: string;
  setNodeId: (id: string) => void;
  lastError: string | null;
  section: <T>(name: string) => Envelope<T> | undefined;
  reconnect: () => void;
}

const Ctx = createContext<StreamValue | null>(null);
const MAX_BACKOFF = 30_000;

export function StreamProvider({ children }: { children: ReactNode }) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [conn, setConn] = useState<ConnState>("connecting");
  const [nodes, setNodes] = useState<NodeInfo[]>([]);
  const [nodeId, setNodeId] = useState("local");
  const [lastError, setLastError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const attempt = useRef(0);

  // Remote nodes are polled over REST: a browser holding one SSE stream per node would
  // multiply connections for no gain, since the aggregator already federates them.
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const list = await api.get<NodeInfo[]>("/api/nodes");
        if (!cancelled) setNodes(list);
      } catch {
        /* nodes are a nicety; the local stream is the product */
      }
    };
    load();
    const t = setInterval(load, 30_000);
    return () => { cancelled = true; clearInterval(t); };
  }, [nonce]);

  useEffect(() => {
    if (nodeId !== "local") return; // non-local nodes use the polling effect below
    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let closed = false;

    const connect = async () => {
      if (closed) return;
      setConn(attempt.current === 0 ? "connecting" : "retrying");
      let url: string;
      try {
        url = await api.streamUrl();
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          setConn("unauthorized");
          setLastError("Authentication required.");
          return;
        }
        schedule();
        return;
      }
      source = new EventSource(url);
      source.addEventListener("snapshot", (ev) => {
        attempt.current = 0;
        setSnapshot(JSON.parse((ev as MessageEvent).data) as Snapshot);
        setConn("live");
        setLastError(null);
      });
      source.onerror = () => {
        source?.close();
        source = null;
        schedule();
      };
    };

    const schedule = () => {
      if (closed) return;
      const delay = Math.min(1000 * 2 ** attempt.current, MAX_BACKOFF);
      attempt.current += 1;
      setConn("retrying");
      retry = setTimeout(connect, delay);
    };

    connect();
    return () => {
      closed = true;
      source?.close();
      if (retry) clearTimeout(retry);
    };
  }, [nodeId, nonce]);

  useEffect(() => {
    if (nodeId === "local") return;
    let cancelled = false;
    const poll = async () => {
      try {
        const snap = await api.get<Snapshot>(`/api/snapshot?node=${encodeURIComponent(nodeId)}`);
        if (!cancelled) { setSnapshot(snap); setConn("live"); }
      } catch (err) {
        if (!cancelled) {
          setConn("retrying");
          setLastError(err instanceof Error ? err.message : String(err));
        }
      }
    };
    poll();
    const t = setInterval(poll, 5000);
    return () => { cancelled = true; clearInterval(t); };
  }, [nodeId, nonce]);

  const section = useCallback(
    <T,>(name: string) => snapshot?.sections?.[name] as Envelope<T> | undefined,
    [snapshot],
  );
  const reconnect = useCallback(() => { attempt.current = 0; setNonce((n) => n + 1); }, []);

  const value = useMemo<StreamValue>(
    () => ({ snapshot, conn, nodes, nodeId, setNodeId, lastError, section, reconnect }),
    [snapshot, conn, nodes, nodeId, lastError, section, reconnect],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStream(): StreamValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useStream must be used inside <StreamProvider>");
  return v;
}

export function useSection<T>(name: string): Envelope<T> | undefined {
  return useStream().section<T>(name);
}
