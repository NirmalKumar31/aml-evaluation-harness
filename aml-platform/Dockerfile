# The pipeline image. Built and tested by `.github/workflows/image.yml` on an
# amd64 runner, then run on an Azure VM -- see `docs/RUNBOOK_cloud.md`.
#
# NO ROW-LEVEL REPLAY DATA. This image `COPY`s the whole `results_archive/`,
# which in this repository holds aggregate manifests and the replay INVENTORY,
# and no replay rows. An image built from a tree that does hold them would
# redistribute data whose licence status is unreviewed, and must not be
# published.
#
# PINNED BY DIGEST, not by tag. A patch tag is mutable: the image the tests
# passed on and the image that runs the 180M-row job can differ while both
# call themselves 3.12.14-slim-bookworm. The trade is that a security update
# becomes a deliberate edit, which is the point, and Dependabot raises it.
#
# WHAT IS NOT PINNED, and is why two builds of one commit differ: the APT
# installs below resolve against mutable Debian repositories, the DuckDB Azure
# extension is fetched over the network at build time, and build timestamps
# are not normalised. The base layers are identical between builds; divergence
# begins at the first step after this line. Reproducibility here is source
# provenance, not a bit-reproducible container -- see the README.
FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e

# - build-essential: some wheels still compile on arm64/musl edge cases
# - ca-certificates: TLS to ADLS
# - git: manifest.py records the commit SHA in every run's provenance. Without
#   git the manifest silently records "unknown", which is exactly the sort of
#   quiet degradation this project exists to avoid.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential ca-certificates git \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Provenance, injected because the image cannot discover it: .dockerignore
# excludes .git -- correctly, it is not needed at runtime -- so without this
# every manifest the container writes would record code_git_sha "unknown".
ARG AML_GIT_SHA=unknown
ENV AML_GIT_SHA=${AML_GIT_SHA}

# Dependencies first, from the LOCK -- so a code change does not re-resolve the
# environment, and so the container gets the exact versions the test suite ran
# against rather than whatever pyproject's ranges permit today.
COPY requirements.linux-amd64.lock ./
# --require-hashes, against a platform-specific lock.
#
# requirements.lock comes from `pip list --format=freeze`: exact versions, no
# hashes, so there would be nothing to check against. This lock is resolved
# for THIS platform and carries a sha256 per wheel, so pip refuses to install
# anything whose bytes do not match. "The versions I tested" and "the bytes
# that ran" are different claims, and this makes the second one checkable.
RUN pip install --no-cache-dir --require-hashes -r requirements.linux-amd64.lock

# THE TOOLING THE BASE IMAGE SHIPS IS ALSO AN INPUT, and a container scan
# reads it. The base image's setuptools and pip are the toolchain rather than
# the dependency set, so they appear in no lock, --require-hashes never sees
# them and pip-audit never sees them either -- while a scanner reading the
# filesystem does. Pinning them here puts them under the same policy.
#
# Pinning setuptools here also closes a second hole. The editable install below
# disables build isolation, so it uses this known version instead of resolving
# `setuptools>=77` from the network after the hashed dependency layer. 84.0.0
# is the version requirements-release.lock uses for `python -m build`.
RUN pip install --no-cache-dir --upgrade \
      "pip==25.3" "setuptools==84.0.0" "wheel==0.48.0"

# Pre-install DuckDB's azure extension AT BUILD TIME.
#
# Without this, every container fetches it from the extension repository on
# first use. On a 182M-row job spread over many task containers that is a
# per-container network round trip and an outbound dependency in the middle of
# the most expensive stage -- a transient failure there costs the whole run.
RUN python -c "import duckdb; c=duckdb.connect(); c.execute('INSTALL azure'); c.execute('LOAD azure'); print('duckdb azure extension baked in')"

