FROM python:3.12-alpine
RUN pip install --no-cache-dir requests==2.32.5
COPY app.py /app.py
CMD ["python3", "-u", "/app.py"]
