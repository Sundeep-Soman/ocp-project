# Slim (~170MB) image using ubi9-minimal + python3.11 runtime only.
# Build: podman build -t docker.io/imsundeepdocker/ocp-lab:sre-monitor-2.0.0 -f Containerfile .
# Push:  podman push docker.io/imsundeepdocker/ocp-lab:sre-monitor-2.0.0
FROM registry.access.redhat.com/ubi9/ubi-minimal:latest
RUN microdnf install -y python3.11 && microdnf clean all
WORKDIR /app
COPY app.py /app/app.py
ENV PORT=8080 APP_VERSION=2.0.0 WARMUP_SECONDS=5 ALERT_THRESHOLD=0
EXPOSE 8080
USER 1001
CMD ["python3.11", "/app/app.py"]
