"""Implementation facts verified against the fixed Node 24 dependency image.

These are reference material, not extra packages, tools or app-owned business types.
"""


def runtime_references(database):
    facts={'next_app_router':[
        'app/api/**/route.ts is a server HTTP module. Do not mark a route handler with use client.',
        'Client components call HTTP handlers with fetch; do not import a route handler as a client helper.',
        'Pages/layouts are server modules by default. Use a quoted use client directive only for a client boundary; never import server database code across it.',
        'In this Next.js 16 runtime, dynamic route-handler context.params is a Promise. Type it as Promise<{id: string}> (using your actual segment names) and await context.params before reading values; the old synchronous params object fails the production route-type check.',
    ]}
    if database=='sqlite':
        facts['sqlite']={
            'module':'node:sqlite','export':'DatabaseSync','runtime':'Node server only',
            'connection':"const db = new DatabaseSync(databasePath);",
            'path':'Use process.env.SQLITE_PATH when supplied; create its parent directory with node:fs mkdirSync before opening a file database.',
            'schema':'db.exec(sql) executes your app-owned schema statements.',
            'write':'db.prepare(sql).run(...boundValues) returns changes and lastInsertRowid.',
            'read':'db.prepare(sql).all(...boundValues) returns rows; .get(...boundValues) returns one row. Narrow records into your app-owned types.',
            'parameters':'Use ? placeholders and bound values, rather than interpolating user input into SQL.',
            'api_boundary':'DatabaseSync provides exec/prepare/close, not ORM model properties. Define any app-specific helper interface yourself.',
            'dependencies':'No npm database package is needed. Prisma, @prisma/client, sqlite3 and better-sqlite3 are not installed; do not import them.',
            'initialization':'Next.js production build imports route modules in parallel workers. Avoid opening/migrating a shared SQLite file as an import side effect: initialize lazily in request-time helpers. Concurrent connections need a bounded busy timeout before schema/journal changes (for example db.exec("PRAGMA busy_timeout = 5000")).',
        }
    return facts
