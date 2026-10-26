# Python 3.14 Alpine, pinned multi-platform manifest.
FROM python@sha256:601e99e090cb08c2784a42395487709500bc39930307fe72f3f11a8f3c430762
RUN apk add --no-cache curl
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 65534:65534
ENTRYPOINT ["python3", "/app/probe.py"]
