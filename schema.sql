CREATE TABLE IF NOT EXISTS categories (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE,
    budget REAL                      -- monthly budget, NULL = none
);

CREATE TABLE IF NOT EXISTS rules (
    id          INTEGER PRIMARY KEY,
    pattern     TEXT NOT NULL UNIQUE,  -- case-insensitive substring of description
    category_id INTEGER NOT NULL REFERENCES categories(id)
);

CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY,
    date        TEXT NOT NULL,         -- ISO yyyy-mm-dd
    description TEXT NOT NULL,
    amount      REAL NOT NULL,         -- negative = spending, positive = income
    category_id INTEGER REFERENCES categories(id),
    UNIQUE (date, description, amount)  -- makes re-imports idempotent
);

CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_tx_cat  ON transactions(category_id);
