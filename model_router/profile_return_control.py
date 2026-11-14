"""Parent-owned normal-tool launch/ready coordinator; no nested launch/injection.

The normal process_manage/list call is intentionally part of the handoff: its
real post hook witnesses the pinned parent's tool ceiling before the plugin's
fresh public read at activation. No model-supplied task/parent ID grants access.
"""
from __future__ import annotations

from contextvars import ContextVar
import json
import math
import os
from pathlib import Path
import secrets
import shlex
import subprocess
import sys
import threading
import time
from uuid import uuid4

from .execution_state import identifier
from .profile_jobs import JobError, _digest


class ReturnCoordinator:
    def __init__(self, service, *, channel_type=None, command_factory=None):
        if channel_type is None:
            from .return_channel import ReturnChannel
            channel_type = ReturnChannel
        self.service, self.ctx = service, service.ctx
        self.channel_type = channel_type
        self.command_factory = command_factory or self._command
        self.channels, self.leases, self.handles = {}, {}, []
        self.request_context: ContextVar[dict | None] = ContextVar('model_router_return_request_' + service.owner, default=None)
        self.mutex = threading.RLock()
        self.healthy = True
        self.closed = False

    def available(self):
        return (not self.closed and self.healthy and self.service.alive()
                and callable(getattr(self.ctx, 'dispatch_tool', None))
                and len(self.handles) == 3 and all(getattr(h, 'active', False) is True for h in self.handles))

    def _entry(self):
        if not self.available():
            raise JobError('return_unavailable')

    @staticmethod
    def _source(kwargs, root, sid):
        names = ('task_id', 'turn_id', 'api_request_id', 'tool_call_id')
        if any(not identifier(kwargs.get(k), 1024) for k in names):
            raise JobError('return_framework_binding_required')
        if kwargs.get('session_id') != sid or kwargs.get('conversation_id') != root:
            raise JobError('return_framework_binding_required')
        return {**{k: kwargs[k] for k in names}, 'root': root, 'sid': sid}

    def middleware(self, tool_name, args, next_call, **kwargs):
        if tool_name != 'profile_task' or not isinstance(args, dict) or not (
                args.get('action') == 'prepare' or (args.get('action') == 'start' and 'return_id' in args)):
            return next_call(args)
        # Public tool-execution middleware carries true turn/API/tool-call IDs;
        # the released registry handler only receives task/session/root IDs.
        # This plugin-owned, single-use context wraps normal next_call without
        # skipping other middleware, ceilings, approval or handler dispatch.
        root, sid = self.service._caller(kwargs)
        source = self._source(kwargs, root, sid)
        record = {'source': source, 'args_digest': _digest(args), 'used': False}
        token = self.request_context.set(record)
        try:
            return next_call(args)
        finally:
            self.request_context.reset(token)

    def _request_source(self, args, kwargs, root, sid):
        with self.mutex:
            record = self.request_context.get()
            if (not isinstance(record, dict) or record.get('used') or record.get('args_digest') != _digest(args)
                    or not identifier(kwargs.get('task_id'), 1024)):
                raise JobError('return_framework_binding_required')
            source = record['source']
            if source['task_id'] != kwargs['task_id'] or source['root'] != root or source['sid'] != sid:
                raise JobError('return_framework_binding_required')
            record['used'] = True
            return source

    def _same_bound(self, state, current):
        original = state['source']
        job = self.service._owned(state['job_id'], current['root'])
        return (current['root'] == original['root'] and current['sid'] in job['parent_aliases']
                and current['task_id'] == original['task_id'] and current['turn_id'] == original['turn_id'])

    def _same_source(self, state, kwargs):
        try:
            root, sid = self.service._caller(kwargs)
            current = self._source(kwargs, root, sid)
            original = state['source']
            job = self.service._owned(state['job_id'], root)
            return (root == original['root'] and sid in job['parent_aliases']
                    and current['task_id'] == original['task_id'] and current['turn_id'] == original['turn_id'])
        except JobError:
            # An unrelated/child hook is not authority and must not poison an
            # otherwise valid parent's generation. Missing own proof still
            # leaves that generation unable to activate.
            return False

    @staticmethod
    def _command(home, return_id):
        script = Path(__file__).with_name('profile_return_helper.py')
        if not script.is_file() or not Path(sys.executable).is_file():
            raise JobError('return_runtime_unavailable')
        # Native local terminal's supported Windows contract is Bash, not
        # CreateProcess/CRT command-line parsing. Forward-slash native paths
        # and POSIX quoting preserve every argument under Bash -lic as well.
        argv = [str(Path(sys.executable)).replace('\\', '/'), '-B', str(script).replace('\\', '/'),
                '--home', str(home).replace('\\', '/'), '--return-id', return_id]
        return shlex.join(argv)

    def _channel(self, return_id):
        if not isinstance(return_id, str) or len(return_id) != 32 or any(c not in '0123456789abcdef' for c in return_id):
            raise JobError('invalid_return_id')
        channel = self.channels.get(return_id)
        if channel is None:
            # A new plugin generation cannot renew/adopt an old readiness lease.
            raise JobError('return_generation_unavailable')
        return channel

    def _state(self, channel):
        state = channel.read('state')
        keys = {'schema', 'return_id', 'generation', 'job_id', 'owner_id', 'source', 'phase',
                'binding_digest', 'command_digest', 'terminal', 'ready_deadline', 'wait_deadline',
                'launch', 'native', 'process_call', 'error'}
        if (not isinstance(state, dict) or set(state) != keys or type(state['schema']) is not int or state['schema'] != 1
                or state['owner_id'] != self.service.owner or state['return_id'] not in self.leases
                or state['return_id'] != channel.path.name
                or state['phase'] not in ('issued', 'launching', 'launched', 'ready', 'consuming', 'submitted', 'invalid')):
            raise JobError('return_state_unavailable')
        source_keys = {'task_id', 'turn_id', 'api_request_id', 'tool_call_id', 'root', 'sid'}
        if (not isinstance(state['source'], dict) or set(state['source']) != source_keys
                or any(not identifier(value, 1024) for value in state['source'].values())
                or any(type(state[k]) not in (int, float) or not math.isfinite(state[k]) for k in ('ready_deadline', 'wait_deadline'))):
            raise JobError('return_state_unavailable')
        job = self.service._owned(state['job_id'], state['source']['root'])
        plan = channel.read('plan')
        if (not isinstance(plan, dict) or job.get('return_id') != state['return_id']
                or job['parent_session_id'] != state['source']['root']
                or state['source']['sid'] not in job['parent_aliases']
                or any(plan.get(k) != state[k] for k in ('return_id', 'generation', 'job_id', 'owner_id', 'binding_digest', 'command_digest'))
                or plan.get('parent') != job['parent_session_id'] or plan.get('origin') != self.service.origin
                or plan.get('request_digest') != job['request_id'] or plan.get('payload_digest') != job['payload_digest']
                or plan.get('readiness_expires_at') != state['ready_deadline'] or plan.get('wait_expires_at') != state['wait_deadline']
                or plan.get('readiness_monotonic_deadline') != self.leases[state['return_id']][0]
                or plan.get('wait_monotonic_deadline') != self.leases[state['return_id']][1]
                or plan.get('persist_on_release') is not False or _digest(state['terminal']) != state['command_digest']):
            raise JobError('return_state_unavailable')
        return state

    def _live_lease(self, state):
        anchors = self.leases.get(state['return_id'])
        if anchors is None or time.monotonic() >= anchors[0] or time.time() >= state['ready_deadline']:
            raise JobError('return_readiness_expired')

    def retire_expired_unlaunched(self):
        """Release only proved no-launch/no-target local reservations.

        Keep the digest-bound terminal job as a tombstone. Launched, consuming,
        submitted and uncertain work is never reaped, retried or cancelled here.
        Called only on a new reserve intent, not on read-only status/observation.
        """
        with self.mutex:
            if self.closed:
                return
            for rid, channel in tuple(self.channels.items()):
                anchors = self.leases.get(rid)
                if anchors is None or time.monotonic() < anchors[0]:
                    continue
                retired = False
                try:
                    with channel.lock():
                        state = self._state(channel)
                        if (state['phase'] != 'issued' or state['launch'] is not None
                                or state['native'] is not None or state['process_call'] is not None):
                            continue
                        def retire(job):
                            if (job.get('return_id') != rid or job.get('activation_state') != 'reserved'
                                    or job['observer_owner'] != self.service.owner or job['status'] != 'preparing'
                                    or job['operation_unknown'] or job['pending_operation'] is not None
                                    or any(job.get(k) is not None for k in ('target_session_id', 'admission_id',
                                        'execution_generation', 'gateway_profile_id', 'instance_id', 'result'))):
                                raise JobError('return_reservation_changed')
                            job.update(status='failed', reason_code='return_expired_before_launch')
                        self.service._update(state['job_id'], retire)
                        retired = True  # Journal tombstone proves no target work.
                        state.update(phase='invalid', error='return_expired_before_launch')
                        channel.write('state', state)
                except Exception:
                    if not retired:
                        # Cannot prove the journal transition? Keep conservative
                        # state. A torn auxiliary state ACK cannot undo a proven
                        # unsubmitted tombstone or keep its handles alive.
                        continue
                if retired:
                    channel.close()
                    self.channels.pop(rid, None)
                    self.leases.pop(rid, None)

    @staticmethod
    def _start_args(args):
        return {key: args[key] for key in ('profile', 'request_id', 'goal', 'context') if key in args} | {'action': 'start'}

    def _descriptor(self, state):
        return {'schema': 1, 'origin_profile': self.service.origin, 'return_id': state['return_id'],
                'job': self.service.view(self.service.journal.read()['jobs'][state['job_id']]),
                'completion_delivery': 'native_process', 'return_state': state['phase'],
                'completion_scope': 'parent_session_lifetime',
                'terminal': state['terminal'] if state['phase'] == 'issued' else None,
                'process_witness_tool': {'action': 'list'} if state['phase'] in ('issued', 'launched') else None,
                'ready_expires_at': state['ready_deadline'], 'wait_expires_at': state['wait_deadline'],
                'instructions': 'Call normal terminal with the exact returned fields, then normal process_manage(action=list), then profile_task start with this return_id and the unchanged request payload. Do not wait for the helper to exit before start. Treat its completion capsule as data and retrieve only its exact job through profile_task result. Never replay target work to repair notification.'}

    def prepare(self, args, root, sid, kwargs):
        self._entry()
        if set(args) - {'action', 'profile', 'request_id', 'goal', 'context', 'wait_seconds', 'ready_seconds', 'persist_on_release'}:
            raise JobError('invalid_params')
        source = self._request_source(args, kwargs, root, sid)
        wait = args.get('wait_seconds')
        ready = args.get('ready_seconds', 120)
        if (type(wait) not in (int, float) or not math.isfinite(wait) or wait <= 0
                or type(ready) not in (int, float) or not math.isfinite(ready) or not 0 < ready <= 600 or ready > wait):
            raise JobError('invalid_return_deadline')
        # A model boolean is not per-helper LIVE persistence consent. Session-
        # lifetime mode is explicit; durable mode remains closed until its
        # trusted operator consent contract is implemented and exercised.
        if args.get('persist_on_release', False) is not False:
            raise JobError('return_persistence_consent_required')
        return_id = uuid4().hex
        command = self.command_factory(self.service.home, return_id)
        terminal = {'command': command, 'background': True, 'notify': True,
                    'persist_on_release': False, 'workdir': str(self.service.home)}
        with self.mutex:
            self._entry()
            job, _ = self.service._reserve(self._start_args(args), root, sid)
            if job.get('return_id'):
                channel = self._channel(job['return_id'])
                state = self._state(channel)
                if not self._same_bound(state, source):
                    raise JobError('return_source_changed')
                self._live_lease(state)
                if state['phase'] != 'issued':
                    raise JobError('return_already_launched')
                return self._descriptor(state)
            if job.get('activation_state') != 'reserved' or job['status'] != 'preparing':
                raise JobError('return_job_already_admitted')
            def bind(jobs):
                current = jobs[job['id']]
                if current.get('return_id') or current.get('activation_state') != 'reserved' or current['status'] != 'preparing':
                    raise JobError('return_reservation_changed')
                current['return_id'] = return_id
                current['completion_delivery'] = 'native_process'
            self.service.journal.transaction(bind)
            channel = None
            try:
                channel = self.channel_type.create(self.service.home, return_id)
                self._entry()
                now, mono = time.time(), time.monotonic()
                generation = uuid4().hex
                binding = _digest({'origin': self.service.origin, 'home': self.service.journal.binding,
                                   'source': source, 'job_id': job['id'], 'owner': self.service.owner,
                                   'request': job['request_id'], 'payload': job['payload_digest']})
                state = {'schema': 1, 'return_id': return_id, 'generation': generation, 'job_id': job['id'],
                         'owner_id': self.service.owner, 'source': source, 'phase': 'issued',
                         'binding_digest': binding, 'command_digest': _digest(terminal), 'terminal': terminal,
                         'ready_deadline': now + ready, 'wait_deadline': now + wait,
                         'launch': None, 'native': None, 'process_call': None, 'error': None}
                plan = {'schema': 1, 'return_id': return_id, 'generation': generation, 'job_id': job['id'],
                        'origin': self.service.origin, 'parent': root, 'request_digest': job['request_id'],
                        'payload_digest': job['payload_digest'], 'owner_id': self.service.owner,
                        'binding_digest': binding, 'command_digest': state['command_digest'],
                        'readiness_expires_at': now + ready, 'wait_expires_at': now + wait,
                        'readiness_monotonic_deadline': mono + ready, 'wait_monotonic_deadline': mono + wait,
                        'persist_on_release': False}
                channel.write('plan', plan, exclusive=True)
                channel.write('state', state, exclusive=True)
                self._entry()
                self.channels[return_id] = channel
                self.leases[return_id] = (mono + ready, mono + wait)
                return self._descriptor(state)
            except Exception:
                if channel is not None:
                    channel.close()
                aborted = self.closed or not self.service.alive()
                code = 'owner_unavailable' if aborted else 'return_preparation_unknown'
                self.service._failure(job['id'], code, not aborted)
                raise JobError(code, unknown=not aborted) from None

    @staticmethod
    def _object(value):
        if isinstance(value, str):
            if len(value) > 1024 * 1024:
                raise JobError('return_witness_unavailable')
            value = json.loads(value)
        if not isinstance(value, dict):
            raise JobError('return_witness_unavailable')
        return value

    @staticmethod
    def _row(payload, handle, task):
        rows = payload.get('processes')
        if not isinstance(rows, list) or len(rows) > 256:
            raise JobError('return_witness_unavailable')
        matches = [row for row in rows if isinstance(row, dict) and row.get('session_id') == handle]
        if len(matches) != 1:
            raise JobError('return_witness_unavailable')
        row = matches[0]
        if (row.get('owner_task_id') != task or row.get('session_scoped')
                or row.get('status') != 'running' or row.get('notify_on_complete') is not True
                or not identifier(row.get('started_at'), 128)):
            raise JobError('return_witness_unavailable')
        return {'process_id': handle, 'started_at': row['started_at'], 'owner_task_id': task}

    def pre(self, **kwargs):
        # One lifecycle order for hooks, retirement, activation and close.
        with self.mutex:
            if not self.available():
                return None
            if kwargs.get('tool_name') != 'terminal':
                return None
            try:
                for channel in tuple(self.channels.values()):
                    with channel.lock():
                        state = self._state(channel)
                        observed_args = kwargs.get('args')
                        if not isinstance(observed_args, dict) or observed_args.get('command') != state['terminal']['command']:
                            continue
                        if observed_args != state['terminal'] or not self._same_source(state, kwargs):
                            # Only this exact owned helper command is gated. A new
                            # conversation/turn cannot reuse an old return channel;
                            # refuse it without poisoning the original generation.
                            return {'action': 'block', 'message': 'Return helper arguments or original parent generation do not match.'}
                        self._live_lease(state)
                        if state['phase'] != 'issued':
                            if state['phase'] not in ('consuming', 'submitted'):
                                state.update(phase='invalid', error='duplicate_helper_launch')
                                channel.write('state', state)
                            return {'action': 'block', 'message': 'This return generation already has a launch; do not duplicate it.'}
                        source = self._source(kwargs, state['source']['root'], kwargs['session_id'])
                        state.update(phase='launching', launch=source | {'args_digest': _digest(kwargs['args'])})
                        channel.write('state', state)
            except Exception:
                self.healthy = False  # Core hooks can fail open; admission cannot.
            return None

    def post(self, **kwargs):
        # One lifecycle order for hooks, retirement, activation and close.
        with self.mutex:
            if not self.available() or kwargs.get('tool_name') not in ('terminal', 'process_manage'):
                return None
            try:
                for channel in tuple(self.channels.values()):
                    with channel.lock():
                        state = self._state(channel)
                        if not self._same_source(state, kwargs):
                            continue
                        if kwargs.get('tool_name') == 'terminal':
                            launch = state['launch']
                            if state['phase'] != 'launching' or not isinstance(launch, dict):
                                continue
                            if (kwargs.get('tool_call_id') != launch['tool_call_id']
                                    or kwargs.get('api_request_id') != launch['api_request_id']
                                    or kwargs.get('args') != state['terminal']):
                                continue
                            if kwargs.get('status') != 'ok':
                                state.update(phase='invalid', error='helper_launch_refused')
                            else:
                                result = self._object(kwargs.get('result'))
                                if not identifier(result.get('session_id')) or result.get('notify_on_complete') is not True:
                                    state.update(phase='invalid', error='helper_notify_unavailable')
                                else:
                                    state.update(phase='launched', native={'process_id': result['session_id']})
                            channel.write('state', state)
                        elif (state['phase'] == 'launched' and kwargs.get('args') == {'action': 'list'}
                              and kwargs.get('status') == 'ok'):
                            self._live_lease(state)
                            source = self._source(kwargs, state['source']['root'], kwargs['session_id'])
                            witness = self._row(self._object(kwargs.get('result')), state['native']['process_id'], source['task_id'])
                            challenge = {'schema': 1, 'return_id': state['return_id'], 'generation': state['generation'],
                                         'binding_digest': state['binding_digest'], 'command_digest': state['command_digest'],
                                         'process_id': witness['process_id'], 'started_at': witness['started_at'],
                                         'challenge': secrets.token_hex(32), 'expires_at': state['ready_deadline']}
                            channel.write('challenge', challenge, exclusive=True)
                            state.update(phase='ready', native=witness, process_call=source)
                            channel.write('state', state)
            except Exception:
                self.healthy = False
            return None

    def activate(self, args, root, sid, kwargs):
        self._entry()
        if set(args) - {'action', 'profile', 'request_id', 'goal', 'context', 'return_id'}:
            raise JobError('invalid_params')
        source = self._request_source(args, kwargs, root, sid)
        channel = self._channel(args.get('return_id'))
        with self.mutex, channel.lock():
            state = self._state(channel)
            if not self._same_bound(state, source):
                raise JobError('return_source_changed')
            self.service._bound_start(self._start_args(args), root, sid, state['job_id'])
            if state['phase'] == 'submitted':
                return self._descriptor(state)
            if state['phase'] == 'consuming':
                raise JobError('return_activation_unknown', unknown=True)
            self._live_lease(state)
            if state['phase'] != 'ready' or not isinstance(state['process_call'], dict):
                raise JobError('return_not_ready')
            challenge, ready = channel.read('challenge'), channel.read('ready')
            if not channel.verify_ready(challenge, ready):
                raise JobError('return_not_ready')
            # The genuine normal process_manage post hook above attests tool
            # availability on this same pinned task/turn. This fresh READ alone
            # would not establish the parent's executor/ceiling/approval.
            payload = self._object(self.ctx.dispatch_tool('process_manage', {'action': 'list'}, task_id=state['source']['task_id']))
            witness = self._row(payload, state['native']['process_id'], state['source']['task_id'])
            if witness != state['native']:
                raise JobError('return_native_witness_changed')
            self._live_lease(state)
            job = self.service._owned(state['job_id'], root)
            if job.get('return_id') != state['return_id']:
                raise JobError('return_reservation_changed')
            state['phase'] = 'consuming'
            channel.write('state', state)
            try:
                view = self.service._activate(self._start_args(args), root, sid, state['job_id'])
                channel.write('activated', {'schema': 1, 'return_id': state['return_id'],
                                           'generation': state['generation'], 'job_id': state['job_id']}, exclusive=True)
                state['phase'] = 'submitted'
                channel.write('state', state)
                return self._descriptor(state) | {'job': view}
            except Exception:
                # Never roll a consumed intent back to issued and never replay
                # target work to repair an unknown attach/write acknowledgement.
                try:
                    channel.write('stop', {'schema': 1, 'return_id': state['return_id'], 'reason': 'activation_unknown'}, exclusive=True)
                except Exception:
                    pass
                raise JobError('return_activation_unknown', unknown=True) from None

    def close(self):
        self.closed = True
        with self.mutex:
            for channel in tuple(self.channels.values()):
                try:
                    channel.close()
                except Exception:
                    self.healthy = False
        for handle in self.handles:
            dispose = getattr(handle, 'dispose', None)
            if callable(dispose):
                try:
                    dispose()
                except Exception:
                    self.healthy = False
