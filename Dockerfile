FROM python:3.11-slim

WORKDIR /app

# Copy only what the build needs before the source, so dependency layers
# cache across builds that only touch application code.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/var \
    && chown -R appuser:appuser /app
USER appuser

ENV MCP_TRANSPORT=streamable-http \
    LOG_FORMAT=json \
    PORT=8080

EXPOSE 8080

CMD ["email-mcp-server"]
