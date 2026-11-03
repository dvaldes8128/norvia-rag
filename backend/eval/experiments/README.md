# Off-CI retrieval experiments

Harness and reports for an **InsuranceQA-v2** subsample embedded with local
Ollama models (`nomic-embed-text`, `embeddinggemma`). Not run in GitHub Actions;
the brief deliverable remains synthetic `python -m eval.run`.

```bash
# Requires Ollama with the embedding models pulled.
uv run python -m eval.experiments.insuranceqa_ollama
```

Outputs land in `out/` (`report.html`, `results.json`). Large embedding caches
under `cache/` are gitignored.
