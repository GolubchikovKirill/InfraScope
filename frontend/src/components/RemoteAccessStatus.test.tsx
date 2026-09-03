import { render, screen } from "@testing-library/react";
import type { RemoteDevice } from "../client";
import { AppLockerMismatchBadge, ReadinessChip, READINESS_META, deviceReadinessDetail } from "./RemoteAccessStatus";

function makeDevice(overrides: Partial<RemoteDevice> = {}): RemoteDevice {
  return {
    id: "dev-1",
    hostname: "VNK-MGR-D1",
    location: "A1",
    source_kind: "computer",
    computer_id: null,
    media_player_id: null,
    cash_register_id: null,
    rustdesk_id: "VNK_MGR_D1",
    has_password: true,
    password_rotated_at: null,
    deploy_profile: "client",
    desired_hidden: true,
    desired_block_outgoing: true,
    desired_unattended: true,
    managed: true,
    in_address_book: false,
    ab_password_pushed: false,
    deploy_state: "unknown",
    deploy_detail: null,
    deploy_requested_at: null,
    deploy_reported_at: null,
    readiness: "not_deployed",
    installed_version: null,
    os_edition: null,
    os_caption: null,
    applocker_supported: null,
    applocker_mismatch: false,
    online: null,
    logged_in_user: null,
    last_ip: null,
    last_seen_at: null,
    host_online: null,
    host_last_seen_at: null,
    created_at: "2026-09-01T00:00:00Z",
    ...overrides,
  };
}

describe("ReadinessChip", () => {
  it("shows the right label for every readiness value", () => {
    (Object.keys(READINESS_META) as Array<keyof typeof READINESS_META>).forEach((r) => {
      const { unmount } = render(<ReadinessChip readiness={r} />);
      expect(screen.getByText(READINESS_META[r].label)).toBeInTheDocument();
      unmount();
    });
  });
});

describe("deviceReadinessDetail", () => {
  it("explains a ready device as online + configured", () => {
    const detail = deviceReadinessDetail(
      makeDevice({ online: true, host_online: true, deploy_state: "configured", readiness: "ready" }),
    );
    expect(detail).toContain("на связи");
    expect(detail).toContain("Хост отвечает");
    expect(detail).toContain("скрипт применил конфиг");
  });

  it("surfaces the failure detail from the endpoint script", () => {
    const detail = deviceReadinessDetail(
      makeDevice({ deploy_state: "failed", deploy_detail: "msiexec exit 1603", readiness: "failed" }),
    );
    expect(detail).toContain("скрипт сообщил об ошибке");
    expect(detail).toContain("msiexec exit 1603");
  });

  it("reads a never-seen device as never registered, not offline", () => {
    const detail = deviceReadinessDetail(makeDevice());
    expect(detail).toContain("ещё не регистрировался");
  });
});

describe("deviceReadinessDetail - stale and AppLocker", () => {
  it("explains a stale device as a pending redeploy, not a fresh one", () => {
    const detail = deviceReadinessDetail(makeDevice({ deploy_state: "stale", readiness: "stale" }));
    expect(detail).toContain("на машине ещё старый");
  });

  it("warns when the desired lockdown could not apply on this edition", () => {
    const detail = deviceReadinessDetail(
      makeDevice({
        applocker_mismatch: true,
        os_edition: "Core",
        os_caption: "Windows 10 Домашняя для одного языка",
      }),
    );
    expect(detail).toContain("AppLocker недоступен");
    expect(detail).toContain("Домашняя");
  });

  it("shows the OS caption plainly when there is no mismatch", () => {
    const detail = deviceReadinessDetail(
      makeDevice({ applocker_mismatch: false, os_caption: "Windows 11 Pro" }),
    );
    expect(detail).toContain("ОС: Windows 11 Pro");
    expect(detail).not.toContain("AppLocker недоступен");
  });
});

describe("AppLockerMismatchBadge", () => {
  it("renders nothing without a confirmed mismatch", () => {
    const { container } = render(<AppLockerMismatchBadge device={makeDevice()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing while the edition is merely unknown, not mismatched", () => {
    const { container } = render(
      <AppLockerMismatchBadge device={makeDevice({ applocker_mismatch: false, os_edition: null })} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a warning badge on a confirmed Home-edition mismatch", () => {
    render(
      <AppLockerMismatchBadge
        device={makeDevice({ applocker_mismatch: true, os_edition: "Core", os_caption: "Windows 10 Home" })}
      />,
    );
    expect(screen.getByText("Home")).toBeInTheDocument();
  });
});
