FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /uvx /bin/

COPY pyproject.toml uv.lock* .python-version ./
RUN uv sync --no-dev --frozen
COPY . .

CMD ["uv", "run", "python", "-u", "-m", "src.bot"]
