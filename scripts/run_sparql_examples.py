"""Run the SPARQL examples from the semantic-model learning chapter."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.semantic import load_graph


METRICS_QUERY = """
PREFIX : <https://example.org/retail#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?metric ?definition ?grain WHERE {
  ?metric a :Metric ; :metricDefinition ?definition ; :metricGrain ?grain .
}
ORDER BY ?metric
"""

SOURCE_MAPPING_QUERY = """
PREFIX : <https://example.org/retail#>
SELECT ?metric ?table ?column WHERE {
  ?metric a :Metric ; :metricUsesField ?field .
  ?field :fieldTable ?table ; :fieldName ?column .
}
ORDER BY ?metric ?table ?column
"""


def main() -> None:
    version, graph = load_graph()
    metrics = list(graph.query(METRICS_QUERY))
    mappings = list(graph.query(SOURCE_MAPPING_QUERY))
    print(f"Model {version}: {len(metrics)} metrics, {len(mappings)} metric-to-field mappings")
    for row in metrics:
        print(f"{row.metric.rsplit('#', 1)[-1]} | {row.grain} | {row.definition}")
    for row in mappings:
        print(f"{row.metric.rsplit('#', 1)[-1]} -> {row.table}.{row.column}")


if __name__ == "__main__":
    main()
