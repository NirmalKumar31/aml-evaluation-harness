.PHONY: demo replay-demo get-data verify-data setup test lint release-check package-smoke lock lock-hashes docker-build leak-sweep model-stability ingest patterns reconcile splits sweep features train evaluate leaks all full clean

# Default rung = HI-Medium (the working file). Override with: make VARIANT=Small ...
VARIANT ?= Medium
CUT     ?= 2022-09-10
PY       = .venv/bin/python
D        = data

# THE INTERPRETER, NAMED. pyproject declares >=3.12,<3.13. A bare `python3`
# makes the documented clean-setup path depend on whichever interpreter the
# reader's machine happens to call `python3`, which succeeds on a developer's
# machine and fails on a new reader's. Override with
# `make PYTHON=/path/to/python3.12`.
PYTHON  ?= python3.12

# Checked, not assumed: a wrong interpreter should fail here with a sentence,
# not four steps later inside pip's resolver.
define check_python
	@$(PYTHON) -c "import sys; v=sys.version_info; \
	  sys.exit(0) if (v.major,v.minor)==(3,12) else sys.exit( \
	    'FATAL: $(PYTHON) is %d.%d; this project requires 3.12 ' \
	    '(pyproject: >=3.12,<3.13). Install it, or pass PYTHON=<path>.' \
	    % (v.major, v.minor))"
endef

# From the locks, not from pyproject's ranges -- the same environment CI and
# the container get. pyproject declares compatibility; the locks declare what
# was verified.
setup:
	$(call check_python)
	$(PYTHON) -m venv .venv
	.venv/bin/pip install -q -U pip
	.venv/bin/pip install -q -r requirements.lock
	.venv/bin/pip install -q -r requirements-dev.lock
	.venv/bin/pip install -q --no-deps -e .

# Runs the REAL pipeline on a generated corpus. No data download, ~30s.
# The numbers it prints are meaningless by construction and it says so.
demo:
	$(PY) -m aml.cli demo --dest $(D)/demo

# NO-DATA REPLAY, DEMONSTRABLE WITHOUT THE DATASET.
#
# The archived bundles are withheld from distribution while the CDLA question
# is unreviewed, but the MECHANISM is the differentiator and it stays
# demonstrable: this target generates a synthetic corpus, cuts a bundle from
# it, and recomputes every budget metric from the bundle alone -- about
# 0.03 MB, no AMLworld bytes, nothing licensed.
replay-demo:
	$(PY) -m aml.cli demo --dest $(D)/replay-demo > /dev/null
	$(PY) scripts/make_replay_bundle.py --features $(D)/replay-demo/features \
	  --splits $(D)/replay-demo/splits \
	  --scores $(D)/replay-demo/models/gbdt_test_scores.parquet \
	  --dest $(D)/replay-demo/bundle --data-origin synthetic > /dev/null
	$(PY) scripts/verify_replay_bundle.py --bundle $(D)/replay-demo/bundle \
	  --manifest $(D)/replay-demo/models/manifest.json

# The published results need the real dataset, which is not redistributable.
get-data:
	@echo "IBM AMLworld is published by IBM under CDLA-Sharing-1.0."
	@echo "It is not redistributed with this repository."
	@echo
	@echo "  1. https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml"
	@echo "  2. place these under $(D)/ :"
	@echo "       HI-Small_Trans.csv    HI-Small_Patterns.txt    (475 MB)"
	@echo "       HI-Medium_Trans.csv   HI-Medium_Patterns.txt   (3.0 GB)"
	@echo "  3. make verify-data     <- hashes the dataset files you HAVE against"
	@echo "                             the pin. A file you do not have is not an"
	@echo "                             error unless you pass --require: locally"
	@echo "                             that means 5 of the 6 are checked, and"
	@echo "                             HI-Large_Trans.csv is simply absent."
	@echo "                             Use: verify_dataset.py --require all"
	@echo "  4. make all VARIANT=Small CUT=2022-09-05"
	@echo
	@echo "No download is needed to see the pipeline run: use 'make demo'."

# The raw dataset is identified by CONTENT, not by filename. If a future
# download does not match, it is a different dataset and the published numbers
# do not describe it. ~1 minute over 3.3 GB.
verify-data:
	$(PY) scripts/verify_dataset.py

test:
	.venv/bin/pytest -q

