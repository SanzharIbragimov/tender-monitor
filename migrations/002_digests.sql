-- Журнал отправленных дайджестов: для проверки доставки и доли повторов (п. 9 ТЗ)
CREATE TABLE IF NOT EXISTS digests (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL,
    subject  TEXT,
    count    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS digest_items (
    digest_id    INTEGER NOT NULL REFERENCES digests(id),
    lot_id       INTEGER NOT NULL REFERENCES lots(id),
    fingerprint  TEXT NOT NULL,
    changed      INTEGER DEFAULT 0     -- лот повторно отправлен из-за изменения условий
);
CREATE INDEX IF NOT EXISTS ix_digest_items_fp ON digest_items(fingerprint);
