# Деплой на VPS

Бот работает на VPS FirstVDS (Нидерланды, Ubuntu 24.04, Docker) в контейнере
из `docker-compose.yml`. Сервер держит несколько ботов: каждый — в своей папке
`/opt/bots/<имя>/` со своими `.env` и `data/`.

## Где что лежит

| Путь | Что это |
|---|---|
| `/opt/bots/maf-event-bot/` | клон репозитория, переключён на тэг релиза |
| `/opt/bots/maf-event-bot/.env` | токен и `TZ=Asia/Yekaterinburg` (права 600, в git не попадает) |
| `/opt/bots/maf-event-bot/data/bot.db` | база SQLite |
| `/opt/bots/backup.sh` | бэкап баз всех ботов (копия — `deploy/backup.sh`) |
| `/etc/cron.d/bots-backup` | запуск бэкапа ежедневно в 03:30 |
| `/opt/backups/<дата>/` | копии баз, хранятся 14 дней |
| `/etc/docker/daemon.json` | ротация логов: 3 файла по 10 МБ на контейнер |

Вход по SSH — только по ключу, пароль отключён. Если ключ потерян — VNC-консоль
в панели FirstVDS.

## Обновление до нового релиза

```bash
cd /opt/bots/maf-event-bot
git fetch --tags
git checkout vX.Y.Z
docker compose up -d --build
docker compose logs --tail 20
```

Откат — то же самое с предыдущим тэгом. Перед обновлением, которое меняет схему
базы, стоит вручную запустить `/opt/bots/backup.sh`.

## Настройка нового сервера

1. Docker с плагином compose и `sqlite3`.
2. Ротация логов в `/etc/docker/daemon.json`:
   ```json
   { "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }
   ```
3. `git clone https://github.com/kam1kk/maf-event-bot.git /opt/bots/maf-event-bot`,
   `git checkout` нужного тэга.
4. Положить `.env` и `data/bot.db`. `TZ` обязателен: в контейнере системное
   время — UTC, а у групп без своего пояса время считается по `TZ`.
5. `docker compose up -d --build`.
6. `deploy/backup.sh` → `/opt/bots/backup.sh`, в `/etc/cron.d/bots-backup`:
   `30 3 * * * root /opt/bots/backup.sh`.

Один токен — один запущенный экземпляр: пока бот работает на сервере, локально
его не запускать, иначе Telegram отвечает `Conflict: terminated by other
getUpdates request`.
