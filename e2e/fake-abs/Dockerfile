FROM python:3.12-alpine
WORKDIR /app
COPY server.py /app/server.py
ENV FAKE_ABS_HOST=0.0.0.0
ENV FAKE_ABS_PORT=13378
EXPOSE 13378
CMD ["python", "/app/server.py"]
