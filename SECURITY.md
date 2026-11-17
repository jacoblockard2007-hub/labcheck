# Security policy

## Supported versions

Security fixes are applied to the latest release and to `main`.

| Version | Supported |
| --- | --- |
| 0.1.x | yes |

## Reporting a vulnerability

Please **do not** open a public issue for a security problem. Use GitHub's
private vulnerability reporting:

<https://github.com/jacoblockard2007-hub/labcheck/security/advisories/new>

Include the affected version, your distribution and Python version, the check
involved, and a minimal reproduction. Remove tokens, hostnames and other
secrets from logs and configuration.

You can expect an acknowledgement within a few days. Once a fix is available, a
new release will be published and the advisory disclosed.

## Scope and design notes

- `labcheck` is read-only: checks query the system but do not modify it.
- The certificate check deliberately disables chain and hostname verification.
  It measures expiry, including for private CAs; it is not a validator.
- Some checks need privileged access. `systemctl` talks to the system bus,
  `smartctl` opens block devices, and access to the Docker socket is equivalent
  to root on the host. Run those checks as root only when you intend to.
- Generated reports can contain hostnames, mount points, service and container
  names. Protect report and node_exporter textfile directories accordingly.
- The tool never invokes a shell and never builds commands from configuration
  values.
