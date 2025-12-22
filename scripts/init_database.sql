-- Slack RAG Bot Database Schema
-- Run this script to initialize the Aurora PostgreSQL database
--
-- For Aurora Data API, run via AWS CLI:
--   aws rds-data execute-statement \
--     --resource-arn "$CLUSTER_ARN" \
--     --secret-arn "$SECRET_ARN" \
--     --database "slack_rag" \
--     --sql "$(cat scripts/init_database.sql)"
--
-- For local PostgreSQL:
--   psql -h localhost -U postgres -d slack_rag -f scripts/init_database.sql

-- Enable pgvector extension for vector similarity search
CREATE EXTENSION IF NOT EXISTS vector;

-- Main table for storing Slack message chunks with embeddings
CREATE TABLE IF NOT EXISTS slack_messages (
    -- Primary key: {channel_id}_{message_ts}_{chunk_index}
    id              VARCHAR(255) PRIMARY KEY,

    -- Slack identifiers
    channel_id      VARCHAR(50) NOT NULL,
    channel_name    VARCHAR(255),
    message_ts      VARCHAR(50) NOT NULL,
    chunk_index     INTEGER DEFAULT 0,

    -- Content
    text            TEXT NOT NULL,

    -- Vector embedding (Titan Embeddings: 1536 dimensions)
    embedding       vector(1536) NOT NULL,

    -- Metadata
    user_id         VARCHAR(50),
    user_name       VARCHAR(255),
    permalink       TEXT,
    indexed_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata        JSONB DEFAULT '{}'
);

-- HNSW index for fast approximate nearest neighbor search
-- Using cosine distance (vector_cosine_ops)
-- HNSW is preferred over IVFFlat for:
--   - Better recall at same speed
--   - No need to rebuild after inserts
--   - Works well with incremental data
CREATE INDEX IF NOT EXISTS idx_slack_messages_embedding
ON slack_messages USING hnsw (embedding vector_cosine_ops);

-- Index for filtering by channel
CREATE INDEX IF NOT EXISTS idx_slack_messages_channel
ON slack_messages (channel_id);

-- Index for deduplication and timestamp-based queries
CREATE INDEX IF NOT EXISTS idx_slack_messages_ts
ON slack_messages (message_ts);

-- Composite index for common query pattern (channel + time range)
CREATE INDEX IF NOT EXISTS idx_slack_messages_channel_ts
ON slack_messages (channel_id, message_ts);

-- Index for finding recent messages
CREATE INDEX IF NOT EXISTS idx_slack_messages_indexed_at
ON slack_messages (indexed_at DESC);

-- Function to search for similar messages
-- Usage: SELECT * FROM search_similar_messages('[0.1, 0.2, ...]'::vector, 5, 0.25);
CREATE OR REPLACE FUNCTION search_similar_messages(
    query_embedding vector(1536),
    result_limit INTEGER DEFAULT 5,
    min_similarity FLOAT DEFAULT 0.25,
    channel_filter VARCHAR DEFAULT NULL
)
RETURNS TABLE (
    id VARCHAR,
    channel_name VARCHAR,
    text TEXT,
    permalink TEXT,
    user_name VARCHAR,
    similarity FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        sm.id,
        sm.channel_name,
        sm.text,
        sm.permalink,
        sm.user_name,
        (1 - (sm.embedding <=> query_embedding))::FLOAT AS similarity
    FROM slack_messages sm
    WHERE (1 - (sm.embedding <=> query_embedding)) > min_similarity
      AND (channel_filter IS NULL OR sm.channel_id = channel_filter)
    ORDER BY sm.embedding <=> query_embedding
    LIMIT result_limit;
END;
$$ LANGUAGE plpgsql;

-- Comment on table
COMMENT ON TABLE slack_messages IS 'Indexed Slack message chunks for RAG search';
COMMENT ON COLUMN slack_messages.embedding IS 'Titan Embeddings v1 vector (1536 dimensions)';
