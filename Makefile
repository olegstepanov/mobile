.PHONY: test baseline diff-baseline

test:
	uv run python test_smoke.py

baseline:
	mkdir -p baseline
	@for shape in circle burst star heart shopify cup eclipse octopus smile sun blank; do \
		uv run mbl "HI" --shape "$$shape" --output "baseline/$${shape}.3mf"; \
	done

diff-baseline:
	mkdir -p baseline-after
	@for shape in circle burst star heart shopify cup eclipse octopus smile sun blank; do \
		uv run mbl "HI" --shape "$$shape" --output "baseline-after/$${shape}.3mf"; \
	done
	python3 diff_baseline.py
