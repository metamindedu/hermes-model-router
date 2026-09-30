"""Preserve pre-existing installed Codex alias handling at both evidence gates."""
import importlib.util
from pathlib import Path
import pytest
from model_router import scoped_agent

spec = importlib.util.spec_from_file_location('runner_identity_test', Path(__file__).resolve().parents[1] / 'lib/run_routed_agent.py')
runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)

@pytest.mark.parametrize('gate', [scoped_agent, runner])
@pytest.mark.parametrize('model,wire', [('gpt-6-astra-900k','gpt-6-astra'),('gpt-6-luna-900k','gpt-6-luna')])
def test_installed_registered_codex_alias_survives(gate, model, wire):
    from agent.model_metadata import is_codex_context_variant, strip_codex_context_variant_suffix
    assert is_codex_context_variant(model)
    assert strip_codex_context_variant_suffix(model)==wire
    route={'provider':'openai-codex','model':model,'api_mode':'codex_responses','request_model':wire,'response_model':wire}
    assert gate._observed_route_matches(route,'openai-codex',model)
    for key,value in [('provider','openai-api'),('model',wire),('api_mode','chat_completions'),('request_model','wrong-model'),('response_model','wrong-model')]:
        assert not gate._observed_route_matches(dict(route,**{key:value}),'openai-codex',model)

@pytest.mark.parametrize('gate', [scoped_agent, runner])
def test_unregistered_suffix_never_becomes_an_alias(gate):
    route={'provider':'openai-codex','model':'unregistered-model-900k','api_mode':'codex_responses','request_model':'unregistered-model','response_model':'unregistered-model'}
    assert not gate._observed_route_matches(route,'openai-codex','unregistered-model-900k')
