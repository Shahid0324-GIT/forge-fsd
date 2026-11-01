# Generated task application

Requires Node 24 and npm. SQLite uses the Node built-in `node:sqlite` API;
its maturity depends on the pinned Node release and experimental warnings may appear.

```sh
npm ci --ignore-scripts
npm run build
npm start -- --port 3000
```

Visit localhost:3000. `SQLITE_PATH` defaults to `./data/tasks.sqlite3`.
The database schema initializes on first API access. No credentials are required.
Back up the data directory for persistence. This template has no authentication;
it is intended for a local single-user demo. Local SQLite is not a persistent
database solution for Vercel Functions. PostgreSQL deployment support is not yet implemented.

ForgeFSD verification should use its isolated runner rather than executing untrusted
generated code directly on the host. This file alone is not verification evidence.
