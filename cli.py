"""CLI uses the same service as the Desktop UI; never parses/executes a BAT."""
import argparse
import json
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description="Hermes Model Router")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("status")
    p = sub.add_parser("preview"); p.add_argument("--file", required=True)
    p = sub.add_parser("fallback-preview"); p.add_argument("--file", required=True)
    p = sub.add_parser("apply"); p.add_argument("--plan-id", required=True)
    p = sub.add_parser("initialize")
    p.add_argument("--routing-profiles", nargs="*", required=True)
    p.add_argument("--fallbacks-file")
    p = sub.add_parser("route")
    p.add_argument("--purpose", required=True, choices=["implementation", "mechanical", "preliminary-review", "plan", "semantic-final", "independent-review"])
    p.add_argument("--prompt-file", required=True)
    p.add_argument("--cwd", required=True)
    p.add_argument("--timeout", type=int, default=None, help="Per-job total seconds; omitted uses profile setting, 0 disables the plugin total limit")
    p.add_argument("--title", help="Public Background task title (1–96 characters; no secrets)")
    p = sub.add_parser("job-status"); p.add_argument("--job-id", required=True)
    args = parser.parse_args(argv)
    try:
        from model_router.service import Service
        service = Service()
        if args.action == "status":
            result = service.status()
        elif args.action == "preview":
            result = service.preview(json.loads(Path(args.file).read_text(encoding="utf-8")))
        elif args.action == "fallback-preview":
            result = service.fallback_preview(json.loads(Path(args.file).read_text(encoding="utf-8")))
        elif args.action == "apply":
            result = service.apply(args.plan_id)
        elif args.action == "initialize":
            fallbacks = json.loads(Path(args.fallbacks_file).read_text(encoding="utf-8")) if args.fallbacks_file else None
            result = service.initialize(args.routing_profiles, fallbacks=fallbacks)
        else:
            from model_router.routing import Router
            router = Router(service)
            if args.action == "route":
                result = router.start(args.purpose, Path(args.prompt_file).read_text(encoding="utf-8"), args.cwd, args.timeout, title=args.title)
            else:
                result = router.status(args.job_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if isinstance(result, dict) and (result.get("status") in {"failed", "partial", "unverified"} or result.get("error")):
            return 2
        return 0
    except (ValueError, PermissionError, RuntimeError, FileNotFoundError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)[:500]}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
