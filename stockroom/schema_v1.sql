CREATE TABLE item (
    id ANY NOT NULL PRIMARY KEY CHECK (
        typeof(id) = 'text' AND instr(id, char(0)) = 0
        AND id GLOB '[A-Za-z0-9]*' AND id NOT GLOB '*[^A-Za-z0-9._-]*'
    ),
    sku TEXT NOT NULL UNIQUE CHECK (length(trim(sku)) > 0)
) STRICT;

CREATE TABLE location (
    id ANY NOT NULL PRIMARY KEY CHECK (
        typeof(id) = 'text' AND instr(id, char(0)) = 0
        AND id GLOB '[A-Za-z0-9]*' AND id NOT GLOB '*[^A-Za-z0-9._-]*'
    ),
    code TEXT NOT NULL CHECK (length(trim(code)) > 0)
) STRICT;

CREATE TABLE opening_balance (
    item_id ANY NOT NULL REFERENCES item(id),
    location_id ANY NOT NULL REFERENCES location(id),
    quantity ANY NOT NULL CHECK (typeof(quantity) = 'integer' AND quantity >= 0),
    PRIMARY KEY (item_id, location_id)
) STRICT;

CREATE TABLE stock_balance (
    item_id ANY NOT NULL,
    location_id ANY NOT NULL,
    quantity ANY NOT NULL CHECK (typeof(quantity) = 'integer' AND quantity >= 0),
    PRIMARY KEY (item_id, location_id),
    FOREIGN KEY (item_id, location_id) REFERENCES opening_balance(item_id, location_id)
) STRICT;

CREATE TABLE transfer (
    id ANY NOT NULL PRIMARY KEY CHECK (
        typeof(id) = 'text' AND instr(id, char(0)) = 0
        AND id GLOB '[A-Za-z0-9]*' AND id NOT GLOB '*[^A-Za-z0-9._-]*'
    ),
    item_id ANY NOT NULL,
    source_location_id ANY NOT NULL,
    destination_location_id ANY NOT NULL,
    quantity ANY NOT NULL CHECK (typeof(quantity) = 'integer' AND quantity BETWEEN 1 AND 1000000000),
    CHECK (source_location_id <> destination_location_id),
    FOREIGN KEY (item_id, source_location_id) REFERENCES opening_balance(item_id, location_id),
    FOREIGN KEY (item_id, destination_location_id) REFERENCES opening_balance(item_id, location_id)
) STRICT;

CREATE TABLE journal_entry (
    id INTEGER PRIMARY KEY,
    transfer_id ANY NOT NULL REFERENCES transfer(id),
    item_id ANY NOT NULL,
    location_id ANY NOT NULL,
    delta ANY NOT NULL CHECK (
        typeof(delta) = 'integer' AND delta BETWEEN -1000000000 AND 1000000000 AND delta <> 0
    ),
    UNIQUE (transfer_id, location_id),
    FOREIGN KEY (item_id, location_id) REFERENCES opening_balance(item_id, location_id)
) STRICT;
