-- E1/F1 pilot fixture: synthetic, disposable, not the frozen application schema.
-- Two items, two locations, four opening positions, no transfer initially.
-- IDs intentionally remain stable across all E1 trials.
PRAGMA foreign_keys = ON;
BEGIN;
CREATE TABLE item (
    id TEXT PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE
);
CREATE TABLE location (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL
);
CREATE TABLE opening_balance (
    item_id TEXT NOT NULL REFERENCES item(id),
    location_id TEXT NOT NULL REFERENCES location(id),
    quantity INTEGER NOT NULL CHECK (quantity >= 0),
    PRIMARY KEY (item_id, location_id)
);
CREATE TABLE stock_balance (
    item_id TEXT NOT NULL REFERENCES item(id),
    location_id TEXT NOT NULL REFERENCES location(id),
    quantity INTEGER NOT NULL CHECK (quantity >= 0),
    PRIMARY KEY (item_id, location_id)
);
CREATE TABLE transfer (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES item(id),
    source_location_id TEXT NOT NULL REFERENCES location(id),
    destination_location_id TEXT NOT NULL REFERENCES location(id),
    quantity INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 1000000000),
    CHECK (source_location_id <> destination_location_id)
);
CREATE TABLE journal_entry (
    id INTEGER PRIMARY KEY,
    transfer_id TEXT NOT NULL REFERENCES transfer(id),
    item_id TEXT NOT NULL REFERENCES item(id),
    location_id TEXT NOT NULL REFERENCES location(id),
    delta INTEGER NOT NULL
        CHECK (delta BETWEEN -1000000000 AND 1000000000 AND delta <> 0),
    UNIQUE (transfer_id, location_id)
);
INSERT INTO item (id, sku) VALUES
    ('item-bolt', 'BOLT-01'),
    ('item-nut', 'NUT-01');
-- Intentionally unnormalized historical codes for later migration pilots.
INSERT INTO location (id, code) VALUES
    ('loc-north', ' North '),
    ('loc-south', 'south');
INSERT INTO opening_balance (item_id, location_id, quantity) VALUES
    ('item-bolt', 'loc-north', 10),
    ('item-bolt', 'loc-south', 2),
    ('item-nut', 'loc-north', 4),
    ('item-nut', 'loc-south', 8);
INSERT INTO stock_balance (item_id, location_id, quantity)
SELECT item_id, location_id, quantity FROM opening_balance;
COMMIT;