lint:
	.venv/bin/ruff check src/ tests/ scripts/

# Does the WHEEL work, in an environment that has nothing else in it?
#
# `pip install -e .` in the development venv proves almost nothing about the
# artifact a reader downloads: the editable install resolves imports from the
# source tree, and every dependency is already present. This builds the real
# sdist and wheel, installs the wheel into an empty interpreter, and runs the
# CLI and the no-data demo through it.
package-smoke:
	$(call check_python)
	rm -rf dist build/ .pkgsmoke .pkgbuild
	# THE BUILD TOOLS COME FROM A LOCK, into their own throwaway venv.
	# Neither dev lock contains `build`, so running it out of `.venv` makes
	# the documented clean-clone path fail with "No module named build".
	$(PYTHON) -m venv .pkgbuild
	.pkgbuild/bin/pip install -q -U pip
	.pkgbuild/bin/pip install -q -r requirements-release.lock
	# --no-isolation: build with the backend in requirements-release.lock,
	# not whatever PyPI resolves for `requires = [...]` today.
	.pkgbuild/bin/python -m build --no-isolation --sdist --wheel --outdir dist
	# Metadata a package index would reject is metadata this repository should
	# reject first.
	.pkgbuild/bin/twine check dist/*
	# WHAT IS ACTUALLY INSIDE THEM. `twine check` validates metadata and never
	# opens the archive, so a package README could claim the distributions
	# ship replay data with every gate green.
	.pkgbuild/bin/python scripts/check_package.py dist/*.whl dist/*.tar.gz
	$(PYTHON) -m venv .pkgsmoke
	.pkgsmoke/bin/pip install -q dist/*.whl
	.pkgsmoke/bin/aml --help > /dev/null
	.pkgsmoke/bin/aml demo --dest .pkgsmoke/demo > /dev/null
	@echo "wheel installs clean, twine accepts the metadata, and the demo runs through it"
	rm -rf .pkgsmoke .pkgbuild

# Regenerate the pinned environment the container installs. Run after any
# dependency change, and re-run `make test` before committing the result:
# the lock is a claim that these exact versions pass.
lock:
	@{ echo "# Exact environment the pipeline is TESTED against. Generated: $$(date -u +%Y-%m-%dT%H:%MZ)"; \
	   echo "# Python $$($(PY) -V | cut -d' ' -f2)"; \
	   echo "#"; \
	   echo "# The Dockerfile installs from THIS FILE, not from pyproject.toml's ranges."; \
	   echo "# pyproject declares compatibility; this declares what was verified."; \
	   echo; \
	   .venv/bin/pip list --format=freeze --exclude-editable \
	     | grep -viE '^(pytest|ruff|iniconfig|pluggy|pygments)='; } > requirements.lock
	@wc -l < requirements.lock | xargs echo "requirements.lock:" packages

# The hashed, platform-specific lock the CONTAINER installs. Needs network.
# Regenerate whenever requirements.lock changes, or the image build will fail
# closed -- which is the correct direction.
lock-hashes:
	@rm -rf .wheels && mkdir -p .wheels
	@grep -v '^#' requirements.lock | grep -v '^$$' > .wheels/pkgs.txt
	$(PY) -m pip download --no-deps --only-binary=:all: \
	  --python-version 3.12 --implementation cp --abi cp312 \
	  --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 \
	  --platform manylinux_2_28_x86_64 --platform any \
	  -r .wheels/pkgs.txt -d .wheels -q
	$(PY) scripts/write_hashed_lock.py --wheels .wheels \
	  --lock requirements.lock --out requirements.linux-amd64.lock
	@rm -rf .wheels

# Build and self-check the pipeline image. The image runs its own smoke test at
# build time, then we run the full suite INSIDE it -- that is the evidence the
# cloud environment behaves like this one.
# --platform is NOT optional. The development machine is arm64 and the cloud
# target is amd64. Without it the image builds fine, pushes fine, and dies at
# container start with "exec format error" -- after the compute has been
# provisioned and billed.
#
# pytest and its helpers are prepared outside the image from the hashed amd64
# dev lock, then mounted read-only. The runtime image has no pip or setuptools;
# tests must not reintroduce build tooling into the artifact being verified.
docker-build:
	docker buildx build --platform linux/amd64 -t aml-platform:local --load .
	@set -e; \
	  deps="$(CURDIR)/.image-test-deps"; \
	  trap 'rm -rf "$$deps"' EXIT; \
	  rm -rf "$$deps"; \
	  .venv/bin/python -m pip install -q --target "$$deps" \
	    --platform manylinux2014_x86_64 --implementation cp \
	    --python-version 3.12 --abi cp312 --only-binary=:all: \
	    --require-hashes -r requirements-dev.linux-amd64.lock; \
	  docker run --rm --platform linux/amd64 \
	    -v "$$deps:/test-deps:ro" -e PYTHONPATH=/test-deps \
	    --entrypoint python aml-platform:local -m pytest -q

# ^ AML_GIT_SHA is deliberately absent here: this target builds a LOCAL image
# for testing, and an image that claims a commit it was not built from is the
# defect the Dockerfile's ARG exists to prevent. The deployed image gets it
# from provision_vm.sh, which refuses to build without it.

# ONE COMMAND FOR EVERYTHING LOCALLY VERIFIABLE.
#
# Without it, nothing tells a reader which command regenerates which of the 56
# result sets, or which of them need data and cloud access they do not have.
# This runs every check that needs nothing but a checkout, and says plainly
# what it did NOT check.
release-check:
	@echo "== lint ==" && .venv/bin/ruff check src/ tests/ scripts/
	@echo "== tests ==" && .venv/bin/pytest -q
	@echo "== pipeline composes ==" && $(PY) -m aml.cli demo --dest $(D)/demo-check > /dev/null
	@echo "== storage abstraction ==" && .venv/bin/pytest tests/cloud/ -q
	@echo "== derived artifacts verify against git objects ==" && \
	  .venv/bin/pytest tests/repro/ -q \
	    -k "derived_artifact_names or refuses_when_the_code"
	@echo "== replay bundles recompute the published metrics ==" && \
	  .venv/bin/pytest -q -k replay
	@echo "== no-data replay works without the dataset ==" && $(MAKE) replay-demo
	@echo "== published numbers ==" && $(PY) scripts/make_tables.py --check --gate
	@echo "== budget metrics agree on their alert unit ==" && \
	  $(PY) scripts/check_units.py
	@echo "== published counts ==" && $(PY) scripts/release_facts.py --verify-artifact && \
	  $(PY) scripts/release_facts.py --check --gate
	@echo "== links and table structure ==" && $(PY) scripts/check_links.py ..
	@echo "== markdown style ==" && \
	  if command -v npx >/dev/null 2>&1; then \
	    cd .. && npx --yes markdownlint-cli2@0.14.0; \
	  else \
	    echo "  SKIPPED: no npx. The gates workflow runs this and WILL fail on"; \
	    echo "  what you cannot see here -- install Node before releasing."; \
	  fi
	@echo "== published figures match the archive ==" && \
	  $(PY) scripts/make_figures.py --check
	@echo "== static analysis (same bandit pin as gates.yml) ==" && \
	  if .venv/bin/bandit --version >/dev/null 2>&1; then \
	    .venv/bin/bandit -r src/ scripts/ -lll -q && \
	    (cd .. && aml-platform/.venv/bin/python aml-platform/scripts/check_sast.py); \
	  else \
	    echo "  SKIPPED: bandit is in no lockfile, so a fresh clone lacks it."; \
	    echo "  gates.yml pip-installs bandit==1.9.4 and WILL run this."; \
	    echo "  pip install 'bandit==1.9.4' to check it here."; \
	  fi
	@echo "== workflow actions are pinned to commit SHAs ==" && \
	  $(PY) scripts/check_pinned_actions.py
	@echo "== shell scripts (same severity as gates.yml) ==" && \
	  if command -v shellcheck >/dev/null 2>&1; then \
	    shellcheck -S warning scripts/*.sh; \
	  else echo "  SKIPPED: no shellcheck. gates.yml runs it."; fi
	@echo "== workflow syntax ==" && \
	  if command -v actionlint >/dev/null 2>&1; then \
	    (cd .. && actionlint -color); \
	  else echo "  SKIPPED: no actionlint. gates.yml runs it."; fi
	@echo "== secret scan ==" && \
	  if command -v gitleaks >/dev/null 2>&1; then \
	    (cd .. && gitleaks detect --no-banner --redact); \
	  else echo "  SKIPPED: no gitleaks. gates.yml runs it."; fi
	@echo "== the wheel builds, twine accepts it, and the demo runs through it =="
	@$(MAKE) --no-print-directory package-smoke
	@echo
	@echo "NOT CHECKED HERE, and each line states why:"
	@echo "  * HI-Large         -> docs/RUNBOOK_cloud.md    (needs Azure + 17 GB)"
	@echo "  * the image        -> the image workflow       (needs Docker)"
	@echo "  * bicep build      -> gates.yml                (needs az login)"
	@echo "  * external links   -> the weekly links workflow, or run it by hand"
	@echo "  RUNNABLE HERE, not part of this target because they are slow:"
	@echo "  * the dataset      -> make verify-data"
	@echo "  * Small/Medium     -> make all VARIANT=Small"

# The two experiments that produce the paper's results. Local, free.
leak-sweep:
	$(PY) -m aml.cli leak-sweep --features $(D)/silver/features_$(VARIANT) \
	  --splits $(D)/gold/splits_$(VARIANT) --leak-root $(D)/gold/leak_$(VARIANT) \
	  --dest $(D)/gold/leaksweep_$(VARIANT) --seeds 0,1,2,3,4,5,6,7

model-stability:
	$(PY) -m aml.cli model-stability --features $(D)/silver/features_$(VARIANT) \
	  --splits $(D)/gold/splits_$(VARIANT) --dest $(D)/gold/stability_$(VARIANT) \
	  --seeds 0,1,2,3,4,5,6,7

ingest:
	$(PY) -m aml.cli normalize --src $(D)/HI-$(VARIANT)_Trans.csv --dest $(D)/bronze/txns_$(VARIANT)

patterns:
	$(PY) -m aml.cli parse-patterns --src $(D)/HI-$(VARIANT)_Patterns.txt --dest $(D)/bronze/patterns_$(VARIANT)

reconcile:
	$(PY) -m aml.cli reconcile-labels --txns $(D)/bronze/txns_$(VARIANT) \
	  --patterns $(D)/bronze/patterns_$(VARIANT) --dest $(D)/gold/reconcile_$(VARIANT)

sweep:
	$(PY) -m aml.cli split-sweep --patterns $(D)/bronze/patterns_$(VARIANT) \
	  --labeled $(D)/gold/reconcile_$(VARIANT)

splits:
	$(PY) -m aml.cli build-splits --patterns $(D)/bronze/patterns_$(VARIANT) \
	  --labeled $(D)/gold/reconcile_$(VARIANT) --cut $(CUT) --dest $(D)/gold/splits_$(VARIANT)

features:
	$(PY) -m aml.cli build-features --src $(D)/gold/reconcile_$(VARIANT)/txns_labeled \
	  --dest $(D)/silver/features_$(VARIANT)

train:
	$(PY) -m aml.cli train --features $(D)/silver/features_$(VARIANT) \
	  --splits $(D)/gold/splits_$(VARIANT) --dest $(D)/gold/models_$(VARIANT) --model baseline
	$(PY) -m aml.cli train --features $(D)/silver/features_$(VARIANT) \
	  --splits $(D)/gold/splits_$(VARIANT) --dest $(D)/gold/models_$(VARIANT) --model gbdt

evaluate:
	for m in baseline gbdt; do \
	  $(PY) -m aml.cli evaluate --features $(D)/silver/features_$(VARIANT) \
	    --splits $(D)/gold/splits_$(VARIANT) \
	    --scores $(D)/gold/models_$(VARIANT)/$$m\_test_scores.parquet \
	    --dest $(D)/gold/eval_$(VARIANT)/$$m --model $$m; \
	done

leaks:
	for k in reversed_window future_counterparty target; do \
	  $(PY) -m aml.cli plant-leak --labeled $(D)/gold/reconcile_$(VARIANT)/txns_labeled \
	    --dest $(D)/gold/leak_$(VARIANT)/$$k --kind $$k; \
	done

# Genuinely end to end: through evaluation, not stopping at `splits`.
all: ingest patterns reconcile splits features train evaluate

# Everything above, plus the two replication experiments that produce the
# paper's results. Note leak-sweep GATES: it raises if the positive control
# fails to separate from its placebo.
full: all leaks leak-sweep model-stability

clean:
	rm -rf $(D)/bronze $(D)/silver $(D)/gold
