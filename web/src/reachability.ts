/**
 * Where a service can be reached from, given where the viewer is (spec R16).
 *
 * A mirror of src/dgxctl/reachability.py. It lives on the client because only the browser
 * knows how the viewer arrived; it is a pure function so the matrix is testable.
 */
import type { HostAddressInfo } from "./api/types";

export type ViewerPosition = "loopback" | "lan" | "tailnet" | "unknown";
export type ServiceScope = "all" | "host-only" | "tailnet-only" | "lan-only";

export interface AccessRoute {
  url: string;
  label: string;
  caveat?: string;
}

export interface AccessPlan {
  viewer: ViewerPosition;
  viewerNote: string;
  routes: AccessRoute[];
  forwardCommand?: string;
  forwardUrl?: string;
  forwardReason?: string;
  unreachableReason?: string;
}

const DOCKER_BRIDGE = /^172\.(1[6-9]|2[0-9]|3[01])\./;
const TAILNET_V4 = /^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\./;

export function tailnetTarget(host: HostAddressInfo): string | null {
  return host.tailnet_name || host.tailnet_ip || null;
}

export function classifyViewer(originHost: string, host: HostAddressInfo): ViewerPosition {
  const bare = (originHost || "").replace(/^\[|\]$/g, "").split("%")[0];
  if (!bare) return "unknown";
  if (bare === "localhost" || bare === "127.0.0.1" || bare === "::1") return "loopback";
  if (host.tailnet_name && bare === host.tailnet_name) return "tailnet";
  if (host.tailnet_ip && bare === host.tailnet_ip) return "tailnet";
  if (TAILNET_V4.test(bare)) return "tailnet";
  return "lan";
}

export function serviceScope(bindIp: string): ServiceScope {
  const bare = (bindIp || "").replace(/^\[|\]$/g, "").split("%")[0];
  if (bare === "" || bare === "*" || bare === "0.0.0.0" || bare === "::") return "all";
  if (bare === "127.0.0.1" || bare === "::1" || bare.startsWith("127.")) return "host-only";
  // A Docker bridge address is reachable from the host and its containers — never from
  // anywhere a person is sitting.
  if (DOCKER_BRIDGE.test(bare)) return "host-only";
  if (TAILNET_V4.test(bare)) return "tailnet-only";
  return "lan-only";
}

const VIEWER_NOTES: Record<ViewerPosition, string> = {
  loopback:
    "You opened this dashboard on 127.0.0.1 — either from the DGX itself, or through NVIDIA Sync or an SSH tunnel.",
  lan: "You are reaching this dashboard over the local network.",
  tailnet: "You are reaching this dashboard over the tailnet.",
  unknown: "",
};

export function planAccess(
  bindIp: string,
  port: number,
  originHost: string,
  host: HostAddressInfo,
  path = "/",
  isSelf = false,
): AccessPlan {
  const viewer = classifyViewer(originHost, host);
  const scope = serviceScope(bindIp);
  const suffix = path.startsWith("/") ? path : `/${path}`;
  const url = (h: string) => `http://${h}:${port}${suffix}`;
  const plan: AccessPlan = { viewer, viewerNote: VIEWER_NOTES[viewer], routes: [] };
  const tailnet = tailnetTarget(host);

  if (scope === "all") {
    if (viewer === "tailnet" && tailnet) {
      plan.routes.push({ url: url(tailnet), label: "over the tailnet" });
    } else if (viewer === "lan" && host.lan.length) {
      host.lan.forEach((a) =>
        plan.routes.push({ url: url(a), label: `over the local network (${a})` }),
      );
    } else if (viewer === "loopback") {
      plan.routes.push({ url: url("127.0.0.1"), label: "if your browser is on the DGX itself" });
      host.lan.forEach((a) =>
        plan.routes.push({ url: url(a), label: `from another machine on the LAN (${a})` }),
      );
      if (tailnet) plan.routes.push({ url: url(tailnet), label: "from your tailnet" });
    } else {
      host.lan.forEach((a) =>
        plan.routes.push({ url: url(a), label: `over the local network (${a})` }),
      );
      if (tailnet) plan.routes.push({ url: url(tailnet), label: "over the tailnet" });
    }
    return plan;
  }

  if (scope === "tailnet-only") {
    if (viewer === "tailnet") plan.routes.push({ url: url(bindIp), label: "over the tailnet" });
    else
      plan.unreachableReason =
        "This service is bound to the tailnet address only, so it cannot be reached from where you are.";
    return plan;
  }

  if (scope === "lan-only") {
    if (viewer === "lan" || viewer === "loopback")
      plan.routes.push({ url: url(bindIp), label: `at ${bindIp}` });
    else
      plan.unreachableReason = `This service is bound to ${bindIp} only, which is not reachable from the tailnet.`;
    return plan;
  }

  // host-only
  if (isSelf) {
    plan.routes.push({ url: url("127.0.0.1"), label: "this dashboard" });
    return plan;
  }

  if (viewer === "loopback") {
    plan.routes.push({
      url: url("127.0.0.1"),
      label: "if your browser is running on the DGX itself",
      caveat:
        "If you reached this dashboard through NVIDIA Sync or an SSH tunnel, only the dashboard's own port was forwarded — this one needs its own forward, below.",
    });
  }

  const forwardTarget = viewer === "tailnet" ? tailnet : host.lan[0] || tailnet;
  if (forwardTarget) {
    plan.forwardCommand = `ssh -N -L ${port}:127.0.0.1:${port} ${forwardTarget}`;
    plan.forwardUrl = url("127.0.0.1");
    plan.forwardReason =
      "This service listens on the DGX's loopback address, so nothing outside the machine reaches it directly. Run this on your own machine, then open the link.";
  } else {
    plan.unreachableReason = `This service listens on the DGX's loopback address. Forward it with: ssh -N -L ${port}:127.0.0.1:${port} <your-dgx>`;
  }
  return plan;
}
