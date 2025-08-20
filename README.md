
# Chat WS (Heroku/Railway Ready)

## Deploy
- **Heroku**: Add Heroku Postgres → `DATABASE_URL` auto. Set `JWT_SECRET`. Procfile already provided.
- **Railway**: Start command `uvicorn server:app --host 0.0.0.0 --port $PORT`. Set `JWT_SECRET`. Add Railway Postgres or use SQLite with Volume (`SQLITE_PATH=/data/chat.db`).

## Health
- `GET /health` → `{"ok": true}`

## Endpoints
- `POST /api/signup` {username, password, display_name?}
- `POST /api/login` {username, password}
- `POST /api/refresh` {token}
- `GET /api/search-users?q=` (Bearer)
- `GET /api/dialogs` (Bearer)
- `GET /api/dm?with=<peer>&limit=200` (Bearer)
- `GET /api/room?room=<room>&limit=200` (Bearer)

## WebSockets
- `/ws/notify?token=...`
- `/ws/dm/{peer}?token=...`
- `/ws/room/{room}?token=...`

## Notes
- Postgres autocommit enabled (no manual commit needed).
- On startup, migrates `users.pwd_hash` → `users.pass_sha256` if needed.
