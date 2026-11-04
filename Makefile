.PHONY: setup demo test clean
PY = .venv/bin/python

setup:
	python3.12 -m venv .venv && .venv/bin/pip install -q -r requirements.txt

demo:
	$(PY) aml_pipeline.py demo --output data/demo

test:
	$(PY) -m pytest -q

clean:
	rm -rf data
