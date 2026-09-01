import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import type { Envelope, Exposure, Status } from "../api/types";
import { ageSeconds, bytes, clampPercent, percent } from "../format";

/* ---- FE-C4: the exposure vocabulary, defined once, used everywhere ---- */

const EXPOSURE_STYLE: Record<Exposure, { label: string; cls: string; title: string }> = {
  loopback: {
    label: "loopback", cls: "bg-slate-700/40 text-slate-300 border-slate-600/50",
    title: "Bound to 127.0.0.1 — reachable only from this host.",
  },
  lan: {
    label: "LAN", cls: "bg-amber-500/15 text-amber-300 border-amber-500/40",
    title: "Reachable by any machine on the local network.",
  },
  tailnet: {
    label: "tailnet", cls: "bg-amber-500/15 text-amber-300 border-amber-500/40",
    title: "Reachable by every machine on this tailnet, including ones you do not control.",
  },
  all: {
    label: "0.0.0.0", cls: "bg-rose-500/20 text-rose-300 border-rose-500/50 font-semibold",
    title: "Bound to ALL interfaces — reachable by anyone who can route to this host.",
  },
  unknown: {
    label: "not published", cls: "bg-slate-800/60 text-slate-500 border-slate-700",
    title: "Exposed by the image but not published to the host.",
  },
};

