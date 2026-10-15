# EMQX Cloud MCP

A local [Model Context Protocol](https://modelcontextprotocol.io/) server for
managing EMQX Cloud from Claude Code, Codex, and other stdio MCP clients.
Your agent starts the Python process; it calls EMQX Cloud APIs directly.

Choose one independent connection:

| Mode | Purpose | Required credentials |
| --- | --- | --- |
| `platform` | List projects and deployments, create Dedicated Flex deployments, start deployments | Platform API endpoint, key, and secret |
| `deployment` | Inspect and operate one deployment: clients, subscriptions, metrics, built-in MQTT users and ACLs, banned list, retained messages, publishing, and data integration (connectors, actions, sources, rules) | Deployment API endpoint, key, and secret |

Each mode exposes only its own tools and reads only its own API credentials.
Configure the modes separately; use either or both as needed.

## Install

Requires Python 3.11 or later, Git, an EMQX Cloud account, and a local Codex or
Claude Code installation. The server runs on your computer and requires network
access to your Cloud API endpoints; it does not require an EMQX internal network.

On macOS or Linux:

```sh
git clone https://github.com/emqx/emqx-cloud-mcp-server.git
cd emqx-cloud-mcp-server
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/emqx-cloud-mcp --help
```

On Windows (PowerShell):

```powershell
git clone https://github.com/emqx/emqx-cloud-mcp-server.git
cd emqx-cloud-mcp-server
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\emqx-cloud-mcp.exe --help
```

Use `.venv\Scripts\emqx-cloud-mcp.exe` as the executable in Windows client
settings. JSON paths need escaped backslashes; TOML single-quoted paths do not.

The same server can also run directly with
`.venv/bin/python emqxcloud_mcp.py platform` or
`.venv/bin/python emqxcloud_mcp.py deployment`.

## Configure API access

Start in your overseas account's [EMQX Cloud Console](https://cloud.emqx.com/).
Create a [Platform API key](https://docs.emqx.com/en/cloud/latest/api/api_platform.html)
under **Settings → Platform API Key**, choosing the required functionality and
projects. For broker operations, create a separate
[Deployment API key](https://docs.emqx.com/en/cloud/latest/api/api_deployment.html)
on the target deployment's overview page. Map its **App ID** to
`EMQXCLOUD_DEPLOYMENT_API_KEY` and **App Secret** to
`EMQXCLOUD_DEPLOYMENT_API_SECRET`; these are not MQTT username/password credentials.

Provide the selected mode's variables to the MCP process through your client's
private environment configuration or a secret manager. Keep credentials out of
prompts, shell history, and shared repository files.

| Platform connection | Deployment connection |
| --- | --- |
| `EMQXCLOUD_PLATFORM_ENDPOINT` | `EMQXCLOUD_DEPLOYMENT_ENDPOINT` |
| `EMQXCLOUD_PLATFORM_API_KEY` | `EMQXCLOUD_DEPLOYMENT_API_KEY` |
| `EMQXCLOUD_PLATFORM_API_SECRET` | `EMQXCLOUD_DEPLOYMENT_API_SECRET` |

Copy the API endpoint from the corresponding Console page. Platform endpoints
must end with `/public_api/v1`; Deployment endpoints must end with `/api/v5`.
All endpoints must use HTTPS and must not contain URL credentials, queries, or
fragments. The server never follows redirects or uses one API's credentials for
the other API.

[.env.platform.example](.env.platform.example) and
[.env.deployment.example](.env.deployment.example) show the separate groups. They
are templates, not automatically loaded files. Set the variables before starting
your agent or use the client's per-server environment settings.

For a local macOS/Linux setup, copy one template and restrict access:

```sh
cp .env.platform.example .env.platform
chmod 600 .env.platform
```

Edit `.env.platform` locally with your endpoint, key and secret. Use shell-quoted
values when they contain special characters. Then load this trusted local file
in the same shell that launches your client:

```sh
set -a
. ./.env.platform
set +a
codex  # or claude
```

Use `.env.deployment` instead for a Deployment connection. On Windows, supply
the same variables through your secret manager or private per-server settings.
Do not commit local credential files. Desktop clients launched from a dock or
Start menu may not inherit terminal variables; configure their server environment
explicitly and restart the client after changing it.

## Claude Code

Register only the connection you need. Replace the executable path with the
absolute path to your installed executable. These commands assume the selected
API variables are available in the environment used to launch Claude Code.

Platform connection:

```sh
claude mcp add --transport stdio --scope user emqx-cloud-platform -- /absolute/path/emqx-cloud-mcp-server/.venv/bin/emqx-cloud-mcp platform
```

Deployment connection:

```sh
claude mcp add --transport stdio --scope user emqx-cloud-deployment -- /absolute/path/emqx-cloud-mcp-server/.venv/bin/emqx-cloud-mcp deployment
```

For per-server configuration, add the selected entry to your private Claude Code
MCP settings. For example, a Platform entry can reference existing environment
variables without embedding their values:

```json
{
  "mcpServers": {
    "emqx-cloud-platform": {
      "type": "stdio",
      "command": "/absolute/path/emqx-cloud-mcp-server/.venv/bin/emqx-cloud-mcp",
      "args": ["platform"],
      "env": {
        "EMQXCLOUD_PLATFORM_ENDPOINT": "${EMQXCLOUD_PLATFORM_ENDPOINT}",
        "EMQXCLOUD_PLATFORM_API_KEY": "${EMQXCLOUD_PLATFORM_API_KEY}",
        "EMQXCLOUD_PLATFORM_API_SECRET": "${EMQXCLOUD_PLATFORM_API_SECRET}"
      }
    }
  }
}
```

For a Deployment entry, use `deployment` in `args` and the three
`EMQXCLOUD_DEPLOYMENT_*` variables, plus any `EMQXCLOUD_MQTT_PASSWORD*` and
`EMQXCLOUD_SECRET_*` variables your write tools reference. Check the connection
with `/mcp`.
See [Claude Code's MCP documentation](https://code.claude.com/docs/en/mcp).

## Codex

Add the selected connection to your private `~/.codex/config.toml`. Keep only the
block you need, or use both as independent connections.

Platform connection:

```toml
[mcp_servers.emqx-cloud-platform]
command = "/absolute/path/emqx-cloud-mcp-server/.venv/bin/emqx-cloud-mcp"
args = ["platform"]
env_vars = ["EMQXCLOUD_PLATFORM_ENDPOINT", "EMQXCLOUD_PLATFORM_API_KEY", "EMQXCLOUD_PLATFORM_API_SECRET"]
```

Deployment connection:

```toml
[mcp_servers.emqx-cloud-deployment]
command = "/absolute/path/emqx-cloud-mcp-server/.venv/bin/emqx-cloud-mcp"
args = ["deployment"]
env_vars = ["EMQXCLOUD_DEPLOYMENT_ENDPOINT", "EMQXCLOUD_DEPLOYMENT_API_KEY", "EMQXCLOUD_DEPLOYMENT_API_SECRET", "EMQXCLOUD_MQTT_PASSWORD"]
```

Add any `EMQXCLOUD_SECRET_*` variables referenced by data-integration configs to
`env_vars` as well.

`env_vars` forwards named variables from the environment used to launch Codex;
it does not contain their secret values. Check the connection with `codex mcp
list` and `/mcp`. See [the official Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

## Enable writes

The default is read-only: write tools are not registered. To enable them, add
`--allow-writes` to the selected server's arguments:

```json
"args": ["platform", "--allow-writes"]
```

For Deployment writes, use `["deployment", "--allow-writes"]`. In TOML, use the
same array for `args`. Restrict API keys to the projects, deployments and API
permissions you intend the agent to manage. Authorize paid operations with their
exact project, region and capacity before asking the agent to execute them.

Deployment connections have two further opt-ins, which can be combined:

- `--allow-destructive` registers deletes, client kickout, bans and unbans, and
  also enables the regular write tools.
- `--allow-integrations` registers data-integration create and update, and
  delete when combined with `--allow-destructive`. It is separate because a rule
  can forward every message to an external system.

```json
"args": ["deployment", "--allow-writes", "--allow-integrations"]
```

| Arguments | Deployment tools registered |
| --- | --- |
| (none) | Read |
| `--allow-writes` | Read, Write |
| `--allow-destructive` | Read, Write, Destructive |
| `--allow-integrations` | Read, Integrations |
| `--allow-destructive --allow-integrations` | All |

The Platform connection ignores these two options; it has no destructive or
integration tools.

## Tools

### Platform

| Tool | Access | Behavior |
| --- | --- | --- |
| `list_projects` | Read | Lists visible projects |
| `list_deployments` | Read | Lists visible deployments |
| `get_deployment` | Read | Reads one deployment's actual status |
| `create_deployment` | Write | Creates a paid Dedicated Flex deployment; requires project, cloud, region, connections and TPS; defaults to `v5`, also accepts `v6` |
| `start_deployment` | Write | Starts a stopped deployment; an already-running deployment is a no-op |

Creation and startup return once the API accepts the request. Keep the returned
`deploymentID` and call `get_deployment` at most once per minute until it reports
`running`. An accepted request does not prove readiness or MQTT connectivity.
Creation requires a configured payment method and is rate-limited by EMQX Cloud.

If a write times out, the connection is interrupted, or its result is unknown,
inspect the remote resource before trying again. Writes are never automatically
retried. Read requests have a 30-second overall timeout, bounded retries for
transient HTTP statuses, and a 4 MiB response limit.

### Deployment

| Tool | Access | Behavior |
| --- | --- | --- |
| `list_authentication_users` | Read | One page of built-in MQTT users, filtered by fuzzy user ID or superuser flag; follow the returned pagination metadata |
| `get_authentication_user` | Read | Reads a user without returning its password |
| `get_authorization_rules` | Read | Reads the complete ACL of one username or clientid; `found: false` when none exists |
| `list_clients` | Read | One page of clients (default 20), filtered by fuzzy clientid/username, IP, state or node; `fields` limits the ~60 returned fields |
| `get_client` | Read | One client's connection details and counters |
| `get_client_subscriptions` | Read | Topics one client subscribes to |
| `get_client_messages` | Read | Messages queued for (`mqueue`) or in flight to (`inflight`) one client |
| `get_client_authorization_cache` | Read | One client's cached authorization decisions |
| `list_subscriptions` | Read | One page of subscriptions, filtered by client, topic, topic filter, share group, QoS or node |
| `get_metrics` | Read | Current connection, subscription and message-rate statistics, cluster-wide or per node |
| `list_banned` | Read | One page of banned client IDs, usernames and IP addresses |
| `list_retained_messages` | Read | Retained-message metadata (no payloads), filtered by exact topic or wildcard |
| `list_data_integrations` | Read | Connectors, actions, sources or rules with their status |
| `get_data_integration` | Read | One connector, action or source (`type:name`) or rule (rule id) |
| `get_data_integration_metrics` | Read | Counters and rates of one action, source or rule |
| `test_rule` | Read | Runs a rule's SQL against a sample event without executing its actions; `matched: false` on no match. Test runs count in the rule's metrics |
| `create_authentication_user` | Write | Creates a user using a local password reference |
| `update_authentication_user` | Write | Replaces a user's password and superuser flag |
| `set_authorization_rules` | Write | Creates or replaces one identity's complete ACL |
| `publish_message` | Write | Publishes one message to exercise delivery or rules; an empty retained payload (which deletes the retained message) also requires `--allow-destructive` |
| `clear_client_authorization_cache` | Write | Drops one client's authorization cache so changed ACLs apply immediately |
| `delete_authentication_user` | Destructive | Deletes one built-in MQTT user; its ACL is kept |
| `delete_authorization_rules` | Destructive | Deletes one username's or clientid's complete ACL |
| `kickout_client` | Destructive | Disconnects one client and discards its session; it may reconnect unless banned |
| `ban` | Destructive | Bans a client ID, username, IP, or their regex/CIDR variants |
| `unban` | Destructive | Removes one banned-list entry; refuses EMQX Cloud's default protective entries |
| `create_data_integration` | Integrations | Creates a connector, action, source or rule from its EMQX v5 JSON config |
| `update_data_integration` | Integrations | Replaces the complete config of one connector, action, source or rule |
| `delete_data_integration` | Integrations + Destructive | Deletes one connector, action, source or rule |

When a request fails with a 4xx status, the error includes the API's redacted
`code` and `message` (at most 500 characters) so the agent can correct its
input. Other error-response content is never echoed. Values of local
`EMQXCLOUD_MQTT_PASSWORD*` and `EMQXCLOUD_SECRET_*` variables are redacted from
result strings and JSON keys. Nonempty values shorter than 8 characters are
rejected at Deployment startup. Use strong, unique secrets; the length check is
only a minimum. Redaction covers exact known values, not encoded/derived values
or arbitrary credentials already stored in remote integrations.

Authentication write tools take `password_env`, an environment-variable name,
not a password. Configure `EMQXCLOUD_MQTT_PASSWORD` in the MCP process environment
and use the default reference. For multiple passwords, use names such as
`EMQXCLOUD_MQTT_PASSWORD_DEVICE_A` and explicitly forward them in your client
configuration. Other environment-variable names, including API credentials,
cannot be used as password references. Passwords are never returned by tools.

The default `is_superuser` is `false`; updating a user sets this flag explicitly.
An example username ACL request is:

```json
{
  "identity_type": "username",
  "identity": "device-a",
  "rules": [
    {"permission": "allow", "action": "publish", "topic": "devices/a/#"},
    {"permission": "allow", "action": "subscribe", "topic": "commands/a/#"}
  ]
}
```

Use `identity_type: "clientid"` for a client-ID ACL. `set_authorization_rules`
replaces the **complete** rule set for that exact identity; it does not merge
rules, and an empty list clears that identity's rules. Read existing rules and
authorize the replacement first. The write tool supports `permission`, `action`
and `topic`; advanced ACL fields remain visible on reads and are managed in the
Console or through the Deployment API.

### Data integration

These tools require `--allow-integrations`. A rule such as `SELECT * FROM "#"`
with an external action forwards every message the deployment receives, so
enable them only for agents and API keys trusted with that data flow.

`create_data_integration` and `update_data_integration` take the EMQX v5 JSON
config of a `connector`, `action`, `source` or `rule`. Connectors, actions and
sources are identified as `type:name`; rules by the id returned on creation.
Create in dependency order (connector, then action or source, then rule) and
delete in the reverse order. `delete_data_integration` with `cascade: true` also
removes an action or source from the rules that reference it.

Updates replace the complete config. Read the item first and send the edited
result; server fields such as `name`, `type` and `status` are dropped
automatically. A masked value (`******`) sent back unchanged keeps the stored
secret.

Put secrets in configs as references, never as literal values:

```json
{
  "kind": "connector",
  "config": {
    "type": "http",
    "name": "webhook",
    "url": "https://hooks.example.com",
    "headers": {"authorization": {"$env": "EMQXCLOUD_SECRET_WEBHOOK_TOKEN"}}
  }
}
```

The server replaces each `{"$env": "EMQXCLOUD_SECRET_<NAME>"}` object with that
variable from its own environment. Only `EMQXCLOUD_SECRET_*` names are accepted,
their values are redacted from tool results, and they must be forwarded to the
MCP process like the API credentials.

## Create a deployment, then manage it

1. Use a Platform connection to create the deployment and query its status.
2. Once it is running, create a Deployment API key in the target deployment's
   Console page and copy its endpoint.
3. Configure a separate Deployment connection with that endpoint and key.
4. Use that connection to configure MQTT users, ACLs and data integration, and
   to inspect clients, subscriptions and metrics.

The Platform API does not supply Deployment API credentials. The server does not
guess MQTT addresses or Deployment API endpoints. Each Deployment connection
targets the endpoint configured by its operator; configuring multiple deployments
requires separate connections with their own environment settings.

## First checks and example prompts

After configuring a client, open `/mcp` and confirm the selected server is
connected. A default Platform connection exposes 3 tools; a default Deployment
connection exposes 16. Start with a harmless read:

- "List the projects and deployments available through emqx-cloud-platform."
- "Show the status of deployment `<deployment-id>`."
- "Show current metrics and the first 20 connected clients."
- "Read the username ACL for `device-a` and explain what it permits."

After enabling the required write flag and approving the exact target:

- "Create MQTT user `device-a` with password reference `EMQXCLOUD_MQTT_PASSWORD_DEVICE_A`; keep superuser disabled."
- "Read `device-a`'s current ACL, show the complete replacement for my approval, then apply it."

Read access can expose client details and queued message contents to your AI
client/provider. Keep host-side tool approvals enabled for changes and grant
only the API methods/resources needed. `test_rule` uses POST, requests no action
execution and can increment rule metrics; an API key allowing only GET cannot
use that tool. See [SECURITY.md](SECURITY.md) for the trust boundaries.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Server cannot start / missing variables | Use the absolute executable path; ensure the chosen connection has all three variables in the client process. Templates are not loaded automatically. |
| HTTP 401 | Check the matching API key/secret pair; Deployment uses App ID/App Secret, not MQTT credentials. |
| HTTP 403 | Grant the required API path/method and project scope. Local flags do not override Cloud permissions. |
| HTTP 404 or unsupported tool operation | Check the endpoint suffix and the deployment's EMQX version/API reference. Serverless exposes a smaller API surface. |
| Timeout or TLS error | Check DNS, firewall/VPC access and the endpoint certificate. Keep certificate verification enabled. |
| Write tools missing | Update that connection's startup flags and restart/reconnect the MCP server. |

After updating this checkout, reinstall with the installation command and restart
the MCP connection. Pin a reviewed commit for repeatable installations.

## Notes and limitations

- Deployment creation is limited to non-trial Dedicated Flex deployments; region and capacity availability are validated by the Platform API.
- Deployment tools use the documented EMQX `/api/v5` Deployment API of Dedicated Flex deployments; Platform support for creating `v6` is not a claim of support for every v6 API.
- API availability depends on deployment edition, EMQX version, region and key permissions. This server does not expose every EMQX Cloud feature; Serverless, BYOC and every customer network have not been validated by this repository's tests.
- New deployments require separately configured Deployment API credentials and a network path from the local MCP process to that endpoint.
- Deployment stopping and deletion, TLS, schema registry, message transformation and schema validation, user import, retained-message payload lookup, and bulk-clear operations are not exposed.
- On Dedicated Flex, the EMQX Cloud API gateway rejects identities containing `/` (for example a client ID `site/a`) in URL paths with HTTP 400; such users, clients and ACLs must be managed in the Console. Other deployment types were not tested.
- `--allow-writes` permits credential and complete-ACL changes, `--allow-integrations` permits data flows to external systems, and `--allow-destructive` adds deletes, kickouts and bans. Local client tool-approval settings and the API key's scope must match the customer's intended access.
- Base64 publish payloads must be valid base64 without whitespace; zero-byte retained payloads require `--allow-destructive` after decoding.

## Development checks

```sh
.venv/bin/python -m unittest -v
.venv/bin/python -m py_compile emqxcloud_mcp.py test_emqxcloud_mcp.py
```

Tests use simulated APIs and actual stdio subprocesses, including modern and
legacy MCP handshakes. They do not require live Cloud credentials. Live EMQX
Cloud acceptance and sessions inside Claude Code or Codex are separate checks.

## License

Licensed under [Apache-2.0](LICENSE). See [NOTICE](NOTICE) for Provider attribution.
