# zalo-phake


# Run chat backend local
```bash
docker compose -f chat_management/local/docker-compose.yml up -d

cd chat_management

uvicorn app.main:app --reload --log-config app/conf/log_conf.yaml --host 0.0.0.0 --port 3000
```