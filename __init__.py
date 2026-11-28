"""Model Router native plugin. No configuration writes during registration."""
from pathlib import Path
import json
import os


def register(ctx):
    from hermes_constants import get_hermes_home, set_hermes_home_override, reset_hermes_home_override
    from .model_router.service import Service

    home = Path(get_hermes_home())

    def scoped(callback):
        token = set_hermes_home_override(home)
        try:
            return callback(Service())
        finally:
            reset_hermes_home_override(token)

    def enabled():
        try:
            return bool(scoped(lambda service: service.routing_config(service.active_profile())["enabled"]))
        except (OSError, ValueError, RuntimeError, KeyError):
            return False

    def cli_setup(parser):
        parser.add_argument("operation", choices=["status", "preview", "fallback-preview", "delegation-preview", "initial-setup-preview", "custom-slots-preview", "apply", "stage", "role-proposal-context", "role-proposal", "profile-jobs-status", "profile-jobs-configure"])
        parser.add_argument("--body", default="{}")

    def cli_handler(args):
        # Grant administration belongs to this original host CLI context only.
        # Never bridge these operations through renderer cli.exec or plugin RPC.
        if args.operation in ('profile-jobs-status', 'profile-jobs-configure'):
            from .model_router.full_profile_policy import operator_cli
            result = operator_cli(ctx, home, args.operation, args.body)
            print('MODEL_ROUTER_JSON:' + json.dumps(result, ensure_ascii=False, separators=(',', ':')))
            return 0 if result.get('status') in ('ready', 'saved', 'noop') else 2
        # Existing ordinary settings/proposal commands retain their native path.
        try:
            if len(args.body) > 16384:
                raise ValueError("payload too large")
            body = json.loads(args.body)
            if not isinstance(body, dict):
                raise ValueError("body must be an object")
            if args.operation == "stage":
                from .model_router import staged_body
                print("MODEL_ROUTER_JSON:" + json.dumps(staged_body.stage(home, body), separators=(",", ":")))
                return 0
            if set(body) == {"staged"}:
                # A large settings body arrives in pieces staged by earlier calls.
                from .model_router import staged_body
                if args.operation not in staged_body.STAGED_OPERATIONS:
                    raise ValueError("this operation does not accept a staged body")
                body = staged_body.assemble(home, body)
            def operation(service):
                def completion_available():
                    try:
                        return callable(getattr(ctx.llm, 'complete_structured', None))
                    except Exception:
                        return False
                if args.operation == "status":
                    # A page asks for a size-bounded reply; anything else in the body is refused.
                    if body and (set(body) - {"paged", "profiles"} or body.get("paged") is not True):
                        raise ValueError("status accepts only paged and profiles")
                    result = service.status(paged=True, profiles=body.get("profiles")) if body else service.status()
                    available = completion_available()
                    result['role_proposal'] = {'schema': 1, 'transport': 'native_cli', 'available': available, 'reason_code': None if available else 'unsupported_sdk'}
                    return result
                if args.operation in ('role-proposal-context', 'role-proposal'):
                    from .model_router import role_proposal
                    try:
                        role_proposal._body(body, args.operation == 'role-proposal')
                        role_proposal._owner(service, home, body)
                    except Exception:
                        return role_proposal._failure('owner_mismatch')
                    if args.operation == 'role-proposal-context':
                        return role_proposal.context(service, home, body, completion_available())
                    def complete(**kwargs):
                        return ctx.llm.complete_structured(**kwargs)
                    return role_proposal.generate(service, home, body, complete if completion_available() else None)
                if args.operation == "preview": return service.preview(body)
                if args.operation == "fallback-preview": return service.fallback_preview(body)
                if args.operation == "delegation-preview": return service.delegation_preview(body)
                if args.operation == "initial-setup-preview": return service.initial_setup_preview(body)
                if args.operation == "custom-slots-preview": return service.custom_slots_preview(body)
                if set(body) != {"plan_id"}: raise ValueError("apply accepts only plan_id")
                return service.apply(body["plan_id"])
            if args.operation in ('role-proposal-context', 'role-proposal'):
                try:
                    current = Path(get_hermes_home()).resolve(strict=True)
                    captured = home.resolve(strict=True)
                    if os.path.normcase(str(current)) != os.path.normcase(str(captured)):
                        raise ValueError('owner_mismatch')
                except Exception:
                    print('MODEL_ROUTER_JSON:' + json.dumps({'schema': 1, 'status': 'error', 'code': 'owner_mismatch'}, separators=(',', ':')))
                    return 0
            result = scoped(operation)
            from .model_router.service import cli_reply
            print(cli_reply(result))
            return 0
        except Exception as exc:
            try:
                from .model_router.service import cli_error_payload
                payload = cli_error_payload(exc)
            except Exception:
                payload = {"error": type(exc).__name__, "message": "작업이 완료되지 않았습니다. 상태를 확인한 후 다시 미리보기 하세요."}
            print("MODEL_ROUTER_JSON:" + json.dumps(payload, ensure_ascii=False))
            return 2

    ctx.register_cli_command("model-router", "Profile model settings and task routing", cli_setup, cli_handler)

    # Ordinary native delegation has its own opt-in total limit, independent
    # of routing membership. Never mutate native inactivity config.
    from .model_router.native_watchdog import register_native_watchdog
    register_native_watchdog(ctx, home)

    # Session Fast inheritance is independent of routing opt-in and TOTAL.
    # The controller observes exact native child IDs and rewrites only their
    # supported request payloads; it never edits native agent/config state.
    from .model_router.fast_inheritance import register_fast_inheritance
    fast_controller = register_fast_inheritance(ctx, home)

    from .model_router.native_delegation import register_native_delegation
    register_native_delegation(ctx, home)

    # A read-only advisor the working agent consults and waits for. Its guard hooks are
    # registered before the tool; without them the tool is never offered.
    from .model_router.advise_guard import register_advise_guard
    register_advise_guard(ctx, home, routing_enabled=enabled)

    # Passive metadata only: this never dispatches, reroutes or controls a child.
    from .model_router.execution_roster import register_execution_roster
    register_execution_roster(ctx, home)

    # Independent opt-in jobs. Native delegate_task and retired starts stay untouched.
    from .model_router.profile_jobs import register_profile_jobs
    register_profile_jobs(ctx, home)

    if enabled():
        ctx.register_skill(
            "adaptive-coding-orchestration",
            Path(__file__).parent / "skills/adaptive-coding-orchestration/SKILL.md",
            "Profile-enabled coding and complex non-coding orchestration: Main handles small bounded changes directly; delegate implementation only for worthwhile parallel work; keep required reviews.",
        )

    def handler(args, **kwargs):
        try:
            if set(args) != {"action"} or args.get("action") != "config":
                raise ValueError("action must be config")
            return json.dumps(scoped(lambda service: service.routing_config(service.active_profile())), ensure_ascii=False)
        except (ValueError, PermissionError, KeyError) as exc:
            return json.dumps({"error": "invalid_or_denied", "message": str(exc)}, ensure_ascii=False)
        except Exception:
            return json.dumps({"error": "route_operation_failed", "message": "라우팅 설정을 읽지 못했습니다. 설정 화면에서 상태를 확인하세요."}, ensure_ascii=False)

    schema = {
        "name": "coding_route",
        "description": "Read this profile's task slots: which model each purpose runs on and its runtime limit. New work uses native delegate_task with the selected model-router, model-router-profiles or model-router-auto backend. Main handles small bounded changes directly, including tests. Ordinary delegation needs a concrete benefit: a different-model route the task needs, large context, long runtime, or at least two substantive independent workstreams; on Main's own model, design stays with Main unless explicitly requested by the user; required reviews (semantic-final, independent-review) remain mandatory. ask_advisor is a read-only same-turn consultation of the advise slot at a decision point, not delegation or a required review. Read model-router:adaptive-coding-orchestration. config is not proof that this session selected a native backend. Native route reports are runtime-reported identity, not successful-response evidence or semantic GO. This tool never launches work or changes settings.",
        "parameters": {
            "type": "object", "additionalProperties": False,
            "properties": {"action": {"type": "string", "enum": ["config"]}},
            "required": ["action"],
        },
    }
    ctx.register_tool(name="coding_route", toolset="model_router", schema=schema, handler=handler, check_fn=lambda: True)
