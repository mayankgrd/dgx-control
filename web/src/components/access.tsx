/**
 * Getting from "this exists" to "I am using it" (spec R11, R16, FE-10).
 *
 * The server supplies what the service is and where the machine can be reached; the browser
 * knows where the viewer is. Composition happens here.
 */
import { useState } from "react";
import type { HostAddressInfo, ServiceInfo } from "../api/types";
import { planAccess, type AccessPlan } from "../reachability";

export function viewerOrigin(): string {
  return window.location.hostname;
}

export function servicePlan(svc: ServiceInfo, host: HostAddressInfo): AccessPlan {
  const path = svc.path && svc.path !== "/v1/models" ? svc.path : "/";
  return planAccess(svc.bind_ip, svc.port, viewerOrigin(), host, path, svc.is_self);
}

export function CopyButton({ text, label = "copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
        } catch {
          // Clipboard is blocked in some contexts; the text is on screen either way, so this
          // must not look like a failure of the page.
        }
        setDone(true);
        setTimeout(() => setDone(false), 1500);
      }}
      className="shrink-0 rounded border border-[var(--color-edge)] px-1.5 py-0.5 text-[11px] text-[var(--color-ink-dim)] hover:bg-[var(--color-panel-2)]"
    >
      {done ? "copied" : label}
    </button>
  );
}

function Command({ text }: { text: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <code className="min-w-0 flex-1 overflow-x-auto rounded bg-[var(--color-surface)] px-1.5 py-1 text-[11px] whitespace-nowrap">
        {text}
      </code>
      <CopyButton text={text} />
    </div>
  );
}

/** A credential-bearing link: masked until revealed (FE-C11). */
function TokenLink({ url, plain }: { url: string; plain: string }) {
  const [revealed, setRevealed] = useState(false);
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-2">
        <a href={url} target="_blank" rel="noreferrer"
          className="text-xs font-medium text-teal-300 hover:underline">Open ↗</a>
        <span className="rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-300">
          includes token
        </span>
        <CopyButton text={url} label="copy link" />
        <button onClick={() => setRevealed((r) => !r)}
          className="text-[11px] text-[var(--color-ink-faint)] hover:text-[var(--color-ink-dim)]">
          {revealed ? "hide" : "reveal"}
        </button>
      </div>
      <code className="block overflow-x-auto rounded bg-[var(--color-surface)] px-1.5 py-1 text-[11px] text-[var(--color-ink-dim)]">
        {revealed ? url : `${plain}?token=${"•".repeat(12)}`}
      </code>
    </div>
  );
}

export function AccessBlock({ svc, host }: { svc: ServiceInfo; host: HostAddressInfo }) {
  const plan = servicePlan(svc, host);
  const primary = plan.routes[0];

  if (!svc.linkable) {
    return (
      <div className="space-y-1.5 text-xs text-[var(--color-ink-dim)]">
        {svc.auth_hint && <p>{svc.auth_hint}</p>}
        {!svc.auth_hint && <p className="text-[var(--color-ink-faint)]">Not a web service.</p>}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {primary && (
        svc.auth_query
          ? <TokenLink url={primary.url + svc.auth_query} plain={primary.url} />
          : (
            <div className="flex flex-wrap items-center gap-2">
              <a href={primary.url} target="_blank" rel="noreferrer"
                className="text-xs font-medium text-teal-300 hover:underline">Open ↗</a>
              <span className="text-[11px] text-[var(--color-ink-faint)]">{primary.label}</span>
              <CopyButton text={primary.url} label="copy link" />
            </div>
          )
      )}

      {plan.routes.length > 1 && (
        <details className="text-[11px] text-[var(--color-ink-faint)]">
          <summary className="cursor-pointer">other addresses</summary>
          <ul className="mt-1 space-y-1">
            {plan.routes.slice(1).map((r) => (
              <li key={r.url} className="flex items-center gap-1.5">
                <a href={r.url + (svc.auth_query ?? "")} target="_blank" rel="noreferrer"
                  className="text-teal-300 hover:underline">{r.url}</a>
                <span>· {r.label}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      {primary?.caveat && (
        <p className="text-[11px] text-amber-300/80">{primary.caveat}</p>
      )}

      {plan.forwardCommand && (
        <div className="space-y-1 rounded border border-[var(--color-edge)] bg-[var(--color-surface)]/60 p-2">
          <p className="text-[11px] text-[var(--color-ink-faint)]">{plan.forwardReason}</p>
          <Command text={plan.forwardCommand} />
          <p className="text-[11px] text-[var(--color-ink-faint)]">
            then open <a href={plan.forwardUrl} target="_blank" rel="noreferrer"
              className="text-teal-300 hover:underline">{plan.forwardUrl}</a>
          </p>
        </div>
      )}

      {plan.unreachableReason && (
        <p className="text-[11px] text-amber-300/80">{plan.unreachableReason}</p>
      )}

      {svc.base_url && (primary || plan.forwardUrl) && (
        // A forwarded service still has an API endpoint — it just lives behind the tunnel.
        <div className="space-y-1">
          <div className="text-[11px] text-[var(--color-ink-faint)]">
            OpenAI base URL{plan.forwardUrl && !primary ? " (once forwarded)" : ""}
            {svc.served_models.length > 0 && <> · model <code>{svc.served_models[0]}</code></>}
          </div>
          <Command text={apiBase((primary?.url ?? plan.forwardUrl)!, svc)} />
        </div>
      )}

      {svc.auth_hint && svc.linkable && (
        <p className="text-[11px] text-[var(--color-ink-faint)]">{svc.auth_hint}</p>
      )}
    </div>
  );
}

export function apiBase(routeUrl: string, svc: ServiceInfo): string {
  // routeUrl carries the browsable path (/docs for vLLM); the API base is a different path
  // on the same origin.
  const u = new URL(routeUrl);
  return `${u.protocol}//${u.host}${svc.base_url ?? "/v1"}`;
}
