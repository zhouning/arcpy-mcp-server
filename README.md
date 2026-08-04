# ArcPy MCP Server

Authenticated Windows MCP service for invoking an allowlisted set of ArcPy operations from a
remote Codex client. The gateway exposes Streamable HTTP MCP at `https://<host-ip>:8765/mcp`,
persists jobs in SQLite WAL mode, and serializes all ArcPy execution through one worker process.

The publishing address is resolved from the host at bootstrap rather than hardcoded, so a DHCP
change does not silently break TLS. Print the address the tooling will use:

```powershell
.\scripts\resolve_ip.ps1
```

## Prerequisites

- Windows 10 or 11 with a LAN/VPN address reachable by the client. A fixed DHCP reservation or
  static address is still recommended, because a mid-session change invalidates the certificate.
- ArcGIS Pro 3.7.1 with the default environment at
  `D:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe`.
- An ArcGIS Pro Advanced/ArcInfo license. Spatial Analyst is required for raster analysis and
  Image Analyst is required for deep-learning inference.
- Python available for the one-time `uv` bootstrap. If `uv.exe` is not on `PATH`, the bootstrap
  installs it into `%LOCALAPPDATA%\ArcPyMCP\bootstrap` without changing the Esri environment.
- Git and network access to install the gateway dependencies on first setup.

The validated host configuration is ArcGIS Pro 3.7.1, ArcInfo, Spatial available, and
ImageAnalyst available. The gateway has its own Python 3.13 environment; no package is installed
into the ArcGIS Pro environment.

## Install

Run from a normal Windows PowerShell in the repository root:

```powershell
.\scripts\bootstrap.ps1
.\scripts\install_scheduled_task.ps1
.\scripts\start.ps1
.\scripts\status.ps1
```

`install_scheduled_task.ps1` requests elevation only when it creates or re-scopes the inbound
Windows Firewall rule. The rule permits TCP `8765` on the Private profile only from the `/24`
containing the host's current address. Re-running the script after the address changes re-points an
existing rule instead of leaving it scoped to the old subnet. It also registers `ArcPyMCPServer` for
the current interactive user at logon, with three one-minute restart attempts.

Do not expose port `8765` directly to the public Internet. Use the trusted LAN or an authenticated
VPN.

## When the host address changes

A new address invalidates three things at once: the certificate SAN, the recorded public base URL,
and the firewall scope. Re-run bootstrap and the installer:

```powershell
.\scripts\stop.ps1
.\scripts\bootstrap.ps1
.\scripts\install_scheduled_task.ps1
.\scripts\start.ps1
.\scripts\status.ps1
```

`bootstrap.ps1` detects the change, rewrites only the `ARCPY_MCP_PUBLIC_BASE_URL` line in
`server.env` (preserving the Bearer token and signing key), and reissues the certificate for the new
address. Re-import the regenerated `ca.crt` on the client afterwards; previously issued artifact
download URLs stop resolving because they embed the old host.

`status.ps1` warns when the configured address no longer matches the host, which is the usual
explanation for a client TLS failure against a service that otherwise looks healthy.

Address resolution order is `ARCPY_MCP_SERVER_IP`, then the interface serving the default route,
then the host in `ARCPY_MCP_PUBLIC_BASE_URL`. Auto-detect picks the default-route interface rather
than the hostname, because a host with VPN, Hyper-V, WSL, or Docker adapters often resolves its own
name to an address no client can route. Set `ARCPY_MCP_SERVER_IP` to pin one interface. Loopback and
link-local values are rejected: they bind successfully but no remote client can reach them.

## macOS Trust

The bootstrap prints the public CA path:

```text
%LOCALAPPDATA%\ArcPyMCP\certs\ca.crt
```

Transfer only `ca.crt` to the macOS client and trust it in the login or system keychain. Never
transfer `ca.key`, `server.key`, `server.env`, or any signed artifact URL. The Codex plugin connects
to a bare IP, so the server certificate carries an IP SAN for the resolved address rather than a DNS
name. That SAN is why an address change requires reissuing the certificate.

