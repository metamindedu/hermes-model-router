"""Actual Hermes request builders/preflight -> middleware -> SDK wire contract."""
import json
from unittest.mock import patch

import httpx
import pytest
from openai import OpenAI

from test_fast_native_integration import native_plugin, _spawn_through_native_middleware


@pytest.mark.parametrize('provider,api_mode,base_url', [
    ('openai-api', 'chat_completions', 'https://api.openai.com/v1'),
    ('openai-codex', 'codex_responses', 'https://chatgpt.com/backend-api/codex'),
])
@pytest.mark.parametrize('parent_mode,expected_tier', [('priority', 'priority'), (None, None)])
def test_real_builder_preflight_and_sdk_obey_parent_not_stale_overrides(
    native_plugin, provider, api_mode, base_url, parent_mode, expected_tier,
):
    from types import SimpleNamespace
    from agent.subagent_lifecycle import bind_subagent_parent
    from hermes_cli.middleware import apply_llm_request_middleware
    from run_agent import AIAgent

    runtime = native_plugin
    parent = SimpleNamespace(session_id='builder-parent', service_tier=parent_mode, _fast_until=0.0)
    _spawn_through_native_middleware(runtime, parent, child_session='builder-child', subagent_id='builder-native-id')
    captured = []

    def transport(request):
        body = json.loads(request.content)
        captured.append(body)
        if api_mode == 'chat_completions':
            response = {'id': 'chatcmpl-builder-fixture', 'object': 'chat.completion', 'created': 1,
                        'model': 'gpt-6-astra', 'choices': [{'index': 0,
                        'message': {'role': 'assistant', 'content': 'offline'}, 'finish_reason': 'stop'}]}
        else:
            response = {'id': 'resp_builder_fixture', 'object': 'response', 'created_at': 1,
                        'status': 'completed', 'model': 'gpt-6-astra', 'output': []}
        return httpx.Response(200, json=response)

    client = OpenAI(api_key='offline-test-only', base_url=base_url,
                    http_client=httpx.Client(transport=httpx.MockTransport(transport)))
    child = None
    try:
        with (
            patch('model_tools.get_tool_definitions', return_value=[]),
            patch('model_tools.check_toolset_requirements', return_value={}),
            patch('agent.process_bootstrap.OpenAI', return_value=client),
            patch('agent.context_compressor.get_model_context_length', return_value=200_000),
        ):
            child = AIAgent(
                api_key='offline-test-only', base_url=base_url, provider=provider, api_mode=api_mode,
                model='gpt-6-astra', session_id='builder-child', parent_session_id=parent.session_id,
                service_tier=None, request_overrides={'service_tier': 'priority',
                    'extra_body': {'service_tier': 'ultrafast', 'speed': 'fast'}},
                enabled_toolsets=[], max_iterations=2, quiet_mode=True, skip_memory=True,
                skip_context_files=True, skip_background_review=True, platform='subagent', side_agent=True,
            )
        # These are production builders/preflight, not hand-authored SDK kwargs.
        kwargs = child._build_api_kwargs([{'role': 'user', 'content': 'offline builder fixture'}])
        if api_mode == 'codex_responses':
            kwargs = child._get_transport().preflight_kwargs(
                kwargs, allow_stream=False, is_github_responses=False, sanitize_harmony_tokens=True,
            )
        with bind_subagent_parent(child):
            kwargs = apply_llm_request_middleware(
                kwargs, session_id=child.session_id, model=child.model, provider=child.provider,
                base_url=child.base_url, api_mode=child.api_mode, api_call_count=1,
            ).payload
        if api_mode == 'codex_responses':
            # Production repeats preflight immediately before the provider call.
            kwargs = child._get_transport().preflight_kwargs(
                kwargs, allow_stream=False, is_github_responses=False, sanitize_harmony_tokens=True,
            )
            client.responses.create(**kwargs)
        else:
            client.chat.completions.create(**kwargs)
    finally:
        if child is not None:
            child.close()
        client.close()

    assert len(captured) == 1
    assert captured[0].get('service_tier') == expected_tier
    assert 'speed' not in captured[0]
    assert captured[0]['model'] == 'gpt-6-astra'
