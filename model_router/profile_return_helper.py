"""Standalone non-LLM return waiter: private readiness, bounded public locator.

No target launch/control, native parent injection or provider call is performed.
The ordinary parent-owned terminal lifecycle is the only notification transport.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import sys
import threading
import time

# Direct file execution from an installed plugin, not a Core or cwd import hack.
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def run(home, return_id, *, poll_seconds=0.1):
    from model_router.return_channel import ReturnChannel, ChannelError, validate_plan, validate_challenge
    from model_router.profile_return import ProfileResultReader, encode_capsule
    channel = ReturnChannel(home, return_id)  # Existing only; never repair/create.
    stopped = threading.Event()
    old_handlers = {}
    try:
        plan = validate_plan(channel.read('plan'), return_id)
        reader = ProfileResultReader(home, plan['origin'])
        binding = {'request_digest': plan['request_digest'], 'payload_digest': plan['payload_digest']}
        # Early source-job binding is required even for a timeout/cancel locator.
        reader.inspect(plan['job_id'], plan['parent'], **binding)
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGINT, signal.SIGTERM):
                old_handlers[sig] = signal.signal(sig, lambda *_: stopped.set())
        # Windows monotonic clock is shared across these local processes. Both
        # deadlines were frozen by the source BEFORE launch, not re-anchored
        # from a later wall reading or extended across activation.
        until = plan['readiness_monotonic_deadline']

        def cancelled():
            record = channel.read('stop')
            if record is not None:
                if (type(record) is not dict or set(record) != {'schema', 'return_id', 'reason'}
                        or type(record['schema']) is not int or record['schema'] != 1
                        or record['return_id'] != return_id or record['reason'] != 'activation_unknown'):
                    raise ChannelError('invalid_stop')
                return True
            state = channel.read('state')
            expected = {'schema', 'return_id', 'generation', 'job_id', 'owner_id', 'source', 'phase',
                'binding_digest', 'command_digest', 'terminal', 'ready_deadline', 'wait_deadline',
                'launch', 'native', 'process_call', 'error'}
            source_fields = {'task_id', 'turn_id', 'api_request_id', 'tool_call_id', 'root', 'sid'}
            if (type(state) is not dict or set(state) != expected
                    or type(state['schema']) is not int
                    or any(state[k] != plan[k] for k in (
                        'schema', 'return_id', 'generation', 'job_id', 'owner_id', 'binding_digest', 'command_digest'))
                    or state['phase'] not in {'issued', 'launching', 'launched', 'ready', 'consuming', 'submitted', 'invalid'}
                    or state['ready_deadline'] != plan['readiness_expires_at']
                    or state['wait_deadline'] != plan['wait_expires_at']
                    or type(state['source']) is not dict or set(state['source']) != source_fields
                    or state['source']['root'] != plan['parent']):
                raise ChannelError('invalid_state')
            return stopped.is_set() or state.get('phase') == 'invalid'

        def unknown(reason):
            reader.inspect(plan['job_id'], plan['parent'], **binding)
            return reader._capsule(plan['job_id'], 'unknown', reason=reason)

        ready_written = False
        while True:
            if cancelled():
                return encode_capsule(unknown('helper_cancelled'))
            if time.monotonic() >= until or time.time() >= plan['readiness_expires_at']:
                return encode_capsule(unknown('wait_deadline'))
            challenge = channel.read('challenge')
            if challenge is not None:
                validate_challenge(plan, challenge)
                if not ready_written:
                    channel.write_ready(challenge)
                    ready_written = True
                activated = channel.read('activated')
                if activated is not None:
                    if (type(activated) is not dict or set(activated) != {'schema', 'return_id', 'generation', 'job_id'}
                            or type(activated['schema']) is not int or activated['schema'] != 1
                            or any(activated[k] != plan[k] for k in ('return_id', 'generation', 'job_id'))):
                        raise ChannelError('invalid_activation')
                    break
            stopped.wait(min(poll_seconds, max(0.0, until - time.monotonic())))

        class Stop:
            def is_set(self):
                return cancelled()
            def wait(self, timeout):
                return stopped.wait(timeout)
        capsule = reader.wait(plan['job_id'], plan['parent'], **binding,
                              deadline=plan['wait_expires_at'],
                              monotonic_deadline=plan['wait_monotonic_deadline'], stop=Stop())
        return encode_capsule(capsule)
    finally:
        for sig, previous in old_handlers.items():
            signal.signal(sig, previous)
        channel.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Parent-owned Model Router return waiter')
    parser.add_argument('--home', required=True)
    parser.add_argument('--return-id', required=True)
    args = parser.parse_args(argv)
    try:
        output = run(args.home, args.return_id)
    except Exception:
        # Closed, nonsecret failure vocabulary. No paths, plans, key, MAC,
        # source result text, traceback, environment or provider metadata.
        print('{"kind":"model_router.profile_return_refused","schema":1,"error":"return_helper_unavailable"}', flush=True)
        return 2
    print(output, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
