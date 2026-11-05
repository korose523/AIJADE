# P3-C: the scorer pre-check on independent memory systems

Plan: `experiments/plans/2026-11-05-p3-c-external-memory-systems.md`. The systems were installed in an isolated Python 3.12
environment from the commits the plan names, with `uv pip install`:

- LangChain `libs/langchain` at `b4aa7e7d00c4`, with `langchain-community` and `faiss-cpu`;
- LlamaIndex `llama-index-core` at `444fdf068470`;
- Mem0 at `ed1f10fc8708`.

CrewAI, first in the plan's order for its stratum, did not qualify on the Mac: its `lancedb` dependency publishes no wheel for
macOS on x86_64 (versions 0.33 and later; the Mac is an Intel machine), so rule (2) of the plan fails there.

To reproduce: `aijade-experiments locomo-export --out locomo-export.json`, then
`python experiments/p3-c/precheck.py <system> --corpus locomo-export.json --out experiments/p3-c`, with Ollama serving
nomic-embed-text v1.5 on 127.0.0.1.
