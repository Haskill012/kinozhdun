FROM mcr.microsoft.com/playwright/python:v1.56.0-noble

RUN pip install --no-cache-dir playwright==1.56.0
WORKDIR /app
COPY uploader.py /app/uploader.py
CMD ["python", "/app/uploader.py", "watch"]
