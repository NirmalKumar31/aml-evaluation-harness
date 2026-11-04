.PHONY: setup demo test clean
PY = .venv/bin/python

setup:            ## create the environment from pinned versions (Python 3.12)
	python3.12 -m venv .venv && .venv/bin/pip install -q -r requirements.txt

demo:             ## generate a tiny synthetic corpus and run every stage
	$(PY) -m aml demo --dest data/demo

test:
	$(PY) -m pytest -q

clean:
	rm -rf data/demo
