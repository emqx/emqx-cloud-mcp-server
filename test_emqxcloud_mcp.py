"""Hermetic API-contract and real stdio protocol tests; no live Cloud credentials."""

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import AsyncMock, patch

import httpx2
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from emqxcloud_mcp import API, APIError, MAX_RESPONSE_BYTES, build_server


def environment(mode):
    prefix = f"EMQXCLOUD_{mode.upper()}"
    suffix = "/public_api/v1" if mode == "platform" else "/api/v5"
    return {f"{prefix}_ENDPOINT": f"https://{mode}.example{suffix}",
            f"{prefix}_API_KEY": f"test-{mode}-key", f"{prefix}_API_SECRET": f"test-{mode}-secret"}


DEPLOYMENT_READ = {"list_authentication_users", "get_authentication_user", "get_authorization_rules", "list_clients",
                   "get_client", "get_client_subscriptions", "get_client_messages", "get_client_authorization_cache",
                   "list_subscriptions", "get_metrics", "list_banned", "list_retained_messages",
                   "list_data_integrations", "get_data_integration", "get_data_integration_metrics", "test_rule"}
DEPLOYMENT_WRITE = {"create_authentication_user", "update_authentication_user", "set_authorization_rules",
                    "publish_message", "clear_client_authorization_cache"}
DEPLOYMENT_DESTRUCTIVE = {"delete_authentication_user", "delete_authorization_rules", "kickout_client", "ban", "unban"}
DEPLOYMENT_INTEGRATIONS = {"create_data_integration", "update_data_integration"}
DEPLOYMENT_INTEGRATIONS_DESTRUCTIVE = {"delete_data_integration"}


def output(result):
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


class APITests(unittest.IsolatedAsyncioTestCase):
    def test_only_selected_credentials_are_required(self):
        for mode in ("platform", "deployment"):
            with self.subTest(mode=mode):
                env = environment(mode)
                other = "deployment" if mode == "platform" else "platform"
                env[f"EMQXCLOUD_{other.upper()}_ENDPOINT"] = "invalid-unused-endpoint"
                api = API(mode, env, http=object())
                self.assertIn(mode + ".example", api.endpoint)
                del env[f"EMQXCLOUD_{mode.upper()}_API_SECRET"]
                with self.assertRaises(ValueError):
                    API(mode, env, http=object())

    def test_invalid_endpoint_never_exposes_its_value(self):
        endpoints = ["http://deployment.example/api/v5", "https://name:password@deployment.example/api/v5",
                     "https://deployment.example/api/v5?secret=value", "https://deployment.example/api/v5#secret",
                     "https://deployment.example/api/v4", "https://deployment.example:0/api/v5",
                     "https://deployment.example/../api/v5", "https://deployment.example/api/v5\n"]
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                env = environment("deployment")
                env["EMQXCLOUD_DEPLOYMENT_ENDPOINT"] = endpoint
                with self.assertRaises(ValueError) as error:
                    API("deployment", env, http=object())
                self.assertNotIn(endpoint, str(error.exception))
                self.assertNotIn("password@", str(error.exception))

    async def test_get_retries_but_write_does_not_and_errors_are_redacted(self):
        for method in ("GET", "POST", "PUT", "DELETE"):
            with self.subTest(method=method):
                calls = []
                def reply(request):
                    calls.append(request)
                    return httpx2.Response(503, json={"code": "test-platform-secret", "password": "private-password"})
                async with httpx2.AsyncClient(transport=httpx2.MockTransport(reply)) as http:
                    api = API("platform", environment("platform"), http)
                    with patch("emqxcloud_mcp.asyncio.sleep", new_callable=AsyncMock):
                        with self.assertRaises(APIError) as error:
                            await api.request(method, "/deployments")
                self.assertEqual(len(calls), 3 if method == "GET" else 1)
                self.assertNotIn("test-platform-secret", str(error.exception))
                self.assertNotIn("private-password", str(error.exception))
                if method != "GET":
                    self.assertIn("unknown", str(error.exception))

    async def test_client_error_detail_is_redacted_and_bounded(self):
        body = {"code": "BAD_REQUEST", "message": "unknown_fields test-platform-secret " + "x" * 2000, "detail": "private-value"}
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(lambda _: httpx2.Response(400, json=body))) as http:
            with self.assertRaises(APIError) as error:
                await API("platform", environment("platform"), http).request("PUT", "/deployments")
        text = str(error.exception)
        self.assertIn("BAD_REQUEST unknown_fields [REDACTED]", text)
        self.assertNotIn("test-platform-secret", text)
        self.assertNotIn("private-value", text)
        self.assertNotIn("outcome may be unknown", text)
        self.assertLess(len(text), 600)

    async def test_redirect_is_not_followed(self):
        calls = []
        def reply(request):
            calls.append(request)
            return httpx2.Response(307, headers={"Location": "https://other.example/steal"})
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(reply), follow_redirects=True) as http:
            with self.assertRaises(APIError):
                await API("platform", environment("platform"), http).request("POST", "/deployments")
        self.assertEqual(len(calls), 1)

    async def test_bounded_responses_and_uncertain_write(self):
        for content in (b"x" * (MAX_RESPONSE_BYTES + 1), b"not-json"):
            async with httpx2.AsyncClient(transport=httpx2.MockTransport(
                lambda _: httpx2.Response(201, content=content))) as http:
                with self.assertRaises(APIError) as error:
                    await API("platform", environment("platform"), http).request("POST", "/deployments")
            self.assertIn("unknown", str(error.exception))

    async def test_network_failure_is_safe_and_not_retried(self):
        calls = []
        def reply(request):
            calls.append(request)
            raise httpx2.ReadTimeout("private-password test-platform-secret", request=request)
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(reply)) as http:
            with self.assertRaises(APIError) as error:
                await API("platform", environment("platform"), http).request("POST", "/deployments")
        self.assertEqual(len(calls), 1)
        self.assertIn("unknown", str(error.exception))
        self.assertNotIn("private-password", str(error.exception))


class ToolTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, mode, name, args, responses, *, writes=True, destructive=True, integrations=True, extra_env=None):
        self.requests = []
        def reply(request):
            self.requests.append(request)
            response = responses[len(self.requests) - 1]
            return httpx2.Response(response[0], json=response[1])
        env = {**environment(mode), **(extra_env or {})}
        server = build_server(mode, writes, env, httpx2.AsyncClient(transport=httpx2.MockTransport(reply)),
                              allow_destructive=destructive, allow_integrations=integrations)
        async with Client(server, raise_exceptions=True) as client:
            return await client.call_tool(name, args)

    async def test_modes_and_access_levels_are_separate(self):
        platform = ({"list_projects", "list_deployments", "get_deployment"}, {"create_deployment", "start_deployment"},
                    set(), set(), set())
        deployment = (DEPLOYMENT_READ, DEPLOYMENT_WRITE, DEPLOYMENT_DESTRUCTIVE, DEPLOYMENT_INTEGRATIONS,
                      DEPLOYMENT_INTEGRATIONS_DESTRUCTIVE)
        expected = {"platform": platform, "deployment": deployment}
        for mode, (read, write, destructive, integration, integration_delete) in expected.items():
            other = "deployment" if mode == "platform" else "platform"
            for writes in (False, True):
                for deletes in (False, True):
                    for integrations in (False, True):
                        env = environment(mode)
                        env[f"EMQXCLOUD_{other.upper()}_ENDPOINT"] = "broken-unused-group"
                        server = build_server(mode, writes, env,
                                              httpx2.AsyncClient(transport=httpx2.MockTransport(lambda _: self.fail("Unexpected API call"))),
                                              allow_destructive=deletes, allow_integrations=integrations)
                        async with Client(server) as client:
                            tools = (await client.list_tools()).tools
                        names = {tool.name for tool in tools}
                        destructive_implies_writes = deletes and mode == "deployment"
                        self.assertEqual(names, read | (write if writes or destructive_implies_writes else set())
                                         | (destructive if deletes else set())
                                         | (integration if integrations else set())
                                         | (integration_delete if integrations and deletes else set()))
                        self.assertFalse(names & set().union(*expected[other]))
                        for tool in tools:
                            self.assertIsNotNone(tool.output_schema)
                            self.assertEqual(tool.annotations.read_only_hint, tool.name in read)
                            if tool.name in destructive | integration_delete:
                                self.assertTrue(tool.annotations.destructive_hint)
                        self.assertNotIn("stop_deployment", names)
                        self.assertNotIn("delete_deployment", names)

    async def test_create_contract_and_identity_survive_without_polling(self):
        args = {"project_id": "project-1", "platform": "aws", "region": "us-east-1",
                "connections": 1000, "tps": 1000, "deployment_name": "test", "deployment_version": "v6"}
        result = await self.call("platform", "create_deployment", args,
                                 [(201, {"deploymentID": "new-id", "status": "pending", "apiSecret": "private-value"})])
        self.assertFalse(result.is_error)
        data = output(result)
        self.assertEqual(data["deploymentID"], "new-id")
        self.assertEqual(data["status"], "pending")
        self.assertTrue(data["accepted"])
        self.assertEqual(len(self.requests), 1)
        request = self.requests[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(str(request.url), "https://platform.example/public_api/v1/deployments")
        self.assertEqual(request.headers["Authorization"], "Basic " + base64.b64encode(b"test-platform-key:test-platform-secret").decode())
        self.assertEqual(json.loads(request.content), {"projectID": "project-1", "platform": "aws", "region": "us-east-1",
                         "connections": 1000, "tps": 1000, "deploymentName": "test", "deploymentType": "dedicatedFlex",
                         "deploymentVersion": "v6"})
        self.assertNotIn("private-value", str(result))

    async def test_create_without_id_reports_unknown_outcome(self):
        result = await self.call("platform", "create_deployment", {"project_id": "p", "platform": "aws", "region": "us-east-1",
                                 "connections": 1000, "tps": 1000}, [(201, {"status": "pending"})])
        self.assertTrue(result.is_error)
        self.assertIn("unknown", result.content[0].text)

    async def test_invalid_inputs_never_reach_api(self):
        for name, args in [
            ("get_deployment", {"deployment_id": ".."}),
            ("create_deployment", {"project_id": "p", "platform": "aws", "region": "us-east-1", "connections": True, "tps": 10}),
            ("create_deployment", {"project_id": "p", "platform": "aws", "region": "us-east-1", "connections": 0, "tps": 10}),
        ]:
            result = await self.call("platform", name, args, [])
            self.assertTrue(result.is_error)
            self.assertEqual(self.requests, [])

    async def test_identity_is_one_escaped_path_segment(self):
        result = await self.call("platform", "get_deployment", {"deployment_id": "a/b +?%"}, [(200, {"deploymentID": "a/b +?%"})])
        self.assertFalse(result.is_error)
        self.assertEqual(self.requests[0].url.raw_path, b"/public_api/v1/deployments/a%2Fb%20%2B%3F%25")

    async def test_read_identity_mismatch_prevents_start(self):
        for tool in ("get_deployment", "start_deployment"):
            result = await self.call("platform", tool, {"deployment_id": "target"},
                                     [(200, {"deploymentID": "other", "status": "stopped"})])
            self.assertTrue(result.is_error)
            self.assertEqual(len(self.requests), 1)
            self.assertEqual(self.requests[0].method, "GET")

    async def test_platform_lists_use_visible_resources_and_strip_credentials(self):
        for tool, path, body, field in (
            ("list_projects", "/projects", [{"projectID": "p", "projectName": "Project", "apiSecret": "private-value"}], "projects"),
            ("list_deployments", "/deployments", [{"deploymentID": "d", "deploymentName": "test-platform-secret", "password": "private-value"}], "deployments"),
        ):
            result = await self.call("platform", tool, {}, [(200, body)])
            self.assertFalse(result.is_error)
            self.assertEqual(len(output(result)[field]), 1)
            self.assertEqual(self.requests[0].url.path, "/public_api/v1" + path)
            self.assertNotIn("private-value", str(result))
            self.assertNotIn("test-platform-secret", str(result))

    async def test_start_checks_state_and_never_claims_running(self):
        for state in ("running", "starting", "stopped"):
            result = await self.call("platform", "start_deployment", {"deployment_id": "target"},
                                     [(200, {"deploymentID": "target", "status": state}), (201, {"operation": "start"})])
            self.assertEqual(len(self.requests), 2 if state == "stopped" else 1)
            self.assertEqual(result.is_error, state == "starting")
            if state == "stopped":
                self.assertTrue(output(result)["accepted"])
                self.assertNotIn("status", output(result))
                self.assertEqual(self.requests[1].method, "POST")
                self.assertEqual(self.requests[1].url.path, "/public_api/v1/deployments/target/start")

    async def test_authentication_password_reference_is_not_exposed(self):
        for name, method in (("create_authentication_user", "POST"), ("update_authentication_user", "PUT")):
            result = await self.call("deployment", name, {"user_id": "device/one", "password_env": "EMQXCLOUD_MQTT_PASSWORD_DEVICE"},
                                     [(201, {"password": "mqtt-password"})],
                                     extra_env={"EMQXCLOUD_MQTT_PASSWORD_DEVICE": "mqtt-password"})
            self.assertFalse(result.is_error)
            self.assertEqual(self.requests[0].method, method)
            payload = json.loads(self.requests[0].content)
            self.assertEqual(payload["password"], "mqtt-password")
            self.assertFalse(payload["is_superuser"])
            self.assertNotIn("mqtt-password", str(result))
            if method == "PUT":
                self.assertTrue(self.requests[0].url.raw_path.endswith(b"/device%2Fone"))

    async def test_password_cannot_reference_api_or_unrelated_environment(self):
        for reference in ("EMQXCLOUD_DEPLOYMENT_API_SECRET", "HOME", "EMQXCLOUD_MQTT_PASSWORD_MISSING"):
            result = await self.call("deployment", "create_authentication_user", {"user_id": "u", "password_env": reference}, [])
            self.assertTrue(result.is_error)
            self.assertEqual(self.requests, [])

    async def test_authentication_reads_strip_passwords_and_keep_pagination(self):
        result = await self.call("deployment", "list_authentication_users", {"page": 2, "limit": 10},
                                 [(200, {"data": [{"user_id": "u", "password": "private-value", "is_superuser": False}],
                                         "meta": {"page": 2, "limit": 10, "count": 11}})])
        self.assertFalse(result.is_error)
        self.assertNotIn("private-value", str(result))
        self.assertEqual(output(result)["meta"]["count"], 11)
        self.assertEqual(output(result)["items"], [{"user_id": "u", "is_superuser": False}])
        self.assertEqual(dict(self.requests[0].url.params), {"page": "2", "limit": "10"})
        await self.call("deployment", "list_authentication_users", {"like_user_id": "dev", "is_superuser": False},
                        [(200, {"data": [], "meta": {}})])
        self.assertEqual(dict(self.requests[0].url.params),
                         {"page": "1", "limit": "100", "like_user_id": "dev", "is_superuser": "false"})
        result = await self.call("deployment", "get_authentication_user", {"user_id": "u"},
                                 [(200, {"user_id": "u", "password": "private-value"})])
        self.assertEqual(output(result), {"user_id": "u"})

    async def test_acl_read_preserves_advanced_fields(self):
        rules = [{"permission": "allow", "action": "publish", "topic": "a/#", "qos": [1], "retain": "false"}]
        result = await self.call("deployment", "get_authorization_rules", {"identity_type": "username", "identity": "u"},
                                 [(200, {"username": "u", "rules": rules})])
        self.assertEqual(output(result)["rules"], rules)

    async def test_long_client_identity_is_preserved(self):
        identity = "device-" + "x" * 600
        result = await self.call("deployment", "get_authorization_rules", {"identity_type": "clientid", "identity": identity},
                                 [(200, {"clientid": identity, "rules": []})])
        self.assertFalse(result.is_error)
        self.assertEqual(output(result)["identity"], identity)
        self.assertTrue(self.requests[0].url.raw_path.endswith(identity.encode()))

    async def test_acl_upsert_uses_exact_identity_and_contract(self):
        rules = [{"permission": "allow", "action": "subscribe", "topic": "devices/#"}]
        for kind, collection in (("username", "users"), ("clientid", "clients")):
            for exists in (True, False):
                result = await self.call("deployment", "set_authorization_rules", {"identity_type": kind, "identity": "a/b", "rules": rules},
                                         [(200, {"rules": []}) if exists else (404, {"code": "NOT_FOUND"}), (204, None)])
                self.assertFalse(result.is_error)
                request = self.requests[1]
                payload = {kind: "a/b", "rules": rules}
                self.assertEqual(request.method, "PUT" if exists else "POST")
                self.assertEqual(request.url.raw_path, f"/api/v5/authorization/sources/built_in_database/rules/{collection}".encode() +
                                 (b"/a%2Fb" if exists else b""))
                self.assertEqual(json.loads(request.content), payload if exists else [payload])

    async def test_acl_failure_or_ambiguous_read_never_writes(self):
        for response in ((403, {"detail": "private-value"}), (200, {})):
            result = await self.call("deployment", "set_authorization_rules", {"identity_type": "username", "identity": "u", "rules": []}, [response])
            self.assertTrue(result.is_error)
            self.assertEqual(len(self.requests), 1)
            self.assertNotIn("private-value", str(result))

    async def test_invalid_acl_has_no_side_effect(self):
        for rule in ({"permission": "invalid", "action": "publish", "topic": "a"},
                     {"permission": "allow", "action": "publish", "topic": "a", "extra": "x"}):
            result = await self.call("deployment", "set_authorization_rules", {"identity_type": "username", "identity": "u", "rules": [rule]}, [])
            self.assertTrue(result.is_error)
            self.assertEqual(self.requests, [])

    async def test_missing_acl_reads_as_not_found(self):
        result = await self.call("deployment", "get_authorization_rules", {"identity_type": "username", "identity": "u"},
                                 [(404, {"code": "NOT_FOUND"})])
        self.assertFalse(result.is_error)
        self.assertEqual(output(result), {"identity_type": "username", "identity": "u", "found": False, "rules": []})

    async def test_destructive_contracts(self):
        for name, args, method, path in (
            ("delete_authentication_user", {"user_id": "a/b"}, "DELETE",
             b"/api/v5/authentication/password_based:built_in_database/users/a%2Fb"),
            ("delete_authorization_rules", {"identity_type": "clientid", "identity": "c"}, "DELETE",
             b"/api/v5/authorization/sources/built_in_database/rules/clients/c"),
            ("delete_data_integration", {"kind": "connector", "id": "http:my"}, "DELETE", b"/api/v5/connectors/http%3Amy"),
            ("kickout_client", {"clientid": "c 1"}, "DELETE", b"/api/v5/clients/c%201"),
            ("ban", {"ban_type": "clientid", "who": "c1", "reason": "abuse"}, "POST", b"/api/v5/banned"),
        ):
            with self.subTest(name=name):
                result = await self.call("deployment", name, args, [(204, None)])
                self.assertFalse(result.is_error)
                self.assertEqual(self.requests[0].method, method)
                self.assertEqual(self.requests[0].url.raw_path, path)
        self.assertEqual(json.loads(self.requests[0].content),
                         {"as": "clientid", "who": "c1", "reason": "abuse", "by": "emqx-cloud-mcp"})
    async def test_unban_checks_entry_and_protects_cloud_defaults(self):
        page_one = {"data": [{"as": "clientid", "who": "other", "reason": "x"}], "meta": {"page": 1, "hasnext": True}}
        mine = {"data": [{"as": "clientid", "who": "c1", "reason": "abuse"}], "meta": {"page": 2, "hasnext": False}}
        result = await self.call("deployment", "unban", {"ban_type": "clientid", "who": "c1"},
                                 [(200, page_one), (200, mine), (204, None)])
        self.assertFalse(result.is_error)
        self.assertEqual([r.method for r in self.requests], ["GET", "GET", "DELETE"])
        self.assertEqual(self.requests[2].url.raw_path, b"/api/v5/banned/clientid/c1")
        default = {"data": [{"as": "username", "who": "+/#", "reason": "EMQX Cloud Default"}], "meta": {"hasnext": False}}
        result = await self.call("deployment", "unban", {"ban_type": "username", "who": "+/#"}, [(200, default)])
        self.assertTrue(result.is_error)
        self.assertIn("default", result.content[0].text)
        self.assertEqual(len(self.requests), 1)
        result = await self.call("deployment", "unban", {"ban_type": "clientid", "who": "none"},
                                 [(200, {"data": [], "meta": {"hasnext": False}})])
        self.assertTrue(result.is_error)
        self.assertEqual(len(self.requests), 1)

    async def test_empty_retained_publish_needs_destructive(self):
        args = {"topic": "t/1", "payload": "", "retain": True}
        result = await self.call("deployment", "publish_message", args, [], destructive=False)
        self.assertTrue(result.is_error)
        self.assertEqual(self.requests, [])
        result = await self.call("deployment", "publish_message", args, [(200, {"id": "m"})])
        self.assertFalse(result.is_error)

    async def test_slash_identity_rejection_is_explained(self):
        def reply(request):
            return httpx2.Response(400, json={"error": "Bad Request"})
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(reply)) as http:
            with self.assertRaises(APIError) as error:
                await API("deployment", environment("deployment"), http).request("GET", "/clients/a%2Fb")
        self.assertIn("'/'", str(error.exception))

    def test_short_local_secrets_are_rejected_without_exposure(self):
        for name in ("EMQXCLOUD_MQTT_PASSWORD", "EMQXCLOUD_MQTT_PASSWORD_DEVICE", "EMQXCLOUD_SECRET_TOKEN"):
            for secret in ("1", "abcdefg"):
                with self.subTest(name=name, length=len(secret)):
                    env = {**environment("deployment"), name: secret}
                    with self.assertRaises(ValueError) as error:
                        API("deployment", env, http=object())
                    self.assertNotIn(secret, str(error.exception))
            API("deployment", {**environment("deployment"), name: ""}, http=object())
        API("platform", {**environment("platform"), "EMQXCLOUD_MQTT_PASSWORD": "1"}, http=object())

    def test_redaction_covers_nested_keys_and_overlapping_values(self):
        env = {**environment("deployment"), "EMQXCLOUD_SECRET_A": "prefix-123",
               "EMQXCLOUD_SECRET_B": "prefix-123-suffix-456"}
        api = API("deployment", env, http=object())
        self.assertEqual(api.redact({"prefix-123-suffix-456": ["prefix-123", {"value": "prefix-123-suffix-456"}]}),
                         {"[REDACTED]": ["[REDACTED]", {"value": "[REDACTED]"}]})

    async def test_base64_publish_validates_before_destructive_check(self):
        for payload in ("\n", " ", "====", "not-base64", "é"):
            result = await self.call("deployment", "publish_message",
                                     {"topic": "t/1", "payload": payload, "payload_encoding": "base64", "retain": True},
                                     [], destructive=False)
            self.assertTrue(result.is_error)
            self.assertEqual(self.requests, [])
        for destructive in (False, True):
            result = await self.call("deployment", "publish_message",
                                     {"topic": "t/1", "payload": "", "payload_encoding": "base64", "retain": True},
                                     [(200, {})] if destructive else [], destructive=destructive)
            self.assertEqual(result.is_error, not destructive)
        result = await self.call("deployment", "publish_message",
                                 {"topic": "t/1", "payload": "aGk=", "payload_encoding": "base64", "retain": True},
                                 [(200, {})], destructive=False)
        self.assertFalse(result.is_error)
        self.assertEqual(json.loads(self.requests[0].content)["payload"], "aGk=")

    async def test_integration_error_redacts_accepted_secret(self):
        result = await self.call("deployment", "create_data_integration",
                                 {"kind": "connector", "config": {"description": {"$env": "EMQXCLOUD_SECRET_TOKEN"}}},
                                 [(400, {"message": "invalid token-value"})],
                                 extra_env={"EMQXCLOUD_SECRET_TOKEN": "token-value"})
        self.assertTrue(result.is_error)
        self.assertNotIn("token-value", str(result))
        self.assertIn("[REDACTED]", str(result))

    async def test_destructive_and_integration_tools_require_opt_in(self):
        for name, args, kwargs in (
            ("delete_authentication_user", {"user_id": "u"}, {"destructive": False}),
            ("create_data_integration", {"kind": "rule", "config": {"sql": "SELECT 1"}}, {"integrations": False}),
            ("delete_data_integration", {"kind": "rule", "id": "r"}, {"destructive": False}),
            ("delete_data_integration", {"kind": "rule", "id": "r"}, {"integrations": False}),
        ):
            result = await self.call("deployment", name, args, [], **kwargs)
            self.assertTrue(result.is_error)
            self.assertEqual(self.requests, [])

    async def test_cascade_applies_only_to_actions_and_sources(self):
        for kind, cascaded in (("action", True), ("source", True), ("rule", False), ("connector", False)):
            await self.call("deployment", "delete_data_integration", {"kind": kind, "id": "x", "cascade": True}, [(204, None)])
            self.assertEqual(dict(self.requests[0].url.params), {"also_delete_dep_actions": "true"} if cascaded else {})

    async def test_integration_secrets_resolve_locally_and_never_return(self):
        config = {"type": "http", "name": "web", "url": "https://hook.example",
                  "headers": {"authorization": {"$env": "EMQXCLOUD_SECRET_HOOK"}}}
        result = await self.call("deployment", "create_data_integration", {"kind": "connector", "config": config},
                                 [(201, {"type": "http", "name": "web", "headers": {"authorization": "token-value"}})],
                                 extra_env={"EMQXCLOUD_SECRET_HOOK": "token-value"})
        self.assertFalse(result.is_error)
        self.assertEqual(self.requests[0].url.path, "/api/v5/connectors")
        self.assertEqual(json.loads(self.requests[0].content)["headers"]["authorization"], "token-value")
        self.assertNotIn("token-value", str(result))
        for name in ("EMQXCLOUD_DEPLOYMENT_API_SECRET", "EMQXCLOUD_MQTT_PASSWORD", "HOME", "EMQXCLOUD_SECRET_MISSING"):
            result = await self.call("deployment", "create_data_integration",
                                     {"kind": "connector", "config": {"password": {"$env": name}}}, [])
            self.assertTrue(result.is_error)
            self.assertEqual(self.requests, [])

    async def test_update_drops_server_fields(self):
        config = {"type": "http", "name": "web", "status": "connected", "sources": [], "url": "https://hook.example", "enable": False}
        result = await self.call("deployment", "update_data_integration", {"kind": "connector", "id": "http:web", "config": config},
                                 [(200, {"url": "https://hook.example"})])
        self.assertFalse(result.is_error)
        self.assertEqual(self.requests[0].method, "PUT")
        self.assertEqual(self.requests[0].url.raw_path, b"/api/v5/connectors/http%3Aweb")
        self.assertEqual(json.loads(self.requests[0].content), {"url": "https://hook.example", "enable": False})

    async def test_rule_test_never_runs_actions_and_reports_no_match(self):
        context = {"event_type": "message_publish", "topic": "t/1", "payload": "{}"}
        result = await self.call("deployment", "test_rule", {"rule_id": "r1", "context": context},
                                 [(412, {"code": "NOT_MATCH"})], writes=False, destructive=False)
        self.assertEqual(output(result), {"rule_id": "r1", "matched": False})
        self.assertEqual(json.loads(self.requests[0].content),
                         {"context": context, "stop_action_after_template_rendering": True})
        result = await self.call("deployment", "test_rule", {"rule_id": "r1", "context": context}, [(200, {"t": 1})])
        self.assertEqual(output(result)["output"], {"t": 1})
        result = await self.call("deployment", "test_rule", {"rule_id": "r1", "context": context}, [(503, {})])
        self.assertTrue(result.is_error)
        self.assertNotIn("unknown", result.content[0].text)

    async def test_reads_normalize_lists_and_filters(self):
        result = await self.call("deployment", "list_clients", {"like_clientid": "dev", "conn_state": "connected"},
                                 [(200, {"data": [{"clientid": "dev-1"}], "meta": {"page": 1, "count": 1}})])
        self.assertEqual(output(result), {"items": [{"clientid": "dev-1"}], "meta": {"page": 1, "count": 1}})
        self.assertEqual(dict(self.requests[0].url.params),
                         {"page": "1", "limit": "20", "like_clientid": "dev", "conn_state": "connected"})
        await self.call("deployment", "list_clients", {"fields": ["clientid", "connected"]}, [(200, {"data": [], "meta": {}})])
        self.assertEqual(self.requests[0].url.params["fields"], "clientid,connected")
        result = await self.call("deployment", "list_data_integrations", {"kind": "action"}, [(200, [{"name": "a"}])])
        self.assertEqual(output(result), {"kind": "action", "items": [{"name": "a"}]})
        self.assertEqual(dict(self.requests[0].url.params), {})
        result = await self.call("deployment", "list_retained_messages", {"topic": "a/#"}, [(200, {"data": [], "meta": {}})])
        self.assertEqual(dict(self.requests[0].url.params), {"page": "1", "limit": "100", "topic": "a/#"})

    async def test_publish_contract(self):
        result = await self.call("deployment", "publish_message", {"topic": "t/1", "payload": "hi", "qos": 1},
                                 [(202, {"reason_code": 16, "message": "no_matching_subscribers"})])
        self.assertFalse(result.is_error)
        self.assertEqual(output(result)["reason_code"], 16)
        self.assertEqual(json.loads(self.requests[0].content),
                         {"topic": "t/1", "payload": "hi", "qos": 1, "retain": False, "payload_encoding": "plain"})


class StdioTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_modes_start_over_real_stdio_for_modern_and_legacy_clients(self):
        script = str(Path(__file__).with_name("emqxcloud_mcp.py"))
        for mode in ("platform", "deployment"):
            for protocol in ("auto", "legacy"):
                with self.subTest(mode=mode, protocol=protocol):
                    params = StdioServerParameters(command=sys.executable, args=["-B", script, mode], env=environment(mode))
                    async with Client(params, mode=protocol, read_timeout_seconds=10) as client:
                        tools = (await client.list_tools()).tools
                    self.assertEqual(len(tools), 3 if mode == "platform" else len(DEPLOYMENT_READ))
                    self.assertTrue(all(tool.annotations.read_only_hint for tool in tools))

    def test_missing_credentials_fail_without_stdout_or_secret_values(self):
        script = str(Path(__file__).with_name("emqxcloud_mcp.py"))
        env = {k: v for k, v in os.environ.items() if not k.startswith("EMQXCLOUD_")}
        env["EMQXCLOUD_PLATFORM_API_SECRET"] = "private-value"
        result = subprocess.run([sys.executable, "-B", script, "platform"], env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("private-value", result.stderr)
        self.assertIn("EMQXCLOUD_PLATFORM_ENDPOINT", result.stderr)


if __name__ == "__main__":
    unittest.main()
