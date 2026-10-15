# Local EMQX Cloud MCP implementation

## Objective and scope

Deliver one Python stdio MCP server that customers install in Claude Code or
Codex. The server exposes either Platform tools or Deployment tools per process;
customers configure those connections independently.

The implementation consumes existing APIs and changes no Console or Terraform
Provider code. API contract snapshots remain review references and are not
distributed, generated from, or read at runtime.

## Decisions

1. Use the official MCP Python SDK, a single Python module and an installable
   console entry point; the server runs over stdio.
2. Require the selected credential group only. Mode selection and write access
   come from trusted local process arguments rather than model-supplied values.
3. Register read tools by default. `--allow-writes` enables ordinary mutations;
   Deployment `--allow-destructive` also implies those writes. Integration changes
   independently require `--allow-integrations`; integration deletion needs both
   integration and destructive flags.
4. Create only paid Dedicated Flex deployments. Return their identity before
   any later readiness checks; customers query status in separate calls.
5. Use the configured Deployment endpoint for built-in authentication users and
   complete username/clientid ACLs. MQTT passwords come from namespaced local
   environment references, never plaintext tool arguments.
6. Require HTTPS, escape each remote identity, refuse redirects, bound responses
   and total request time, retry only transient GET responses, and report
   uncertain writes without retrying them.
7. Publish English installation instructions, separate credential templates,
   both client configurations, and hermetic API-contract and stdio tests.

## Observable acceptance criteria

- Either mode starts with its own complete credentials while the other group is
  absent or invalid, and exposes only that mode's tools.
- Read-only startup exposes no write tools; write-enabled startup has exactly
  the documented Platform or Deployment tool set.
- Create uses the exact Platform payload, returns `deploymentID` and actual
  status, and issues no long-running poll or retrying POST.
- Start checks the exact deployment identity and state before issuing a POST.
- Deployment calls use Deployment credentials and exact built-in API paths;
  a new ACL uses the documented array POST and an existing ACL uses an item PUT.
- Password references cannot read API credentials or unrelated environment
  variables. Nonempty Deployment-local secret values need at least eight
  characters; exact known secrets are redacted in result/error strings and JSON
  keys, including overlapping values. Encoded values and unknown remote secrets
  are outside this redaction mechanism.
- Both modes complete actual stdio discovery with modern and legacy clients;
  installing the package produces the documented executable.

## Notes and limitations

- Creation supports non-trial Dedicated Flex; the Platform API decides permitted regions and capacities.
- Deployment tools target the published `/api/v5` contract, with basic ACL writes limited to permission/action/topic.
- New-deployment management requires customer-created Deployment API credentials configured separately.
- Deployment mode adds client/subscription/metrics reads, publishing, banned entries and data integration CRUD.
  `--allow-destructive` gates deletes, kickouts, bans and unbans; `--allow-integrations` gates data-integration
  changes separately because rules can forward all messages externally. Deployment stop/delete, TLS, schema registry, message
  transformation and schema validation remain outside this release.
- Simulated API and stdio tests do not establish live Cloud, MQTT, Claude Code or Codex session acceptance.

## Sources

- [EMQX Cloud Terraform Provider](https://github.com/emqx/terraform-provider-emqxcloud): API credential separation, create/start behavior, authentication and ACL request patterns.
- [EMQX Cloud API overview](https://docs.emqx.com/en/cloud/latest/api/api_overview.html)
- [Dedicated Deployment API](https://docs.emqx.com/en/cloud/latest/api/dedicated.html)
- [Official MCP Python SDK](https://py.sdk.modelcontextprotocol.io/)
- [Claude Code MCP setup](https://code.claude.com/docs/en/mcp)
- [Official Codex MCP setup](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
