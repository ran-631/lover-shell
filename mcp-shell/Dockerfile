FROM python:3.11-slim

# 系统工具 - 写在这里就不会丢
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl wget ssh nano \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["python", "app.py"]
