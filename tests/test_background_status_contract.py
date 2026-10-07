"""The plugin's public status refresh must satisfy native Desktop schema."""
from tui_gateway.contracts.events import StatusUpdatePayload
from test_background_output import setup


def test_background_activity_and_exit_status_are_native_payloads(setup):
    s = setup
    assert s.observer.tick()
    s.session.exited, s.session.exit_code = True, 0
    assert not s.observer.tick()
    assert s.events
    for event, payload in s.events:
        assert event == 'status.update'
        parsed = StatusUpdatePayload.model_validate(payload)
        assert parsed.kind == 'process'
        assert set(payload) == {'kind', 'text'}
        assert isinstance(parsed.text, str)
        assert 'SECRET' not in parsed.text
