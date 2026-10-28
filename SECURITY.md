# Security

Report vulnerabilities privately using **Report Vulnerability** in the
[EMQ Security & Trust Center](https://www.emqx.com/en/security-and-trust-center).
Include the commit, startup flags, affected tool and a reproduction with synthetic
credentials. Keep credentials and customer message data out of public issues.

## Trust boundaries

- This is a local stdio process. The MCP client and operating system control who
  can invoke it and read its environment. It is not a multi-user hosted service.
- Mode, endpoint and capability flags are trusted operator configuration.
  Platform and Deployment API credentials are consumed independently. Forward
  only the selected connection's credentials and required secret variables.
- Default tool registration is read-oriented. Ordinary writes, destructive
  operations and integration changes require their documented startup flags.
  Cloud API key scopes and client approval settings provide additional controls;
  tool descriptions are not an authorization system.
- Platform key issuance stores plaintext once-only credentials in private local
  receipts. On POSIX, newly created files/directories use 0600/0700, and directory
  entries are fsynced. Windows requires private ACLs verified by the operator;
  POSIX mode arguments do not enforce those ACLs and directory fsync is unavailable.
  The operator controls `--state-dir` and existing permissions. Protect and retain
  this state across restarts and share it between processes managing the same account.
  Results expose neither file paths nor credentials. Only operators outside the AI
  client may configure credentials; agents must not read private files or copy their
  contents into chat. This guidance cannot sandbox a host client's filesystem tools.
  A per-deployment lock serializes scanning and issuance. Uncertain records or
  temporary results block new IDs for the same endpoint/deployment; unreadable or
  invalid records block issuance conservatively. A crash can leave a stale lock.
  The operator must reconcile Console and private state before resolving these
  records/locks. No remote key update/revocation is exposed.
- Read results can contain client identifiers, IP addresses and message payloads.
  These reach the AI client and its configured provider/storage. `test_rule`
  requests disabled actions but can update rule metrics.
- Integration access authorizes downstream data flows and use of configured
  `EMQXCLOUD_SECRET_*` values. Enable it only for trusted agents. References do
  not isolate a secret from an agent authorized to configure its destination.
- The HTTP client requires HTTPS, verifies certificates, refuses redirects,
  bounds responses/time and never automatically retries writes. Network and
  upstream tenant authorization remain EMQX Cloud responsibilities.
- Exact configured secrets are masked in result/error strings and JSON keys.
  Nonempty local MQTT/integration secrets shorter than eight characters are
  rejected. This is not protection against encoded secrets, arbitrary upstream
  credentials, or an actor that can read the process environment.
- Treat remote names, descriptions and message contents as untrusted data.
  Review the exact account, deployment, operation and payload before approving
  changes, especially paid creation, complete ACL replacement and integrations.

## Development verification

CI runs hermetic API/protocol tests on Linux, macOS and Windows with Python 3.11
and 3.14, builds the package, performs Bandit analysis, and checks resolved Python
dependencies against published advisories with pip-audit. Tests use synthetic
credentials and never modify live EMQX Cloud resources. Passing checks do not
establish compatibility with every deployment version or customer network.
