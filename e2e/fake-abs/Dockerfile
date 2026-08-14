FROM python:3.12-slim-bookworm
WORKDIR /app
COPY server.py /app/server.py
ENV FAKE_ABS_HOST=0.0.0.0
ENV FAKE_ABS_PORT=13378
ENV PYTHONUNBUFFERED=1
EXPOSE 13378
CMD ["python", "-u", "/app/server.py"]
