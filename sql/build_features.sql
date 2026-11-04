-- Final model input: 12 transaction features plus 10 sender-history and
-- 10 receiver-history features. The Python layer writes this view to Parquet.
CREATE OR REPLACE VIEW feature_table AS
SELECT
    tx.txn_id,
    tx.event_time,
    tx.event_date,
    tx.sender_id,
    tx.receiver_id,
    tx.is_laundering,

    LN(1 + tx.amount_paid) AS log_amount_paid,
    LN(1 + tx.amount_received) AS log_amount_received,
    tx.amount_received / NULLIF(tx.amount_paid, 0) AS fx_ratio,
    CAST(tx.payment_currency <> tx.receiving_currency AS TINYINT) AS currency_mismatch,
    CASE
        WHEN tx.amount_paid = ROUND(tx.amount_paid, -3) THEN 3
        WHEN tx.amount_paid = ROUND(tx.amount_paid, -2) THEN 2
        WHEN tx.amount_paid = ROUND(tx.amount_paid, 0) THEN 1
        ELSE 0
    END AS amount_roundness,
    HOUR(tx.event_time) AS hour,
    DAYOFWEEK(tx.event_time) AS dayofweek,
    CAST(DAYOFWEEK(tx.event_time) IN (0, 6) AS TINYINT) AS is_weekend,
    CAST(tx.sender_id = tx.receiver_id AS TINYINT) AS is_self_transfer,
    CAST(tx.sender_bank <> tx.receiver_bank AS TINYINT) AS is_cross_bank,
    HASH(tx.payment_format) % 1000 AS payment_format_code,
    HASH(tx.payment_currency) % 1000 AS payment_currency_code,

    hs.n_1d AS s_n_1d,
    hs.n_7d AS s_n_7d,
    hs.n_30d AS s_n_30d,
    hs.mean_amt_7d AS s_mean_amt_7d,
    hs.std_amt_7d AS s_std_amt_7d,
    hs.max_amt_30d AS s_max_amt_30d,
    hs.n_out_7d AS s_n_out_7d,
    hs.secs_since_prev AS s_secs_since_prev,
    hs.secs_since_prev_cp AS s_secs_since_prev_cp,
    tx.amount_paid / NULLIF(hs.mean_amt_7d, 0) AS s_amt_vs_hist,

    hr.n_1d AS r_n_1d,
    hr.n_7d AS r_n_7d,
    hr.n_30d AS r_n_30d,
    hr.mean_amt_7d AS r_mean_amt_7d,
    hr.std_amt_7d AS r_std_amt_7d,
    hr.max_amt_30d AS r_max_amt_30d,
    hr.n_out_7d AS r_n_out_7d,
    hr.secs_since_prev AS r_secs_since_prev,
    hr.secs_since_prev_cp AS r_secs_since_prev_cp,
    tx.amount_paid / NULLIF(hr.mean_amt_7d, 0) AS r_amt_vs_hist

FROM tx
LEFT JOIN history hs
    ON hs.txn_id = tx.txn_id
   AND hs.side = 's'
LEFT JOIN history hr
    ON hr.txn_id = tx.txn_id
   AND hr.side = 'r';
