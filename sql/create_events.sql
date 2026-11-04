-- Give every transaction a sender view and a receiver view.
-- UNION ALL keeps both perspectives and does not waste time deduplicating them.
CREATE OR REPLACE VIEW events AS
SELECT
    txn_id,
    's' AS side,
    sender_id AS account_id,
    receiver_id AS counterparty,
    event_time,
    amount_paid,
    1 AS is_out
FROM tx

UNION ALL

SELECT
    txn_id,
    'r' AS side,
    receiver_id AS account_id,
    sender_id AS counterparty,
    event_time,
    amount_paid,
    0 AS is_out
FROM tx;
