import { describe, expect, it } from "vitest";
import type { RemoteDevice } from "../client";
import {
  credentialsHref,
  deviceHrefForCredential,
  matchRemoteDevice,
  normalizeHostKey,
  rowDomId,
  rustdeskHrefForHost,
} from "./deviceLinks";

function makeDevice(overrides: Partial<RemoteDevice> = {}): RemoteDevice {
  return {
    id: "dev-1",
    hostname: "VNA-KKM-1506",
    location: null,
    source_kind: "cash_register",
    type_tag: "KKM",
    computer_id: null,
    media_player_id: null,
    cash_register_id: "cr-1",
    rustdesk_id: "VNA_KKM_1506",
    has_password: true,
    password_rotated_at: null,
    deploy_profile: "client",
    desired_hidden: true,
    desired_block_outgoing: true,
    desired_unattended: true,
    managed: true,
    in_address_book: true,
    ab_password_pushed: true,
    deploy_state: "configured",
    deploy_detail: null,
    deploy_requested_at: null,
    deploy_reported_at: null,
    readiness: "ready",
    installed_version: null,
    os_edition: null,
    os_caption: null,
    applocker_supported: null,
    applocker_mismatch: false,
    online: true,
    logged_in_user: null,
    last_ip: null,
    last_seen_at: null,
    host_online: null,
    host_last_seen_at: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("normalizeHostKey", () => {
  it("lower-cases and trims", () => {
    expect(normalizeHostKey("  VNA-KKM-1506  ")).toBe("vna-kkm-1506");
  });
  it("strips a scheme, path and port", () => {
    expect(normalizeHostKey("https://10.10.1.1:8443/login?x=1")).toBe("10.10.1.1");
  });
  it("returns empty for null/blank", () => {
    expect(normalizeHostKey(null)).toBe("");
    expect(normalizeHostKey("   ")).toBe("");
  });
});

describe("rowDomId", () => {
  it("is stable across case/whitespace variants of the same identity", () => {
    expect(rowDomId("VNA-KKM-1506")).toBe(rowDomId(" vna-kkm-1506 "));
  });
});

describe("deviceHrefForCredential", () => {
  it("builds a filtered+focused link for a mapped category with a host", () => {
    expect(deviceHrefForCredential({ category: "computer", host: "VNA-MGR-101" })).toBe(
      "/computers?q=VNA-MGR-101&focus=VNA-MGR-101",
    );
  });
  it("returns null without a matching route", () => {
    expect(deviceHrefForCredential({ category: "server", host: "10.0.0.1" })).toBeNull();
  });
  it("returns null without a host", () => {
    expect(deviceHrefForCredential({ category: "computer", host: null })).toBeNull();
  });
});

describe("credentialsHref", () => {
  it("filters the vault by the given identity", () => {
    expect(credentialsHref("VNA-KKM-1506")).toBe("/credentials?q=VNA-KKM-1506");
  });
});

describe("matchRemoteDevice / rustdeskHrefForHost", () => {
  it("matches case/whitespace-insensitively", () => {
    const map = new Map([["VNA-KKM-1506", makeDevice()]]);
    expect(matchRemoteDevice(" vna-kkm-1506 ", map)?.id).toBe("dev-1");
    expect(rustdeskHrefForHost(" vna-kkm-1506 ", map)).toBe(
      "rustdesk://connection/new/VNA_KKM_1506",
    );
  });
  it("returns null when nothing matches", () => {
    const map = new Map([["VNA-KKM-1506", makeDevice()]]);
    expect(matchRemoteDevice("other-host", map)).toBeNull();
    expect(rustdeskHrefForHost("other-host", map)).toBeNull();
  });
  it("falls back to hostname when rustdesk_id is unset", () => {
    const map = new Map([["VNA-KKM-1506", makeDevice({ rustdesk_id: null })]]);
    expect(rustdeskHrefForHost("VNA-KKM-1506", map)).toBe(
      "rustdesk://connection/new/VNA-KKM-1506",
    );
  });
});
