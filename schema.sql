CREATE TABLE IF NOT EXISTS messages (
    transaction_id VARCHAR(255) PRIMARY KEY,
    payload JSONB NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    next_retry_at TIMESTAMPTZ,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    CONSTRAINT valid_status CHECK (
        status IN ('pending', 'processing', 'success', 'failed', 'dead_letter')
    )
);


CREATE INDEX IF NOT EXISTS idx_status_retry 
ON messages(status, next_retry_at) 
WHERE status = 'failed';


CREATE INDEX IF NOT EXISTS idx_processing_updated 
ON messages(updated_at) 
WHERE status = 'processing';