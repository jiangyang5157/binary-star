Run the full test suite.

```
./venv/bin/python3 -m pytest tests/ -v --tb=short
```

The project's pyproject.toml already configures `testpaths = ["tests"]` and `python_files = ["test_*.py"]` — no extra flags needed.
