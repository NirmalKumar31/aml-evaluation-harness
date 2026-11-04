-- Historical behavior for each account. Every frame stops one minute before
-- the current transaction, so the current row and future rows cannot leak in.
CREATE OR REPLACE VIEW history AS
WITH prior_counterparty AS (
    SELECT
        *,
        MAX(event_time) OVER (
            PARTITION BY account_id, counterparty
            ORDER BY event_time
            RANGE BETWEEN UNBOUNDED PRECEDING
                      AND INTERVAL 1 MINUTE PRECEDING
        ) AS previous_counterparty_time
    FROM events
)
SELECT
    txn_id,
    side,
    COUNT(*) OVER w1d AS n_1d,
    COUNT(*) OVER w7d AS n_7d,
    COUNT(*) OVER w30d AS n_30d,
    AVG(amount_paid) OVER w7d AS mean_amt_7d,
    STDDEV_POP(amount_paid) OVER w7d AS std_amt_7d,
    MAX(amount_paid) OVER w30d AS max_amt_30d,
    COALESCE(SUM(is_out) OVER w7d, 0) AS n_out_7d,
    EPOCH(event_time - MAX(event_time) OVER w30d) AS secs_since_prev,
    EPOCH(event_time - previous_counterparty_time) AS secs_since_prev_cp
FROM prior_counterparty
WINDOW
    w1d AS (
        PARTITION BY account_id ORDER BY event_time
        RANGE BETWEEN INTERVAL 1 DAY PRECEDING
                  AND INTERVAL 1 MINUTE PRECEDING
    ),
    w7d AS (
        PARTITION BY account_id ORDER BY event_time
        RANGE BETWEEN INTERVAL 7 DAY PRECEDING
                  AND INTERVAL 1 MINUTE PRECEDING
    ),
    w30d AS (
        PARTITION BY account_id ORDER BY event_time
        RANGE BETWEEN INTERVAL 30 DAY PRECEDING
                  AND INTERVAL 1 MINUTE PRECEDING
    );