# Source last: the layers above are the slow ones and should stay cached.
#
# tests/ is included deliberately. Running the full suite INSIDE the built
# image is how the cloud environment is shown to behave like the local one --
# a stronger statement than "the image starts".
#
# THE NOTICES TRAVEL WITH THE THING THEY DESCRIBE. The image carries the
# results archive and the licence analysis that says where it came from and
# what terms attach. An artifact that carries derived data without the notice
# is not publishable whatever the notice concludes.
COPY LICENSE DATA_LICENSE.md ./
COPY pyproject.toml README.md ./
# The other three lock files, so the image carries a record of its own
# environment and the lock-consistency tests can run INSIDE it. Copied in this
# layer rather than beside requirements.linux-amd64.lock above, so that editing
# a dev pin does not invalidate the expensive dependency layer.
#
# The suite running in the image caught their absence on the first build after
# those tests were added, which is exactly what running it in here is for.
COPY requirements.lock requirements-dev.lock ./
COPY requirements-dev.linux-amd64.lock ./
COPY src ./src
COPY tests ./tests
# scripts/ too. The replay-bundle generator and the publication checker run
# against cloud data, in this image, on a machine with no checkout. An image
# that can run the pipeline but not the tooling that CHECKS the pipeline is
# half an image.
COPY scripts ./scripts
# results_archive/ too -- 13 MB, and it is what turns "the suite runs in the
# image" into "the image validates the released archive".
#
# Without it the archive-dependent tests find no artifacts and skip, and the
# ones that skip are exactly the replay recomputations, the provenance checks
# and the dataset-pin contract -- the reproducibility evidence. A container
# that can run the pipeline but cannot check the pipeline's published outputs
# proves the environment starts, not that it agrees.
#
COPY results_archive ./results_archive
# docs/ too, ~200 KB. Three release-critical tests read a document and a script
# and check they agree -- the runbook's commands against the scripts' required
# inputs, and the cost table against cost.json. Shipping the scripts without
# the documents they are checked against means the image can run those tests
# and cannot answer them.
#
# The remaining image skips are the repository-ROOT documents (README,
# CONTRIBUTING, CHANGELOG), the Dockerfile itself, and the tests that need
# built gold outputs. They are outside this build context by construction.
# The NUMBER of skips is deliberately not written here: a count in prose is
# wrong as soon as a test is added. The image job asserts the permitted
# REASONS instead; see docs/RELEASE_CHECKLIST.md section 3a.
COPY docs ./docs
# --no-build-isolation so the pinned setuptools above is the one that builds
# this package, instead of PEP 517 fetching an unpinned copy from the network.
RUN pip install --no-deps --no-build-isolation -e .

# pip and setuptools are build tools, not runtime dependencies. Keeping them
# in the final image also keeps pip's vendored dependency tree in the attack
# surface (including packages the application never imports). The editable
# install above has already written the .pth/dist-info needed at runtime, so
# remove both tools and assert that a later Dockerfile edit cannot silently
# add them back.
RUN python -m pip uninstall -y pip setuptools wheel \
 && python -c "import importlib.util as u; assert all(u.find_spec(n) is None for n in ('pip', 'setuptools', 'wheel'))"

# Run as non-root. Azure ML does not require it, but a container that only ever
# reads inputs and writes to a mounted output path has no need for root, and the
# DuckDB extension cache must be readable by whoever runs.
# APPLICATION CODE STAYS ROOT-OWNED. `chown -R aml:aml /app` would make every
# module writable by the account the container runs as, so a process that
# gets execution could also modify what runs next. Only the home directory
# and the DuckDB extension cache need to belong to the runtime user.
#
# NOT A FULL BUILDER-STAGE WHEEL. The stricter design is a wheel built in a
# builder stage and installed non-editably into a slim runtime image, with
# tests in a separate image. That trades away what this image is FOR --
# running the whole suite inside the artifact that ran the results, which is
# the evidence the cloud environment matches the local one. Recorded as a
# known gap rather than half-done.
RUN useradd --create-home --uid 10001 aml \
 && cp -r /root/.duckdb /home/aml/.duckdb \
 && chown -R aml:aml /home/aml \
 && chmod -R a-w /app/src /app/scripts /app/results_archive /app/docs
USER aml

# Fail fast and visibly if the image is broken, rather than at stage 6 of a
# pipeline run.
RUN aml --help > /dev/null && python -c "\
import duckdb, aml.io, aml.exits;\
from aml.models import config;\
c = duckdb.connect(); c.execute('LOAD azure');\
assert aml.io.is_uri('abfss://c@a.dfs.core.windows.net/x');\
print('image self-check OK; production GBDT =', config.GBDT)"

ENTRYPOINT ["aml"]
CMD ["--help"]
