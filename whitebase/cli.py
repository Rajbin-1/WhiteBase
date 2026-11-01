from __future__ import annotations

import argparse
import json
from pathlib import Path

from .runtime import WhiteBase


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="White Base CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List installed components")
    list_parser.set_defaults(action="list")

    install_parser = subparsers.add_parser("install", help="Install a .wb package")
    install_parser.add_argument("package")
    install_parser.set_defaults(action="install")

    inspect_parser = subparsers.add_parser("inspect", help="Inspect a component")
    inspect_parser.add_argument("component_id")
    inspect_parser.set_defaults(action="inspect")

    capabilities_parser = subparsers.add_parser("capabilities", help="List capability index")
    capabilities_parser.set_defaults(action="capabilities")

    load_parser = subparsers.add_parser("load", help="Load a component")
    load_parser.add_argument("component_id")
    load_parser.set_defaults(action="load")

    unload_parser = subparsers.add_parser("unload", help="Unload a component")
    unload_parser.add_argument("component_id")
    unload_parser.set_defaults(action="unload")

    run_parser = subparsers.add_parser("run", help="Run a request for a capability")
    run_parser.add_argument("capability")
    run_parser.add_argument("input_text", nargs="?")
    run_parser.set_defaults(action="run")

    health_parser = subparsers.add_parser("health", help="Inspect health of all loaded components")
    health_parser.set_defaults(action="health")

    benchmark_parser = subparsers.add_parser("benchmark", help="Benchmark White Base overhead")
    benchmark_parser.set_defaults(action="benchmark")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    wb = WhiteBase()

    if args.action == "list":
        print(json.dumps(wb.list_components(), indent=2))
    elif args.action == "install":
        brick = wb.install(args.package)
        print(json.dumps({"installed": brick.brick_id, "state": brick.state}, indent=2))
    elif args.action == "inspect":
        print(json.dumps(wb.inspect(args.component_id), indent=2))
    elif args.action == "capabilities":
        print(json.dumps(wb.capabilities(), indent=2))
    elif args.action == "load":
        connector = wb.load(args.component_id)
        print(json.dumps({"loaded": args.component_id, "capabilities": connector.capabilities}, indent=2))
    elif args.action == "unload":
        wb.unload(args.component_id)
        print(json.dumps({"unloaded": args.component_id}, indent=2))
    elif args.action == "run":
        payload = {"text": args.input_text or "hello"}
        result = wb.request(args.capability, payload)
        print(json.dumps(result, indent=2, default=str))
    elif args.action == "health":
        health = {component_id: brick.connector.health() if brick.connector else {"status": "unloaded"} for component_id, brick in wb.loaded.items()}
        print(json.dumps(health, indent=2))
    elif args.action == "benchmark":
        print(json.dumps(wb.benchmark(), indent=2))


if __name__ == "__main__":
    main()
