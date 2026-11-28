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
    p = sub.add_parser("delegation-preview"); p.add_argument("--file", required=True)
    p = sub.add_parser("initial-setup-preview"); p.add_argument("--file", required=True)
    p = sub.add_parser("apply"); p.add_argument("--plan-id", required=True)
    p = sub.add_parser("initialize")
    p.add_argument("--routing-profiles", nargs="*", required=True)
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
        elif args.action == "delegation-preview":
            result = service.delegation_preview(json.loads(Path(args.file).read_text(encoding="utf-8")))
        elif args.action == "initial-setup-preview":
            result = service.initial_setup_preview(json.loads(Path(args.file).read_text(encoding="utf-8")))
        elif args.action == "apply":
            result = service.apply(args.plan_id)
        else:
            result = service.initialize(args.routing_profiles)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if isinstance(result, dict) and (result.get("status") in {"failed", "partial", "unverified"} or result.get("error")):
            return 2
        return 0
    except (ValueError, PermissionError, RuntimeError, FileNotFoundError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)[:500]}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