The client supplies the Bearer value through `ARCPY_MCP_TOKEN`. The server-side corresponding value
is stored as `ARCPY_MCP_BEARER_TOKEN` in the ACL-restricted `server.env`; it is never committed.

## Secrets and Certificates

Rotate the Bearer Token and artifact signing key, then restart the service:

```powershell
.\scripts\stop.ps1
.\scripts\bootstrap.ps1 -RotateSecrets
.\scripts\start.ps1
```

After rotation, update `ARCPY_MCP_TOKEN` on the macOS client through a secure out-of-band channel.
Previously signed artifact URLs stop working when the signing key changes.

Rotate the local CA and fixed-IP server certificate only when needed:

```powershell
.\scripts\stop.ps1
.\scripts\bootstrap.ps1 -RotateCertificates
.\scripts\start.ps1
```

Import the new `ca.crt` on macOS before reconnecting. Private keys remain under
`%LOCALAPPDATA%\ArcPyMCP\certs` with inheritance disabled for other users.

## Operations

```powershell
.\scripts\start.ps1
.\scripts\status.ps1
.\scripts\stop.ps1
```

The public health endpoint is `https://<host-ip>:8765/healthz`; it exposes only status and
version. `status.ps1` reports the scheduled task, recorded PID, TCP listener, and HTTPS health using
the local CA.

Runtime locations:

| Data | Location |
|---|---|
| Configuration and secrets | `%LOCALAPPDATA%\ArcPyMCP\config\server.env` |
| CA and server certificates | `%LOCALAPPDATA%\ArcPyMCP\certs` |
| Jobs, artifacts, and `state.db` | `%LOCALAPPDATA%\ArcPyMCP\data` |
| Standard output | `%LOCALAPPDATA%\ArcPyMCP\logs\server.stdout.log` |
| Standard error | `%LOCALAPPDATA%\ArcPyMCP\logs\server.stderr.log` |
| PID | `%LOCALAPPDATA%\ArcPyMCP\server.pid` |

Artifacts are retained for 7 days by default. Incomplete uploads are removed after 24 hours. The
service runs cleanup at startup and hourly thereafter; artifacts referenced by active jobs are
protected.

For a consistent backup, stop the service and copy the complete
`%LOCALAPPDATA%\ArcPyMCP\data` directory, including `state.db`, `state.db-wal`, artifacts, and job
workspaces. Restore the directory only while the service is stopped. Certificates and
`server.env` require a separate access-controlled backup if recovery must preserve client trust and
credentials.

## Tool Boundary

The server accepts catalogued vector, raster, map, inspection, and CPU deep-learning operations.
It does not expose arbitrary Python or arbitrary ArcPy tool execution. Deep-learning calls force
`arcpy.env.processorType` to `CPU`; inference can be slow and requires a model compatible with
ArcGIS Pro 3.7.1. `TrainDeepLearningModel`, `SuperResolution`, and model training are deliberately
not exposed.

Clients never send Windows absolute paths. Inputs are uploaded artifacts plus artifact-relative
paths, and outputs are returned as artifact IDs with short-lived signed download URLs.

## Verification

Run the gateway tests from the repository environment:

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m pytest tests -v
git diff --check
```

The real ArcPy tests use the default ArcGIS Pro environment. Map export is skipped unless
`ARCPY_MCP_APRX_TEST_FIXTURE` points to a compatible APRX. Real deep-learning inference is skipped
unless `ARCPY_MCP_DL_TEST_MODEL` points to a compatible DLPK or EMD.

## Uninstall

The default uninstall stops the service and removes the scheduled task while preserving all data,
secrets, and certificates:

```powershell
.\scripts\uninstall_scheduled_task.ps1
```

Use an elevated PowerShell with `-RemoveFirewall` to remove the firewall rule. Permanent deletion
of `%LOCALAPPDATA%\ArcPyMCP` requires the explicit `-RemoveData` switch:

```powershell
.\scripts\uninstall_scheduled_task.ps1 -RemoveFirewall -RemoveData
```
