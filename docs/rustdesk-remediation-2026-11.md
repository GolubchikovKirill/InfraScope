# RustDesk and InfraScope remediation

## Verified production baseline

RustDesk API is reachable. The console has 201 peers, five accounts, three groups
and one shared-book collection. InfraScope manages 192 endpoints. Observed states
were 164 online, 12 offline and 16 unknown. Deployment states were 46 configured,
10 pending and 136 unknown. Console grouping identified 33 endpoints with numeric
IDs only, ten with alternative IDs and 17 with multiple peer registrations.

Blocking prerequisites: missing WinRM credentials in backend and worker, absent
MSI in the mounted package directory, configured TLS pin differing from the
certificate presented to the worker, and an abandoned queued job from October 28.
186 stored device passwords match the shipped default. No password values should
be included in diagnostic output or documentation.

The command page's loopback connections fail because API, hbbs and hbbr use
separate network namespaces. TCP connections to the server containers succeed.
This does not verify relay sessions or the command protocol itself.

## Ordered implementation and acceptance

1. **Preserve ID intent.** Add observed_rustdesk_id, retain rustdesk_id as the
   operator's installation target. Console sync and endpoint reports update
   observations only. Prefer a registered custom target, then the freshest peer.
   For legacy numeric targets prefer hostname-derived observations if present.
   Connect through the observed ID while configuration edits change the target.
   Migration preserves existing numeric and manually assigned targets. Convert
   the 33 legacy targets only through a reviewed pilot/batch action. Accept when
   sync cannot overwrite a custom target and a mismatched deployment report
   cannot mark the endpoint configured.
2. **Make prerequisites explicit.** Add admin-only push readiness checks for
   WinRM credentials, bootstrap URL/token, server key, installer and checksum.
   Block installation enqueue when checks fail. Keep dry-run independent of MSI.
   Verify TLS trust from a pilot Windows machine, package signature/checksum and
   actual worker access. Then provision the dedicated WinRM account securely.
3. **Make jobs durable.** Add atomic job claim, one-active-job DB constraint,
   transactional outbox/periodic redispatch, heartbeat and phase deadlines.
   Reconcile old queued jobs explicitly before redispatch. Isolate push worker
   capacity and bound parallelism per site. Retry transient transport failures
   with backoff, expose permanent errors and support queued cancellation.
4. **Verify endpoint convergence.** Preflight DNS/WinRM/auth/OS/TLS/download.
   Use one installation implementation for push and GPO, cache the verified MSI,
   skip already converged configurations, back up config and preserve recovery
   access. Confirm effective service ID, version and fresh server registration.
   Success requires the requested configuration revision and verification,
   independent of Windows script exit code or the presence of enc_id alone.
5. **Constrain credentials.** Generate unique passwords for new devices and
   rotate the existing fleet in verified batches. Stage address-book password
   activation after endpoint confirmation. Replace the shared bootstrap token
   for push with short-lived per-job/device credentials. Authenticate reports
   against the intended job/host. Review console passthrough permissions and
   return explicitly permitted fields. Audit changes without secret payloads.
6. **Complete administration UI.** Devices, deployments, users/access and server
   diagnostics are separate screens within Remote Access. Show target/observed
   ID, Windows reachability, RustDesk reachability, verification time and phase
   errors. Add capability-aware API wrappers, full pagination, group/book rights,
   operator permissions, audit filters and visible synchronization failures.
7. **Repair command control.** Verify the installed lejianwen command protocol
   on matching staging images. Test a supported shared network namespace and
   keep administrative control internal. Back up Compose, SQLite and server
   keys. Accept only after command status reads and an actual relay session pass.
8. **Pilot and rollout.** Cover clean Windows, numeric-ID endpoint and already
   configured endpoint. Verify connection, reboot, two sync cycles, worker loss,
   invalid TLS, ID collision and site outage. Expand in small per-site batches
   after the pilot and retain a tested rollback procedure.

## Current implementation

Steps 1 and local checks in step 2 are implemented in the working tree. The UI
shows mismatched IDs and uses observed IDs for connection. Existing targets are
preserved intentionally. The complete remediation is still in progress.

Needed from the operator: a pilot hostname with an alternative administration
path, and secure provisioning of a scoped WinRM account in the server settings.
The operator selected `VNA-TV-1101`, target ID `VNA_TV_1101`. DNS resolves to
`10.10.98.146`; TCP 445 is open, while 5985 and 5986 refuse connections from the
backend. RustDesk currently reports numeric ID `274232180`, online, profile
`client`, deploy state `unknown`. No target-ID conflict was found in the console.
Enable WinRM on this pilot and provision the account before attempting push.
Passwords should be entered through a secure administrative session, not chat.
Production configuration changes, fleet password rotation and client installs
have not been performed as part of this package.
