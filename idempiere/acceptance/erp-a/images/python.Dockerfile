# ERP-A harness test issuer. CI and local integration only.
FROM mirror.gcr.io/library/python:3.12-slim
COPY wheels /wheels
RUN pip install --no-index --find-links /wheels cryptography && rm -rf /wheels
COPY issuer/issuer.py /app/
USER 65532:65532
