FROM python:3.12-slim
WORKDIR /opt/sim
RUN pip install --no-cache-dir 'paho-mqtt>=2.1,<3'
COPY simulate.py .
ENTRYPOINT ["python", "simulate.py"]
CMD ["--rpm", "65", "--count", "120"]
