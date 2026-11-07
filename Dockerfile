FROM mcr.microsoft.com/playwright/python:v1.45.0-noble

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and examples
COPY src/ ./src/
COPY examples/ ./examples/

# Environment configurations
ENV PYTHONUNBUFFERED=1
ENV PORT=3001
ENV USER_DATA_DIR=/app/userdata

EXPOSE 3001

CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "3001"]
