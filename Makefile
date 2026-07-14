.PHONY: install demo test clean

install:
	pip install -r requirements.txt

demo:
	./run_demo.sh

test:
	pytest -q

clean:
	rm -f data/synthetic/*.jsonl data/synthetic/*.csv logs/*.log
	find . -type d -name __pycache__ -exec rm -rf {} +
