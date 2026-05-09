format:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ty check .
	uv run ruff check . 
