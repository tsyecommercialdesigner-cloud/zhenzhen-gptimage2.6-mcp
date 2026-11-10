-- Rebuild only tasks to allow an unspecified canvas for SVG/GIF. Other tables
-- continue to refer to tasks; migration runs with legacy rename semantics.
ALTER TABLE tasks RENAME TO tasks_v1;
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
    CASE WHEN max(width,height)<=1024 THEN '' WHEN max(width,height)<=2048 THEN '-2k' ELSE '-4k' END) OR
    (channel IN ('images','flux') AND width IS NULL AND height IS NULL AND
    resolved_model IN ('gpt-image-2.6-' || family, 'gpt-image-2.6-' || family || '-2k', 'gpt-image-2.6-' || family || '-4k'))),
  CHECK(status <> 'retry_wait' OR next_attempt_at IS NOT NULL)
) STRICT;
INSERT INTO tasks SELECT * FROM tasks_v1;
DROP TABLE tasks_v1;
CREATE INDEX tasks_history ON tasks(created_at DESC,task_id DESC);
CREATE INDEX tasks_status_history ON tasks(status,created_at DESC,task_id DESC);
CREATE INDEX tasks_model_history ON tasks(resolved_model,created_at DESC,task_id DESC);
CREATE INDEX tasks_ready ON tasks(status,next_attempt_at,created_at,task_id);

-- Extension tables preserve the v1 tasks and their original snapshots/digests.
CREATE TABLE task_format_options (
  task_id TEXT PRIMARY KEY NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
  snapshot_version INTEGER NOT NULL CHECK(snapshot_version >= 1),
  provider TEXT NOT NULL,
  output_format TEXT NOT NULL CHECK(output_format IN ('gif','svg')),
  size_policy TEXT NOT NULL CHECK(size_policy IN ('strict','accept_actual')),
  options_json TEXT NOT NULL CHECK(json_valid(options_json) AND json_type(options_json)='object')
) STRICT;
CREATE TABLE remote_tasks (
  task_id TEXT PRIMARY KEY NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
  provider TEXT NOT NULL,
  remote_id TEXT NOT NULL,
  remote_status TEXT,
  updated_at INTEGER NOT NULL,
  UNIQUE(provider, remote_id)
) STRICT;
CREATE TABLE image_format_metadata (
  task_id TEXT NOT NULL,
  image_index INTEGER NOT NULL,
  metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
  PRIMARY KEY(task_id,image_index),
  FOREIGN KEY(task_id,image_index) REFERENCES image_artifacts(task_id,image_index) ON DELETE RESTRICT
) STRICT;
CREATE TABLE image_acceptance_records (
  task_id TEXT PRIMARY KEY NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
  sha256 TEXT NOT NULL CHECK(length(sha256)=64),
  width INTEGER NOT NULL CHECK(width>0),
  height INTEGER NOT NULL CHECK(height>0),
  accepted_at INTEGER NOT NULL,
  reason TEXT NOT NULL
) STRICT;
CREATE TABLE pending_image_artifacts (
  task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
  image_index INTEGER NOT NULL,
  local_path TEXT NOT NULL,
  sha256 TEXT NOT NULL CHECK(length(sha256)=64),
  mime_type TEXT NOT NULL,
  bytes INTEGER NOT NULL CHECK(bytes>0),
  width INTEGER NOT NULL CHECK(width>0),
  height INTEGER NOT NULL CHECK(height>0),
  revised_prompt TEXT,
  metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)),
  PRIMARY KEY(task_id,image_index)
) STRICT;
