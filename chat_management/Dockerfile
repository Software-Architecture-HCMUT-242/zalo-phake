FROM python:3.10-slim

WORKDIR /code

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt --no-cache-dir --upgrade

COPY ./app /code/app

EXPOSE 5000

CMD ["python", "-m", "uvicorn", "app.main:app", "--port", "8000", "--log-config", "app/conf/log_conf.yaml", "--host","0.0.0.0"]