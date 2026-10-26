import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { ownerHiddenLabel, PrivilegedNotice } from "../components/privileged";
import type { NetworkSection } from "../api/types";

const section = (over: Partial<NetworkSection> = {}): NetworkSection => ({
  listeners: [], findings: [], local_addresses: [],
  owners_source: "unprivileged", hidden_owners: 9,
  privileged: "not_installed", privileged_detail: "not installed",
  privileged_fix: "sudo /opt/dgxctl/enable.sh", ...over,
});

beforeEach(() => {
  Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
});

describe("FE-7.5 hidden owners are explained, with the one command that reveals them", () => {
  it("states how many are hidden and gives the command", () => {
    render(<PrivilegedNotice section={section()} />);
    expect(screen.getByText(/9 owners hidden/)).toBeTruthy();
    expect(screen.getByText("sudo /opt/dgxctl/enable.sh")).toBeTruthy();
    expect(screen.getByText(/dgxctl privileged/)).toBeTruthy();
  });

  it("says nothing when no owner is hidden", () => {
    const { container } = render(<PrivilegedNotice section={section({ hidden_owners: 0 })} />);
    expect(container.textContent).toBe("");
  });

  it("confirms when the helper is in use", () => {
    render(<PrivilegedNotice section={section({ privileged: "enabled", owners_source: "privileged" })} />);
    expect(screen.getByText(/privileged helper/)).toBeTruthy();
    expect(screen.queryByText(/hidden/)).toBeNull();
  });

  it("raises an alert, not a hint, for an insecure helper", () => {
    render(<PrivilegedNotice section={section({ privileged: "insecure", privileged_detail: "uid=1000" })} />);
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toMatch(/not safe to use/);
    expect(alert.textContent).toMatch(/uid=1000/);
  });
});

describe("the owner cell", () => {
  it("explains why the owner is missing rather than just saying it is", () => {
    expect(ownerHiddenLabel({ privileged: "not_installed" })).toMatch(/unprivileged/);
    expect(ownerHiddenLabel({ privileged: "enabled" })).toBe("owner not reported");
  });
});
