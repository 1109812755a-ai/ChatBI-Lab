"""Validate a versioned retail RDF/OWL model with its SHACL shapes."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pyshacl import validate
from rdflib import Graph

ROOT = Path(__file__).resolve().parents[1]


def validate_model(model_dir: Path) -> tuple[bool, str]:
    data_graph = Graph()
    data_graph.parse(model_dir / "retail.ttl", format="turtle")
    data_graph.parse(model_dir / "semantic-model.ttl", format="turtle")
    shapes_graph = Graph().parse(model_dir / "shapes.ttl", format="turtle")
    conforms, _report_graph, report_text = validate(
        data_graph=data_graph,
        shacl_graph=shapes_graph,
        inference="none",
        abort_on_first=False,
        allow_infos=False,
        allow_warnings=False,
    )
    return conforms, report_text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=ROOT / "ontology" / "versions" / "1.0",
        help="directory containing retail.ttl, semantic-model.ttl, and shapes.ttl",
    )
    args = parser.parse_args()
    model_dir = args.model_dir.resolve()
    try:
        conforms, report_text = validate_model(model_dir)
    except Exception as error:
        print(f"Could not load or validate model at {model_dir}: {error}", file=sys.stderr)
        return 2

    if conforms:
        print(f"Model {model_dir.name} conforms to its SHACL shapes.")
        return 0

    print(f"Model {model_dir.name} does not conform to its SHACL shapes.")
    print(report_text)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
