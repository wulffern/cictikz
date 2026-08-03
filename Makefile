help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'

dev-install: ## Editable install with mcp extra
	pip install -e ".[mcp]"

install: ## Install package
	pip install .

test: ## Run unit tests
	python3 -m pytest -q

lint: ## Ruff, if available
	-ruff check src tests

check: ## Import and print version
	python3 -c "import cictikz; print(cictikz.__version__)"

build: clean ## Build sdist + wheel
	python3 -m build
	python3 -m twine check dist/*

test_upload: build ## Upload to Test PyPI
	python3 -m twine upload --repository testpypi dist/*

upload: build ## Upload to PyPI (the first release is done this way)
	python3 -m twine upload dist/*

clean: ## Remove build artefacts
	rm -rf build dist src/*.egg-info

.PHONY: help dev-install install test lint check build test_upload upload clean