export function ExposureBadge({ exposure }: { exposure: Exposure }) {
  const s = EXPOSURE_STYLE[exposure] ?? EXPOSURE_STYLE.unknown;
  return (
    <span title={s.title}
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[11px] leading-none ${s.cls}`}>
      {s.label}
    </span>
  );
}

/* ---- FE-C2 / FE-C3: panels own their state; staleness is visible, spinners are not ---- */

export function Panel<T>({
  title, envelope, children, actions, interval = 60, subtitle,
}: {
  title: string;
  envelope?: Envelope<T>;
  children: (data: T) => ReactNode;
  actions?: ReactNode;
  interval?: number;
  subtitle?: ReactNode;
}) {
  const status: Status = envelope?.status ?? "ok";
  const age = ageSeconds(envelope?.collected_at);
  const stale = age != null && age > interval * 3;

  return (
    <section className="rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel)]">
      <header className="flex flex-wrap items-center gap-2 border-b border-[var(--color-edge)] px-4 py-2.5">
        <h2 className="text-sm font-semibold tracking-wide">{title}</h2>
        {subtitle && <span className="text-xs text-[var(--color-ink-faint)]">{subtitle}</span>}
        {stale && status === "ok" && (
          <span title={`Last updated ${Math.round(age!)}s ago`}
            className="rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[11px] text-amber-300">
            stale {Math.round(age!)}s
          </span>
        )}
        {status === "error" && (
          <span className="rounded border border-rose-500/40 bg-rose-500/10 px-1.5 py-0.5 text-[11px] text-rose-300">
            error
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">{actions}</div>
      </header>
      <div className="p-4">
        {status === "unavailable" ? (
          <p className="text-sm text-[var(--color-ink-faint)]">
            Not available on this host{envelope?.error ? ` — ${envelope.error}` : "."}
          </p>
        ) : envelope === undefined ? (
          <p className="text-sm text-[var(--color-ink-faint)]">Waiting for first reading…</p>
        ) : (
          <>
            {status === "error" && (
              <p className="mb-3 rounded border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                {envelope.error}
                {envelope.data ? " — showing the last good reading." : ""}
              </p>
            )}
            {envelope.data ? children(envelope.data) : (
              <p className="text-sm text-[var(--color-ink-faint)]">No data yet.</p>
            )}
          </>
        )}
      </div>
    </section>
  );
}

export function StatTile({
  label, value, sub, tone = "neutral", href,
}: {
  label: string; value: ReactNode; sub?: ReactNode;
  tone?: "neutral" | "ok" | "warn" | "bad"; href?: string;
}) {
  const tones = {
    neutral: "border-[var(--color-edge)]",
    ok: "border-emerald-500/30",
    warn: "border-amber-500/40",
    bad: "border-rose-500/50",
  };
  const body = (
    <div className={`rounded-lg border bg-[var(--color-panel)] p-4 ${tones[tone]} ${href ? "transition hover:bg-[var(--color-panel-2)]" : ""}`}>
      <div className="text-xs uppercase tracking-wider text-[var(--color-ink-faint)]">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
      {sub && <div className="mt-1 text-xs text-[var(--color-ink-dim)]">{sub}</div>}
    </div>
  );
  return href ? <a href={href} className="block">{body}</a> : body;
}

export function Bar({
  value, max = 100, tone,
}: { value: number; max?: number; tone?: "ok" | "warn" | "bad" }) {
  const pct = clampPercent((value / max) * 100);
  const color = tone === "bad" ? "bg-rose-500" : tone === "warn" ? "bg-amber-500" : "bg-teal-400";
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--color-panel-2)]">
      <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

/** Segmented single-pool bar. FE-C7: unified memory is ONE pool, never two. */
export function SegmentBar({
  segments, total,
}: { segments: { label: string; value: number; color: string }[]; total: number }) {
  return (
    <div>
      <div className="flex h-4 w-full overflow-hidden rounded bg-[var(--color-panel-2)]">
        {segments.map((s) => (
          <div key={s.label} title={`${s.label}: ${bytes(s.value)}`}
            style={{ width: `${clampPercent((s.value / total) * 100)}%`, background: s.color }} />
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--color-ink-dim)]">
        {segments.map((s) => (
          <span key={s.label} className="inline-flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-sm" style={{ background: s.color }} />
            {s.label} {bytes(s.value)} ({percent((s.value / total) * 100)})
          </span>
        ))}
      </div>
    </div>
  );
}

export function Sparkline({
  points, height = 36, max,
}: { points: { ts: number; value: number }[]; height?: number; max?: number }) {
  if (points.length < 2) {
    return <div style={{ height }} className="flex items-center text-xs text-[var(--color-ink-faint)]">
      collecting…
    </div>;
  }
  const ymax = max ?? Math.max(...points.map((p) => p.value), 1);
  const w = 100;
  const path = points
    .map((p, i) => {
      const x = (i / (points.length - 1)) * w;
      const y = height - (clampPercent((p.value / ymax) * 100) / 100) * height;
      return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  const area = `${path} L${w},${height} L0,${height} Z`;
  return (
    <svg viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none"
      className="w-full" style={{ height }} role="img" aria-label="trend">
      <path d={area} fill="var(--color-accent)" opacity="0.12" />
      <path d={path} fill="none" stroke="var(--color-accent)" strokeWidth="1.5"
        vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-[var(--color-ink-faint)]">{children}</p>;
}

/** FE-C5 / FE-C6: mutating actions confirm and name the target; disabled explains itself. */
export function ActionButton({
  label, onConfirm, confirmText, disabledReason, tone = "neutral",
}: {
  label: string;
  onConfirm: () => Promise<void> | void;
  confirmText: string;
  disabledReason?: string;
  tone?: "neutral" | "danger";
}) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const t = setTimeout(() => setArmed(false), 6000);
    return () => clearTimeout(t);
  }, [armed]);

  if (disabledReason) {
    return (
      <button disabled title={disabledReason}
        className="cursor-not-allowed rounded border border-[var(--color-edge)] px-2 py-1 text-xs text-[var(--color-ink-faint)]">
        {label}
      </button>
    );
  }
  const danger = tone === "danger";
  return armed ? (
    <span className="inline-flex items-center gap-1">
      <button disabled={busy}
        onClick={async () => { setBusy(true); try { await onConfirm(); } finally { setBusy(false); setArmed(false); } }}
        className={`rounded px-2 py-1 text-xs font-medium ${danger ? "bg-rose-600 text-white" : "bg-teal-500 text-slate-900"}`}>
        {busy ? "working…" : confirmText}
      </button>
      <button onClick={() => setArmed(false)}
        className="rounded border border-[var(--color-edge)] px-2 py-1 text-xs text-[var(--color-ink-dim)]">
        cancel
      </button>
    </span>
  ) : (
    <button onClick={() => setArmed(true)}
      className={`rounded border px-2 py-1 text-xs transition hover:bg-[var(--color-panel-2)] ${
        danger ? "border-rose-500/40 text-rose-300" : "border-[var(--color-edge)] text-[var(--color-ink-dim)]"}`}>
      {label}
    </button>
  );
}

export function Table({ head, children }: { head: ReactNode[]; children: ReactNode }) {
  return (
    <div className="-mx-4 overflow-x-auto px-4">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b border-[var(--color-edge)] text-left text-xs uppercase tracking-wider text-[var(--color-ink-faint)]">
            {head.map((h, i) => <th key={i} className="px-2 py-2 font-medium">{h}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--color-edge)]/60">{children}</tbody>
      </table>
    </div>
  );
}
