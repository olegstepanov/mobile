.PHONY: test typecheck lint format build clean

test:
	uv run python -m pytest tests/

typecheck:
	ty check mobile/

lint:
	ruff check mobile/ designs/

format:
	ruff format mobile/ designs/

build:
	uv run python designs/yurika.py

clean:
	rm -rf output/
