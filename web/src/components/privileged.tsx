/**
 * Telling the operator why some socket owners are hidden, and the one command that reveals
 * them (spec R17.8, FE-7.5). dgxctl never escalates on its own; this only explains.
 */
import type { NetworkSection } from "../api/types";
import { CopyButton } from "./access";

export function ownerHiddenLabel(section: Pick<NetworkSection, "privileged">): string {
  return section.privileged === "enabled"
    ? "owner not reported"
    : "owner hidden (dgxctl runs unprivileged)";
}

export function PrivilegedNotice({ section }: { section: NetworkSection }) {
  const { privileged, hidden_owners: hidden, privileged_fix: fix, privileged_detail: detail } =
    section;

  if (privileged === "insecure") {
    return (
      <div role="alert"
        className="rounded border border-rose-500/50 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
        <strong>The privileged helper is installed but not safe to use</strong>, so dgxctl is
        ignoring it. {detail}
        {fix && <div className="mt-1.5 flex items-center gap-1.5">
          <code className="rounded bg-[var(--color-surface)] px-1.5 py-1">{fix}</code>
          <CopyButton text={fix} />
        </div>}
      </div>
    );
  }

  if (privileged === "enabled") {
    return (
      <p className="text-xs text-[var(--color-ink-faint)]">
        Socket owners are read through the privileged helper, so sockets belonging to other users
        are named too.
      </p>
    );
  }

  if (hidden === 0) return null;

  return (
    <div className="rounded border border-[var(--color-edge)] bg-[var(--color-panel-2)] px-3 py-2 text-xs text-[var(--color-ink-dim)]">
      <strong className="text-[var(--color-ink)]">{hidden} owner{hidden === 1 ? "" : "s"} hidden.</strong>{" "}
      dgxctl runs without root, and Linux only tells an unprivileged process who owns its own
      sockets. To name the rest, install the optional read-only helper on the DGX:
      {fix && <div className="mt-1.5 flex items-center gap-1.5">
        <code className="overflow-x-auto rounded bg-[var(--color-surface)] px-1.5 py-1">{fix}</code>
        <CopyButton text={fix} />
      </div>}
      <div className="mt-1 text-[var(--color-ink-faint)]">
        It can only list socket owners. Run <code>dgxctl privileged</code> to read exactly what it
        grants before enabling it.
      </div>
    </div>
  );
}
