"""Register, validate, publish, select, and roll back local RDF model versions."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # Supports both `python scripts/model_registry.py` and package imports.
    from .validate_model import validate_model
except ImportError:
    from validate_model import validate_model

ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ROOT / "ontology" / "versions"
REGISTRY = ROOT / "ontology" / "registry.json"
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_registry() -> dict[str, Any]:
    if not REGISTRY.exists():
        return {"active_version": None, "versions": {}, "history": []}
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def save_registry(registry: dict[str, Any]) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    temp = REGISTRY.with_suffix(".json.tmp")
    temp.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(REGISTRY)


def version_dir(version: str) -> Path:
    if not VERSION_RE.fullmatch(version):
        raise ValueError("Version may contain only letters, numbers, dot, underscore, and hyphen.")
    return VERSIONS / version


def register(version: str, source: Path) -> None:
    target = version_dir(version)
    registry = load_registry()
    if version in registry["versions"] or target.exists():
        raise ValueError(f"Version {version!r} is already registered or exists.")
    if not source.is_dir() or not all((source / name).is_file() for name in ("retail.ttl", "semantic-model.ttl", "shapes.ttl")):
        raise ValueError("Source must contain retail.ttl, semantic-model.ttl, and shapes.ttl.")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    registry["versions"][version] = {"status": "candidate", "registered_at": now(), "validation": None}
    save_registry(registry)
    print(f"Registered candidate model {version} at {target}.")


def bootstrap(version: str) -> None:
    """Register and publish an already checked-in initial version."""
    target = version_dir(version)
    registry = load_registry()
    if registry["active_version"]:
        active_record = registry["versions"].get(registry["active_version"], {})
        if (registry["active_version"] == version
                and active_record.get("validation", {}).get("conforms")):
            print(f"Model {version} is already the active published version.")
            return
        raise ValueError(f"Registry already has active version {registry['active_version']!r}.")
    if not target.is_dir():
        raise ValueError(f"Initial model directory does not exist: {target}")
    registry["versions"][version] = {"status": "candidate", "registered_at": now(), "validation": None}
    save_registry(registry)
    publish(version)


def validate_candidate(version: str) -> tuple[bool, str]:
    registry = load_registry()
    if version not in registry["versions"]:
        raise ValueError(f"Unknown model version {version!r}; register it first.")
    conforms, report = validate_model(version_dir(version))
    registry["versions"][version]["validation"] = {
        "conforms": conforms,
        "validated_at": now(),
        "report": report,
    }
    registry["versions"][version]["status"] = "validated" if conforms else "rejected"
    save_registry(registry)
    return conforms, report


def publish(version: str) -> None:
    conforms, report = validate_candidate(version)
    registry = load_registry()
    if not conforms:
        print(f"Model {version} rejected; active version remains {registry['active_version']!r}.", file=sys.stderr)
        print(report, file=sys.stderr)
        raise SystemExit(1)
    prior = registry["active_version"]
    if prior:
        registry["versions"][prior]["status"] = "published"
    registry["active_version"] = version
    registry["versions"][version]["status"] = "active"
    registry["versions"][version]["published_at"] = now()
    registry["history"].append({"action": "publish", "from": prior, "to": version, "at": now()})
    save_registry(registry)
    print(f"Published model {version}; previous active version was {prior!r}.")


def rollback(version: str) -> None:
    registry = load_registry()
    record = registry["versions"].get(version)
    if not record or record.get("status") not in {"published", "active"}:
        raise ValueError(f"Version {version!r} is not a previously published version and cannot be restored.")
    prior = registry["active_version"]
    if prior == version:
        print(f"Model {version} is already active.")
        return
    if prior:
        registry["versions"][prior]["status"] = "published"
    registry["active_version"] = version
    record["status"] = "active"
    registry["history"].append({"action": "rollback", "from": prior, "to": version, "at": now()})
    save_registry(registry)
    print(f"Rolled back active model from {prior!r} to {version}.")


def select(version: str | None) -> str:
    registry = load_registry()
    selected = version or registry["active_version"]
    if not selected or selected not in registry["versions"]:
        raise ValueError("No published model is active. Publish a validated version first.")
    if registry["versions"][selected].get("status") not in {"published", "active"}:
        raise ValueError(f"Model {selected!r} has not been published.")
    if not registry["versions"][selected].get("validation", {}).get("conforms"):
        raise ValueError(f"Model {selected!r} has not passed validation.")
    print(version_dir(selected))
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("bootstrap", help="validate and publish the checked-in initial version")
    init.add_argument("version")
    reg = commands.add_parser("register", help="copy a model directory as a candidate version")
    reg.add_argument("version")
    reg.add_argument("--source", type=Path, required=True)
    val = commands.add_parser("validate", help="validate and record a candidate report")
    val.add_argument("version")
    pub = commands.add_parser("publish", help="validate and activate a model version")
    pub.add_argument("version")
    sel = commands.add_parser("select", help="show the active or explicitly selected version directory")
    sel.add_argument("version", nargs="?")
    rb = commands.add_parser("rollback", help="activate a previously validated version")
    rb.add_argument("version")
    args = parser.parse_args()
    try:
        if args.command == "bootstrap":
            bootstrap(args.version)
        elif args.command == "register":
            register(args.version, args.source.resolve())
        elif args.command == "validate":
            conforms, report = validate_candidate(args.version)
            print(f"Model {args.version} {'conforms' if conforms else 'does not conform'}.")
            if report:
                print(report)
            return 0 if conforms else 1
        elif args.command == "publish":
            publish(args.version)
        elif args.command == "select":
            select(args.version)
        elif args.command == "rollback":
            rollback(args.version)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(error, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
