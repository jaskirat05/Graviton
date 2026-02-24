# Graviton Backend
FROM python:3.10-slim

WORKDIR /app

# Install uv for fast dependency management
RUN pip install uv

# Copy dependency files and README (required by pyproject.toml)
COPY pyproject.toml uv.lock README.md ./

# Copy core package for installation
COPY core/ ./core/

# Install the package and dependencies to system Python
RUN uv pip install --system .

# Copy and setup entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create directories
RUN mkdir -p artifacts registry_templates

EXPOSE 8001

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "core/main.py"]
