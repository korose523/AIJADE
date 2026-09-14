# RQ-C replay — generates every paper table/figure from raw run artifacts.
#
# The replay is deterministic and provenance-stamped (see packages/research-harness/replay/replay.ts).
# Usage:
#   make figures                                  # default RUN = completed mock
#   make figures RUN=rq-c-s42-ollama-t30-r5        # live in-progress run
#   make figures-mock                             # alias
#   make figures-live                             # alias
#
# No package.json is touched; the runner is wired through this target only.

REPLAY_PKG := packages/research-harness
RUN ?= rq-c-s42-mock-t30-r5
TSX := node_modules/.bin/tsx

.PHONY: figures figures-mock figures-live

figures:
	cd $(REPLAY_PKG) && env -u NODE_OPTIONS ../../$(TSX) replay/replay.ts \
	  --run-dir experiments/rq-c/$(RUN) \
	  --summary experiments/rq-c/$(RUN)/summary.json \
	  --out replay/out

figures-mock:
	$(MAKE) figures RUN=rq-c-s42-mock-t30-r5

figures-live:
	$(MAKE) figures RUN=rq-c-s42-ollama-t30-r5
