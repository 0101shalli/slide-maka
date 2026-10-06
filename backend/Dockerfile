FROM ubuntu:22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    libreoffice \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
ENV PIP_DEFAULT_TIMEOUT=200
ENV PIP_RETRIES=20
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python3 -m pip install --upgrade pip setuptools wheel
RUN python3 -m pip install --no-cache-dir --default-timeout=200 --retries=20 \
    --trusted-host pypi.org --trusted-host files.pythonhosted.org \
    -r requirements.txt

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
