FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt --no-cache-dir

COPY /app/ .

EXPOSE 5000

CMD ["uvicorn", "main:app", "--port", "8000", "--log-config", "conf/log_conf.yaml", "--host","0.0.0.0", "--reload"]