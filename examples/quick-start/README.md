# Example: Quick Start

## Usage

Install the dependencies with `uv`:
```sh
uv sync --all-extras --dev
```

To run, execute the following commands while in `fed-rag/examples/quickstart`:

```sh
# start server
uv run -m quick_start.main --component server

# start client 1
uv run -m quick_start.main --component client_1

# start client 2
uv run -m quick_start.main --component client_2
```
