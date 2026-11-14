.PHONY: test deb docs clean

test:            ## lance tous les tests
	python3 tests/run_all.py

deb:             ## construit dist/mintmail_<version>_all.deb
	packaging/build-deb.sh

docs:            ## régénère docs/AIDE.md depuis l'aide intégrée
	python3 tools/gen_docs.py

clean:
	rm -rf dist build .pytest_cache; find . -name __pycache__ -prune -exec rm -rf {} +
