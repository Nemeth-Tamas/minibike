FROM python:3.12-slim
WORKDIR /opt/pedal
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd -g 10001 pedal \
    && useradd -m -u 10001 -g pedal pedal \
    && mkdir -p /data && chown pedal:pedal /data
COPY app ./app
COPY static ./static
USER pedal
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
