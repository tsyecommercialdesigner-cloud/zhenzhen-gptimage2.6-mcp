CREATE TABLE schema_migrations (
  version INTEGER PRIMARY KEY CHECK(version > 0),
  applied_at INTEGER NOT NULL,
  checksum TEXT NOT NULL
) STRICT;
CREATE TABLE batches (
  batch_id TEXT PRIMARY KEY NOT NULL,
  created_at INTEGER NOT NULL
) STRICT;
CREATE TABLE prompt_templates (
  code TEXT PRIMARY KEY NOT NULL COLLATE BINARY
    CHECK(length(code) BETWEEN 1 AND 64 AND code NOT GLOB '*[^A-Za-z0-9_-]*'),
  version INTEGER NOT NULL CHECK(version >= 1),
  content TEXT NOT NULL CHECK(length(CAST(content AS BLOB)) BETWEEN 1 AND 32768),
  variables_json TEXT NOT NULL CHECK(json_valid(variables_json) AND json_type(variables_json)='array'),
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL CHECK(updated_at >= created_at)
) STRICT;
CREATE TABLE tasks (
  task_id TEXT PRIMARY KEY NOT NULL,
  batch_id TEXT REFERENCES batches(batch_id) ON DELETE RESTRICT,
  idempotency_key TEXT NOT NULL UNIQUE CHECK(length(idempotency_key) BETWEEN 1 AND 128),
  channel TEXT NOT NULL CHECK(channel IN ('images','flux','chat')),
  family TEXT NOT NULL CHECK(family IN ('flare','sunburst')),
  width INTEGER CHECK(width BETWEEN 1 AND 4096),
  height INTEGER CHECK(height BETWEEN 1 AND 4096),
  resolved_model TEXT NOT NULL,
  input_digest TEXT NOT NULL CHECK(length(input_digest)=64),
  resolved_digest TEXT NOT NULL CHECK(length(resolved_digest)=64),
  snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json) AND json_type(snapshot_json)='object'),
  status TEXT NOT NULL CHECK(status IN ('queued','submitting','retry_wait','materializing',
    'recovery_pending','unknown','succeeded','failed','expired','cancelled','closed')),
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  deadline_at INTEGER NOT NULL CHECK(deadline_at=created_at+600000),
  attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count BETWEEN 0 AND 3),
  next_attempt_at INTEGER,
  response_ref TEXT,
  error_category TEXT,
  error_message TEXT,
  revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
  CHECK((channel='chat' AND width IS NULL AND height IS NULL AND
    resolved_model IN ('gpt-image-2.6-' || family, 'gpt-image-2.6-' || family || '-2k', 'gpt-image-2.6-' || family || '-4k')) OR
    (channel IN ('images','flux') AND width IS NOT NULL AND height IS NOT NULL AND
    resolved_model = 'gpt-image-2.6-' || family ||
    CASE WHEN max(width,height)<=1024 THEN ''
         WHEN max(width,height)<=2048 THEN '-2k' ELSE '-4k' END)),
  CHECK(status <> 'retry_wait' OR next_attempt_at IS NOT NULL)
) STRICT;
CREATE TABLE batch_items (
  batch_id TEXT NOT NULL REFERENCES batches(batch_id) ON DELETE RESTRICT,
  input_index INTEGER NOT NULL CHECK(input_index BETWEEN 0 AND 19),
  task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
  reused INTEGER NOT NULL CHECK(reused IN (0,1)),
  PRIMARY KEY(batch_id,input_index)
) STRICT;
CREATE TABLE attempts (
  task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
  attempt_no INTEGER NOT NULL CHECK(attempt_no BETWEEN 1 AND 3),
  started_at INTEGER NOT NULL,
  finished_at INTEGER,
  submission_certainty TEXT NOT NULL CHECK(submission_certainty IN
    ('prepared','not_sent','unknown','response_received','rejected')),
  http_status INTEGER CHECK(http_status BETWEEN 100 AND 599),
  error_category TEXT,
  error_message TEXT,
  response_ref TEXT,
  PRIMARY KEY(task_id,attempt_no),
  CHECK(finished_at IS NULL OR finished_at>=started_at)
) STRICT;
CREATE TABLE reference_assets (
  asset_id TEXT PRIMARY KEY NOT NULL,
  task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
  input_index INTEGER NOT NULL CHECK(input_index BETWEEN 0 AND 3),
  local_path TEXT NOT NULL,
  source_kind TEXT NOT NULL CHECK(source_kind='local_file'),
  sha256 TEXT NOT NULL CHECK(length(sha256)=64),
  mime_type TEXT NOT NULL,
  bytes INTEGER NOT NULL CHECK(bytes>0),
  width INTEGER NOT NULL CHECK(width>0),
  height INTEGER NOT NULL CHECK(height>0),
  UNIQUE(task_id,input_index)
) STRICT;
CREATE TABLE image_artifacts (
  task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
  image_index INTEGER NOT NULL CHECK(image_index BETWEEN 0 AND 3),
  local_path TEXT NOT NULL UNIQUE,
  sha256 TEXT NOT NULL CHECK(length(sha256)=64),
  mime_type TEXT NOT NULL,
  bytes INTEGER NOT NULL CHECK(bytes>0),
  width INTEGER NOT NULL CHECK(width>0),
  height INTEGER NOT NULL CHECK(height>0),
  revised_prompt TEXT,
  created_at INTEGER NOT NULL,
  PRIMARY KEY(task_id,image_index)
) STRICT;
CREATE TABLE closure_records (
  task_id TEXT PRIMARY KEY NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
  previous_status TEXT NOT NULL CHECK(previous_status IN ('unknown','recovery_pending')),
  reason TEXT NOT NULL CHECK(length(reason) BETWEEN 1 AND 1024),
  closed_at INTEGER NOT NULL
) STRICT;
CREATE TABLE task_events (
  event_id INTEGER PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
  from_status TEXT,
  to_status TEXT NOT NULL,
  reason_code TEXT NOT NULL,
  created_at INTEGER NOT NULL
) STRICT;
CREATE INDEX tasks_history ON tasks(created_at DESC,task_id DESC);
CREATE INDEX tasks_status_history ON tasks(status,created_at DESC,task_id DESC);
CREATE INDEX tasks_model_history ON tasks(resolved_model,created_at DESC,task_id DESC);
CREATE INDEX tasks_ready ON tasks(status,next_attempt_at,created_at,task_id);
CREATE INDEX batch_items_task ON batch_items(task_id);
CREATE INDEX task_events_task ON task_events(task_id,event_id);
