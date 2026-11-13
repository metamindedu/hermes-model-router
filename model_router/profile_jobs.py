"""Opt-in, Gateway-owned profile jobs. This module never constructs an agent.

The agent tool cannot edit grants or answer approvals. Results are collected
explicitly; plugin UI events are not native completion or parent-wake receipts.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from uuid import uuid4

from .execution_state import JobJournal, WorkspaceClaims, MAX_JOBS, TERMINAL, identifier
from .full_profile_policy import FullProfilePolicy, PolicyWriteUnknown
from .gateway_protocol_client import GatewayProtocolClient, GatewayProtocolError

CLIENT_NAME = 'model-router-profile-job'
MAX_ACTIVE = 4


class JobError(ValueError):
    def __init__(self, code, *, unknown=False):
        self.code, self.unknown = code, unknown
        super().__init__(code)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def _safe_text(value, limit=16384):
    if not isinstance(value, str):
        return ''
    from agent.redact import redact_sensitive_text
    return redact_sensitive_text(value, force=True, redact_url_credentials=True)[:limit]


def _client_factory(**kwargs):
    return GatewayProtocolClient.connect(**kwargs)


class ProfileJobs:
    def __init__(self, ctx, home, *, client_factory=None, alive=None, poll_seconds: float = 2):
        self.ctx, self.home = ctx, Path(home)
        self.handles = []
        self.external_alive = alive
        self.closed = threading.Event()
        self.owner = uuid4().hex
        self.client_factory = client_factory or _client_factory
        self.poll_seconds = max(.02, float(poll_seconds))
        self.mutex = threading.RLock()
        self.clients, self.threads, self.job_locks = {}, {}, {}
        self.policy = FullProfilePolicy(ctx, self.home, alive=self.alive)
        self.origin = self.policy.origin_profile
        self.journal = JobJournal(self.home, self.origin)
        self.workspaces = WorkspaceClaims(self.policy.root, self.journal.binding)

    def alive(self):
        return not self.closed.is_set() and (bool(self.external_alive()) if self.external_alive is not None
                else bool(self.handles) and all(getattr(h, 'active', False) is True for h in self.handles))

    def entry(self):
        from hermes_constants import get_hermes_home
        if not self.alive() or os.path.normcase(str(Path(get_hermes_home()))) != os.path.normcase(str(self.home)):
            raise JobError('owner_unavailable')

    def available(self):
        try:
            if not self.alive():
                return False
            history = self.journal.present()
            try:
                p = self.policy._get()
                granted = bool(p['enabled'] and p['targets'])
            except Exception:
                granted = False
            return bool(history or granted)
        except Exception:
            return False

    def _owned(self, job_id, parent):
        if not identifier(job_id) or not identifier(parent):
            raise JobError('invalid_job')
        job = self.journal.read()['jobs'].get(job_id)
        if not job or parent not in job['parent_aliases']:
            raise JobError('job_not_owned')
        return copy.deepcopy(job)

    def _caller(self, kwargs):
        self.entry()
        sid, root = kwargs.get('session_id'), kwargs.get('conversation_id')
        if not identifier(sid) or not identifier(root):
            raise JobError('bound_parent_required')
        from hermes_cli.plugin_session import session_client, session_surface
        if not session_surface():
            raise JobError('session_context_unavailable')
        client = session_client()
        # Attribution is used only as an extra denial, never to grant authority.
        if isinstance(client, dict) and client.get('name') == CLIENT_NAME:
            raise JobError('recursive_profile_job_denied')
        if sid != root:
            known = self.journal.read()['jobs'].values()
            if not any(job['parent_session_id'] == root and sid in job['parent_aliases'] for job in known):
                raise JobError('unverified_parent_or_subagent')
        return root, sid

    def compacted(self, old_session_id=None, session_id=None, **kwargs):
        try:
            self.entry()
            if not identifier(old_session_id) or not identifier(session_id) or not self.journal.present():
                return None
            def change(jobs):
                for job in jobs.values():
                    if old_session_id in job['parent_aliases'] and session_id not in job['parent_aliases'] and len(job['parent_aliases']) < 64:
                        job['parent_aliases'].append(session_id)
            self.journal.transaction(change)
        except Exception:
            pass
        return None

    def _grant(self, job):
        grant = self.policy.grant(job['target_profile'])
        if grant['cwd'] != job['cwd']:
            raise JobError('grant_stale')
        return grant

    def view(self, job):
        permitted = False
        try:
            self._grant(job)
            permitted = True
        except Exception:
            pass
        status = job['status']
        with self.mutex:
            thread = self.threads.get(job['id'])
        if status not in TERMINAL and (job['observer_owner'] != self.owner or (thread is not None and not thread.is_alive())):
            status = 'unknown'
        pending = copy.deepcopy(job.get('pending_request'))
        mutable = permitted and not job.get('operation_unknown') and not job.get('cancel_requested') and not job.get('pending_operation')
        observed = {'kind': 'unknown', 'role': None, 'profile': None, 'evidence': 'unknown'}
        if job.get('gateway_profile_id') and job.get('admission_id'):
            observed = {'kind': 'profile', 'role': None, 'profile': job['target_profile'], 'evidence': 'runtime_reported'}
        return {'id': job['id'], 'origin_profile': self.origin, 'parent_session_id': job['parent_session_id'],
            'target_profile': job['target_profile'], 'execution_mode': 'gateway', 'status': status,
            'target_session_id': job.get('target_session_id'), 'admission_id': job.get('admission_id'),
            'target_profile_id': job.get('gateway_profile_id') if identifier(job.get('gateway_profile_id')) else None,
            'target_instance_id': job.get('instance_id') if identifier(job.get('instance_id')) else None,
            'target_authority_epoch': job.get('authority_epoch') if type(job.get('authority_epoch')) is int and 0 <= job['authority_epoch'] <= 2**53 - 1 else None,
            'target_cwd': job.get('cwd') if isinstance(job.get('cwd'), str) and 0 < len(job['cwd']) <= 2048 else None,
            'execution_generation': job.get('execution_generation'), 'create_id': job['create_id'], 'submission_id': job['submission_id'],
            'created_at': job['created_at'], 'updated_at': job['updated_at'], 'result_available': job.get('result') is not None,
            'completion_delivery': 'explicit_result', 'reason_code': job.get('reason_code'), 'pending_request': pending,
            'can_steer': mutable and status == 'running',
            # The public RPC supplies no actor/approval/host authority. Do not
            # advertise a privileged response path until that contract exists.
            'can_approve': False, 'can_deny': False, 'can_clarify': False,
            'operator_controls_supported': False, 'observed': observed}

    def _emit(self, job):
        emit = getattr(self.ctx, 'emit_to_session', None)
        if callable(emit):
            try:
                emit(job['parent_session_id'], 'execution.changed', {'schema': 1, 'job_id': job['id']})
            except Exception:
                pass

    def _update(self, job_id, change):
        def edit(jobs):
            job = jobs[job_id]
            before = copy.deepcopy(job)
            change(job)
            if job != before:
                job['updated_at'] = time.time()
            return job
        job = self.journal.transaction(edit)
        self._emit(job)
        return job

    def _failure(self, job_id, code, unknown, *, effect_unknown=False):
        def edit(job):
            if job['status'] not in TERMINAL and job['observer_owner'] == self.owner:
                uncertain = bool(effect_unknown or job.get('operation_unknown') or (unknown and job.get('pending_operation') in ('create', 'submit', 'steer', 'approve', 'clarify')))
                job.update(status='unknown' if unknown else 'failed', reason_code=code,
                           operation_unknown=uncertain, pending_operation=None)
        result = self._update(job_id, edit)
        if result['status'] in TERMINAL:
            self.workspaces.release(result)
        return result

    def _new_client(self, job):
        home = self.policy.root if job['target_profile'] == 'default' else self.policy.root / 'profiles' / job['target_profile']
        client = self.client_factory(profile=job['target_profile'], home=home, root=self.policy.root)
        try:
            desc = client.description
            caps = desc.get('capabilities', [])
            fields = desc.get('session_create', {}).get('parameters', [])
            if (not {'session-client-v1', 'session-transcript-v1'} <= set(caps) or 'client' not in fields
                    or not identifier(client.profile_id) or not identifier(client.instance_id)):
                raise JobError('unsupported_gateway')
            return client
        except Exception:
            client.close()
            raise

    def _remember_identity(self, job_id, client):
        return self._update(job_id, lambda job: job.update(gateway_profile_id=client.profile_id,
                            instance_id=client.instance_id, authority_epoch=client.authority_epoch))

    def _check_snapshot(self, snapshot, job):
        if (not isinstance(snapshot, dict) or snapshot.get('session_id') != job['target_session_id']
                or snapshot.get('stored_session_id', job['target_session_id']) != job['target_session_id']):
            raise JobError('session_identity_mismatch', unknown=True)
        return snapshot

    def _receipt(self, client, job, receipt):
        if (not isinstance(receipt, dict) or not identifier(receipt.get('admission_id'))
                or receipt.get('ref') != {'profile_id': client.profile_id, 'session_id': job['target_session_id']}
                or receipt.get('authority_epoch') != client.authority_epoch or type(receipt.get('authority_epoch')) is not int
                or receipt.get('status') not in ('queued', 'started', 'unknown', 'terminal')
                or type(receipt.get('sequence')) is not int or receipt['sequence'] < 0):
            raise JobError('receipt_identity_mismatch', unknown=True)
        if job.get('admission_id') and receipt['admission_id'] != job['admission_id']:
            raise JobError('receipt_identity_mismatch', unknown=True)
        generation = receipt.get('execution_generation')
        if (generation is not None and (type(generation) is not int or generation < 0)) or (receipt['status'] == 'started' and generation is None):
            raise JobError('receipt_generation_mismatch', unknown=True)
        return receipt

    def _prompt(self, snapshot, generation):
        prompts = snapshot.get('prompts', [])
        if not isinstance(prompts, list) or len(prompts) > 128:
            raise JobError('invalid_prompt_snapshot', unknown=True)
        candidates = [p for p in prompts if isinstance(p, dict) and p.get('execution_generation') == generation
                      and p.get('kind') in ('approval', 'clarify') and identifier(p.get('prompt_id'))]
        if not candidates:
            return None
        p = candidates[0]
        if p['kind'] == 'approval':
            text = '\n'.join(s for s in (p.get('description'), p.get('command')) if isinstance(s, str))
            choices = [c for c in p.get('choices', []) if c in ('once', 'deny')]
        else:
            question = p.get('question')
            text = question if isinstance(question, str) else ''
            options = p.get('choices', [])
            if isinstance(options, list):
                text += '\n' + '\n'.join(str(c)[:512] for c in options[:32] if isinstance(c, str))
            choices = []
        redacted = _safe_text(text, 1024 * 1024)
        if p['kind'] == 'approval':
            command = p.get('command')
            reviewable = (isinstance(command, str) and bool(command.strip())
                          and p.get('edit') is None and len(redacted) <= 8192)
            if not reviewable:
                choices = [choice for choice in choices if choice == 'deny']
                redacted = '[허용 차단: 전체 명령 또는 지원되는 작업 내용을 표시할 수 없습니다. 기본 승인 화면에서 확인하세요.]\n' + redacted
        return {'kind': p['kind'], 'prompt_id': p['prompt_id'], 'execution_generation': generation,
                'text': redacted[:8192], 'choices': choices}

    def _commit_receipt(self, job_id, client, receipt, snapshot=None):
        original = self.journal.read()['jobs'][job_id]
        self._receipt(client, original, receipt)
        status = {'queued': 'queued', 'started': 'running', 'unknown': 'unknown'}.get(receipt['status'])
        result = None
        prompt = None
        if receipt['status'] == 'terminal':
            outcome = receipt.get('outcome')
            status = ('completed' if outcome == 'completed' else 'cancelled' if outcome in ('cancelled', 'interrupted')
                      else 'failed' if outcome in ('failed', 'error') else 'unknown')
            raw = receipt.get('result')
            if isinstance(raw, dict) and isinstance(raw.get('final_response'), str):
                text = raw['final_response']
                result = {'text': _safe_text(text), 'truncated': len(text) > 16384}
        elif receipt['status'] == 'started' and snapshot is not None:
            self._check_snapshot(snapshot, original)
            if snapshot.get('execution_generation') != receipt['execution_generation']:
                raise JobError('snapshot_generation_mismatch', unknown=True)
            prompt = self._prompt(snapshot, receipt['execution_generation'])
            if prompt:
                status = 'approval_wait' if prompt['kind'] == 'approval' else 'clarify_wait'
        def edit(job):
            if job['target_session_id'] != original['target_session_id'] or (job.get('admission_id') and job['admission_id'] != receipt['admission_id']):
                raise JobError('receipt_identity_mismatch', unknown=True)
            if job['status'] in TERMINAL and receipt['status'] != 'terminal':
                return
            if job['observer_owner'] != self.owner and job.get('admission_id'):
                return
            if job.get('authority_epoch', 0) > receipt['authority_epoch']:
                return
            next_status = 'stop_requested' if job.get('cancel_requested') and receipt['status'] != 'terminal' else status
            job.update(admission_id=receipt['admission_id'], execution_generation=receipt['execution_generation'],
                       gateway_profile_id=client.profile_id, instance_id=client.instance_id,
                       authority_epoch=receipt['authority_epoch'], status=next_status, pending_request=prompt,
                       reason_code='gateway_outcome_unknown' if status == 'unknown' else None)
            if job.get('pending_operation') == 'submit':
                job['pending_operation'] = None  # exact admission ACK, not a new submission
            if receipt['status'] == 'terminal':
                if result is not None or job.get('result') is None:
                    job['result'] = result
                job['pending_operation'] = None
        updated = self._update(job_id, edit)
        if receipt['status'] == 'terminal':
            self.workspaces.release(updated)
        return updated

    def _observe(self, job_id, client):
        job = self.journal.read()['jobs'][job_id]
        if not job.get('admission_id'):
            raise JobError('admission_identity_unknown', unknown=True)
        receipt = self._receipt(client, job, client.call('prompt.receipt', {
            'session_id': job['target_session_id'], 'admission_id': job['admission_id'], 'include_result': True}))
        snapshot = None
        if receipt['status'] == 'started':
            snapshot = client.call('session.resume', {'session_id': job['target_session_id'], 'omit_messages': True})
        # Snapshot/receipt, not replayed prose or the presence/absence of events, is truth.
        client.drain_events()
        return self._commit_receipt(job_id, client, receipt, snapshot), receipt

    def _cancel_before_submit(self, job_id):
        job = self._update(job_id, lambda j: j.update(status='cancelled', reason_code='cancelled_before_submit', pending_operation=None))
        self.workspaces.release(job)

    def _work(self, job_id, text):
        client = None
        remote_attempted = False
        admitted = False
        try:
            job = self.journal.read()['jobs'][job_id]
            if job['cancel_requested']:
                self._cancel_before_submit(job_id)
                return
            if not self.alive():
                raise JobError('owner_unavailable')
            self._grant(job)
            self.workspaces.claim(job)
            client = self._new_client(job)
            with self.mutex:
                self.clients[job_id] = client
            self._remember_identity(job_id, client)
            with self.policy.guard(job['target_profile']) as grant:
                if grant['cwd'] != job['cwd']:
                    raise JobError('grant_stale')
                self._update(job_id, lambda j: j.update(status='creating', pending_operation='create'))
                remote_attempted = True
                created = client.call('session.create', {'request_id': job['create_id'], 'source': 'tool', 'cwd': job['cwd'],
                    'client': {'name': CLIENT_NAME, 'version': '0.9.0'}})
            sid = created.get('session_id')
            if not identifier(sid) or created.get('stored_session_id', sid) != sid:
                raise JobError('session_identity_mismatch', unknown=True)
            self._update(job_id, lambda j: j.update(target_session_id=sid, pending_operation=None))
            with self.job_locks[job_id]:
                job = self.journal.read()['jobs'][job_id]
                if job['cancel_requested']:
                    self._cancel_before_submit(job_id)
                    return
                with self.policy.guard(job['target_profile']) as grant:
                    if grant['cwd'] != job['cwd']:
                        raise JobError('grant_stale')
                    self._update(job_id, lambda j: j.update(status='submitting', pending_operation='submit'))
                    receipt = client.call('prompt.submit', {'session_id': sid, 'submission_id': job['submission_id'], 'text': text})
                self._receipt(client, job, receipt)
                admitted = True
                self._commit_receipt(job_id, client, receipt)
            text = ''
            self._watch_loop(job_id, client)
        except Exception as exc:
            unknown = bool(admitted or getattr(exc, 'ambiguous', False) or getattr(exc, 'unknown', False)
                or (remote_attempted and not isinstance(exc, (JobError, GatewayProtocolError, PermissionError))))
            code = getattr(exc, 'code', None)
            if code is None and isinstance(exc, PermissionError):
                code = 'grant_denied'
            code = code if isinstance(code, str) and code.replace('_', '').isalnum() and len(code) <= 64 else 'job_operation_failed'
            try:
                self._failure(job_id, code, unknown)
            except Exception:
                pass
        finally:
            if client is not None:
                client.close()
            with self.mutex:
                if self.clients.get(job_id) is client:
                    self.clients.pop(job_id, None)

    def _watch_loop(self, job_id, client):
        while self.alive():
            with self.job_locks[job_id]:
                if self.journal.read()['jobs'][job_id]['observer_owner'] != self.owner:
                    return  # another explicit viewer owns observation, never execute anew
                job, receipt = self._observe(job_id, client)
                if receipt['status'] in ('terminal', 'unknown'):
                    return
                if job.get('cancel_requested') and job.get('pending_operation') != 'cancel':
                    self._update(job_id, lambda j: j.update(pending_operation='cancel'))
                    client.call('prompt.cancel', {'session_id': job['target_session_id'], 'admission_id': job['admission_id']})
                    # Re-read the terminal's stored visible result; a cancel ACK is not that result.
                    _, receipt = self._observe(job_id, client)
                    if receipt['status'] in ('terminal', 'unknown'):
                        return
            if self.closed.wait(self.poll_seconds):
                break
        self._failure(job_id, 'observer_detached', True)

    def _watch_existing(self, job_id, client):
        try:
            self._watch_loop(job_id, client)
        except Exception:
            try:
                self._failure(job_id, 'observer_connection_lost', True)
            except Exception:
                pass
        finally:
            client.close()
            with self.mutex:
                if self.clients.get(job_id) is client:
                    self.clients.pop(job_id, None)

    def _adopt_viewer(self, job_id, client):
        # Explicit refresh can adopt ONLY an existing exact admission. This
        # thread has no path to session.create or prompt.submit.
        if not self.alive():
            return False
        self._update(job_id, lambda j: j.update(observer_owner=self.owner))
        thread = threading.Thread(target=self._watch_existing, args=(job_id, client),
            name='model-router-viewer-' + job_id[:8], daemon=True)
        with self.mutex:
            self.clients[job_id] = client
            self.threads[job_id] = thread
        thread.start()
        return True

    def start(self, args, root, sid):
        if set(args) - {'action', 'profile', 'request_id', 'goal', 'context'}:
            raise JobError('invalid_params')
        request, target, goal = args.get('request_id'), args.get('profile'), args.get('goal')
        context = args.get('context', '')
        if (not identifier(request, 128) or not isinstance(goal, str) or not goal.strip() or len(goal) > 16000
                or not isinstance(context, str) or len(context) > 32000):
            raise JobError('invalid_params')
        request_key = _digest([root, request])
        def matches(job):
            return job['payload_digest'] == _digest([root, target, job['cwd'], goal, context])
        for job in self.journal.read()['jobs'].values():
            if job['parent_session_id'] == root and job['request_id'] == request_key:
                if not matches(job):
                    raise JobError('request_id_conflict')
                return self.view(job)
        with self.policy.guard(target) as grant:
            def reserve(jobs):
                for existing in jobs.values():
                    if existing['parent_session_id'] == root and existing['request_id'] == request_key:
                        if not matches(existing):
                            raise JobError('request_id_conflict')
                        return existing, False
                if len(jobs) >= MAX_JOBS or sum(j['status'] not in TERMINAL for j in jobs.values()) >= MAX_ACTIVE:
                    raise JobError('job_capacity')
                now, jid = time.time(), uuid4().hex
                job = {'id': jid, 'origin_profile': self.origin, 'parent_session_id': root, 'parent_aliases': list(dict.fromkeys([root, sid])),
                    'target_profile': target, 'cwd': grant['cwd'], 'request_id': request_key,
                    'payload_digest': _digest([root, target, grant['cwd'], goal, context]), 'grant_revision': grant['revision'],
                    'create_id': uuid4().hex, 'submission_id': uuid4().hex, 'observer_owner': self.owner,
                    'status': 'preparing', 'reason_code': None, 'created_at': now, 'updated_at': now, 'target_session_id': None,
                    'admission_id': None, 'execution_generation': None, 'gateway_profile_id': None, 'instance_id': None, 'authority_epoch': 0,
                    'result': None, 'pending_request': None, 'operation_unknown': False, 'pending_operation': None,
                    'completion_delivery': 'explicit_result', 'cancel_requested': False}
                jobs[jid] = job
                return job, True
            job, created = self.journal.transaction(reserve)
        if created:
            text = goal if not context else goal + '\n\n' + context
            thread = threading.Thread(target=self._work, args=(job['id'], text), name='model-router-viewer-' + job['id'][:8], daemon=True)
            with self.mutex:
                self.job_locks[job['id']] = threading.RLock()
                self.threads[job['id']] = thread
            try:
                thread.start()
            except Exception:
                self._failure(job['id'], 'observer_unavailable', False)
                raise JobError('observer_unavailable') from None
        return self.view(self.journal.read()['jobs'][job['id']])

    def _existing_client(self, job):
        with self.mutex:
            client = self.clients.get(job['id'])
        if client is not None:
            return client, False
        client = self._new_client(job)
        try:
            if client.profile_id != job['gateway_profile_id'] or client.authority_epoch < job['authority_epoch']:
                raise JobError('gateway_identity_mismatch', unknown=True)
            snapshot = client.call('session.resume', {'session_id': job['target_session_id'], 'omit_messages': True})
            self._check_snapshot(snapshot, job)
            return client, True
        except Exception:
            client.close()
            raise

    def control(self, parent, args, *, human=False):
        jid, operation = args.get('job_id'), args.get('operation')
        job = self._owned(jid, parent)
        fields = {'refresh': set(), 'stop': set(), 'steer': {'text'}, 'approve': {'prompt_id', 'choice'}, 'clarify': {'prompt_id', 'answer'}}
        if not isinstance(operation, str) or operation not in fields or set(args) != {'job_id', 'operation'} | fields[operation]:
            raise JobError('invalid_params')
        # No boolean can turn a worker/CLI identity into the viewer's authority.
        # Even internal callers must use the native session response surface.
        if operation in ('approve', 'clarify'):
            raise JobError('operator_authority_unavailable')
        if operation == 'steer' and (not isinstance(args['text'], str) or not args['text'].strip() or len(args['text']) > 16000):
            raise JobError('invalid_params')
        if operation == 'stop':
            if job['status'] in TERMINAL:
                return self.view(job)
            job = self._update(jid, lambda j: j.update(cancel_requested=True, status='stop_requested'))
        if not job.get('target_session_id') or not job.get('admission_id'):
            if operation == 'stop':
                return self.view(job)
            raise JobError('admission_identity_unknown', unknown=True)
        with self.mutex:
            lock = self.job_locks.setdefault(jid, threading.RLock())
        client, temporary, sent, action_returned, receipt = None, False, False, False, None
        def keep_viewing(observed, current_receipt):
            nonlocal temporary
            if temporary and current_receipt['status'] not in ('terminal', 'unknown'):
                if self._adopt_viewer(jid, client):
                    temporary = False
                    observed = self.journal.read()['jobs'][jid]
            return self.view(observed)
        try:
            with lock:
                self._update(jid, lambda j: j.update(observer_owner=self.owner))
                client, temporary = self._existing_client(job)
                job, receipt = self._observe(jid, client)
                if operation == 'refresh':
                    return keep_viewing(job, receipt)
                if operation == 'stop':
                    self._update(jid, lambda j: j.update(pending_operation='cancel'))
                    client.call('prompt.cancel', {'session_id': job['target_session_id'], 'admission_id': job['admission_id']})
                    stopped, current_receipt = self._observe(jid, client)
                    return keep_viewing(stopped, current_receipt)
                if receipt['status'] != 'started' or job.get('operation_unknown') or job.get('cancel_requested') or job.get('pending_operation'):
                    raise JobError('job_not_mutable')
                def send():
                    nonlocal sent, action_returned
                    self._update(jid, lambda j: j.update(pending_operation=operation))
                    sent = True
                    client.call('session.steer', {'session_id': job['target_session_id'],
                                                'execution_generation': receipt['execution_generation'], 'text': args['text']})
                    action_returned = True
                    self._update(jid, lambda j: j.update(pending_operation=None))
                with self.policy.guard(job['target_profile']) as grant:
                    if grant['cwd'] != job['cwd']:
                        raise JobError('grant_stale')
                    send()
                observed, current_receipt = self._observe(jid, client)
                return keep_viewing(observed, current_receipt)
        except Exception as exc:
            unknown = bool(operation == 'stop' or action_returned or getattr(exc, 'ambiguous', False) or getattr(exc, 'unknown', False) or (sent and not isinstance(exc, (JobError, GatewayProtocolError))))
            if sent and unknown:
                self._failure(jid, 'control_outcome_unknown', True, effect_unknown=True)
            elif sent:
                self._update(jid, lambda j: j.update(pending_operation=None))
            if not unknown and temporary and receipt is not None and client is not None:
                keep_viewing(self.journal.read()['jobs'][jid], receipt)
            elif not sent:
                self._failure(jid, 'observer_connection_lost', True)
            raise JobError('control_outcome_unknown' if unknown else 'control_refused', unknown=unknown) from None
        finally:
            if temporary and client is not None:
                client.close()

    def result(self, parent, job_id):
        job = self._owned(job_id, parent)
        return {'schema': 1, 'origin_profile': self.origin, 'job': self.view(job), 'result': copy.deepcopy(job.get('result'))}

    def listing(self, parent):
        if not identifier(parent):
            raise JobError('bound_parent_required')
        jobs = self.journal.read()['jobs'].values()
        return {'schema': 1, 'origin_profile': self.origin, 'parent_session_id': parent,
                'completion_delivery': 'explicit_result', 'jobs': [self.view(j) for j in jobs if parent in j['parent_aliases']]}

    def _response_error(self, code, unknown=False):
        return {'schema': 1, 'origin_profile': self.origin, 'status': 'unknown' if unknown else 'refused',
                'error': code, 'no_effect': not unknown, 'completion_delivery': 'explicit_result'}

    def rpc(self, operation, params, *, session_id=None, **kwargs):
        try:
            self.entry()
            if (not isinstance(params, dict) or ('profile' in params and params['profile'] != self.origin)
                    or ('session_id' in params and params['session_id'] != session_id)):
                raise JobError('owner_mismatch')
            body = {k: v for k, v in params.items() if k not in ('session_id', 'profile')}
            if operation == 'describe':
                if body:
                    raise JobError('invalid_params')
                reply = self.policy.describe()
                reply.update(operator_controls_supported=False,
                             grant_management={'transport': 'host_cli', 'rpc_writable': False},
                             response_management={'transport': 'native_session', 'rpc_writable': False})
                return reply
            if operation == 'configure':
                # session:control is not host-wide grant administration.
                raise JobError('operator_authority_unavailable')
            if not identifier(session_id):
                raise JobError('bound_parent_required')
            if operation == 'list' and not body:
                return self.listing(session_id)
            if operation == 'control':
                if body.get('operation') in ('approve', 'clarify'):
                    # Never manufacture approval/respond authority from a UI
                    # endpoint name, checkbox or caller-supplied boolean.
                    raise JobError('operator_authority_unavailable')
                return {'schema': 1, 'origin_profile': self.origin, 'job': self.control(session_id, body)}
            if operation == 'result' and set(body) == {'job_id'}:
                return self.result(session_id, body['job_id'])
            raise JobError('invalid_params')
        except PolicyWriteUnknown:
            return self._response_error('policy_write_unknown', True)
        except JobError as exc:
            return self._response_error(exc.code, exc.unknown)
        except (ValueError, PermissionError):
            return self._response_error('invalid_or_denied')
        except Exception:
            return self._response_error('operation_unavailable', True)

    def tool(self, args, **kwargs):
        try:
            root, sid = self._caller(kwargs)
            if not isinstance(args, dict):
                raise JobError('invalid_params')
            action = args.get('action')
            if action == 'start':
                reply = {'schema': 1, 'origin_profile': self.origin, 'job': self.start(args, root, sid), 'completion_delivery': 'explicit_result'}
            elif action == 'status' and set(args) == {'action'}:
                reply = self.listing(root)
                try:
                    p = self.policy._get()
                    reply['allowed_profiles'] = p['targets'] if p['enabled'] else []
                except Exception:
                    reply['allowed_profiles'] = []
            elif action == 'result' and set(args) == {'action', 'job_id'}:
                reply = self.result(root, args['job_id'])
            elif action in ('status', 'stop', 'steer'):
                expected = {'action', 'job_id'} | ({'message'} if action == 'steer' else set())
                if set(args) != expected:
                    raise JobError('invalid_params')
                body = {'operation': 'refresh' if action == 'status' else action, 'job_id': args['job_id']}
                if action == 'steer':
                    body['text'] = args['message']
                reply = {'schema': 1, 'origin_profile': self.origin, 'job': self.control(root, body), 'completion_delivery': 'explicit_result'}
            else:
                raise JobError('invalid_params')
            return json.dumps(reply, ensure_ascii=False)
        except JobError as exc:
            return json.dumps(self._response_error(exc.code, exc.unknown))
        except (ValueError, PermissionError):
            return json.dumps(self._response_error('invalid_or_denied'))
        except Exception:
            return json.dumps(self._response_error('operation_unavailable', True))

    def close(self):
        self.closed.set()
        with self.mutex:
            clients = list(self.clients.values())
        for client in clients:
            client.close()  # viewer only: never stop the shared owner or its work


SCHEMA = {'name': 'profile_task', 'description':
    'Separate opt-in full-profile Gateway jobs; never a native subagent or Heavy adapter. Start requires separately saved full-profile grants. '
    'Use status without a job_id to read allowed targets and this exact conversation only. Start requires a stable request_id; reuse it unchanged after a known retry, never replay an unknown outcome. '
    'Target normal model/memory/context/tool policy is used on the tool surface; no parent toolset override. Existing Gateway required: none is started. '
    'Jobs survive parent turn end/close; stop only the exact returned job. There is NO automatic parent wake or native completion event. '
    'Collect the stored visible output with result. This tool cannot edit grants, approve tools, answer human questions, change backends or use arbitrary endpoints.',
    'parameters': {'type': 'object', 'additionalProperties': False, 'properties': {
        'action': {'type': 'string', 'enum': ['start', 'status', 'stop', 'steer', 'result']},
        'profile': {'type': 'string', 'description': 'Exact separately allowed target; read status first.'},
        'request_id': {'type': 'string', 'maxLength': 128, 'description': 'Stable caller-chosen identifier for one exact payload; never a credential.'},
        'goal': {'type': 'string', 'maxLength': 16000}, 'context': {'type': 'string', 'maxLength': 32000},
        'job_id': {'type': 'string'}, 'message': {'type': 'string', 'maxLength': 16000}}, 'required': ['action']}}


def register_profile_jobs(ctx, home):
    manager = None
    if all(callable(getattr(ctx, name, None)) for name in ('register_rpc', 'get_config', 'set_config', 'on_unload')):
        try:
            manager = ProfileJobs(ctx, home)
            for operation in ('describe', 'configure', 'list', 'control', 'result'):
                def handler(params, *, session_id=None, _op=operation, _manager=manager, **kwargs):
                    return _manager.rpc(_op, params, session_id=session_id, **kwargs)
                manager.handles.append(ctx.register_rpc('profile_jobs.' + operation, handler))
            manager.handles.append(ctx.register_hook('post_compaction', manager.compacted))
            manager.handles.append(ctx.on_unload(manager.close))
        except Exception:
            if manager is not None:
                manager.close()
                for handle in manager.handles:
                    if callable(getattr(handle, 'dispose', None)):
                        handle.dispose()
            manager = None
    def tool(args, **kwargs):
        if manager is None:
            return json.dumps({'schema': 1, 'status': 'refused', 'error': 'unsupported_sdk', 'no_effect': True})
        return manager.tool(args, **kwargs)
    handle = ctx.register_tool(name='profile_task', toolset='model_router', schema=SCHEMA, handler=tool,
                               check_fn=lambda: manager is not None and manager.available())
    if manager is not None:
        manager.handles.append(handle)
    return manager
