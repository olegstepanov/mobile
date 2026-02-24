.PHONY: test typecheck lint format build clean

test:
	LD_LIBRARY_PATH=$(HOME)/.local/share/uv/python/cpython-3.14-linux-x86_64-gnu/lib uv run python -m pytest tests/

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
