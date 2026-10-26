CREATE TABLE IF NOT EXISTS lots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    key           TEXT UNIQUE NOT NULL,      -- source:external_id
    source        TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    title         TEXT NOT NULL,
    organizer     TEXT,
    region        TEXT,
    published_at  TEXT,
    deadline      TEXT,
    budget        REAL,
    description   TEXT,
    url           TEXT,
    extra         TEXT,
    content_hash  TEXT NOT NULL,             -- для отслеживания изменений
    fingerprint   TEXT NOT NULL,             -- для дублей между источниками
    dup_of        INTEGER REFERENCES lots(id),
    changed       INTEGER DEFAULT 0,         -- лот изменился после первой отправки
    score         INTEGER,
    direction     TEXT,
    explanation   TEXT,
    score_method  TEXT,                      -- rules | llm
    scored        INTEGER DEFAULT 0,
    digested      INTEGER DEFAULT 0,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_lots_fp ON lots(fingerprint);
CREATE INDEX IF NOT EXISTS ix_lots_digest ON lots(scored, digested, score);

CREATE TABLE IF NOT EXISTS runs (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    stage   TEXT NOT NULL,                   -- collect | score | digest
    source  TEXT,
    ok      INTEGER NOT NULL,
    count   INTEGER DEFAULT 0,
    error   TEXT
);
