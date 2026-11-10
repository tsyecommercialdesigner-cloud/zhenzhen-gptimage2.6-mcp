CREATE TABLE artifact_retention_policy (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
  enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
  updated_at INTEGER NOT NULL
);
INSERT INTO artifact_retention_policy(singleton, enabled, updated_at) VALUES (1, 0, 0);

CREATE TABLE artifact_cleanup_events (
  event_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  image_index INTEGER NOT NULL,
  source_path TEXT NOT NULL,
  expected_sha256 TEXT NOT NULL,
  expected_bytes INTEGER NOT NULL CHECK (expected_bytes >= 0),
  trigger_kind TEXT NOT NULL CHECK (trigger_kind IN ('manual', 'automatic')),
  plan_id TEXT,
  state TEXT NOT NULL CHECK (state IN ('intent', 'deleted', 'skipped', 'failed', 'uncertain')),
  detail TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  FOREIGN KEY (task_id, image_index) REFERENCES image_artifacts(task_id, image_index) ON DELETE RESTRICT
);
CREATE INDEX artifact_cleanup_events_artifact ON artifact_cleanup_events(task_id, image_index, created_at);

CREATE TABLE artifact_cleanup_status (
  task_id TEXT NOT NULL,
  image_index INTEGER NOT NULL,
  cleaned_at INTEGER NOT NULL,
  event_id TEXT NOT NULL REFERENCES artifact_cleanup_events(event_id) ON DELETE RESTRICT,
  PRIMARY KEY (task_id, image_index),
  FOREIGN KEY (task_id, image_index) REFERENCES image_artifacts(task_id, image_index) ON DELETE RESTRICT
);

CREATE TABLE auxiliary_cleanup_events (
  event_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
  kind TEXT NOT NULL CHECK (kind IN ('response_body', 'response_manifest', 'reference_snapshot')),
  source_path TEXT NOT NULL,
  expected_sha256 TEXT NOT NULL,
  expected_bytes INTEGER NOT NULL CHECK (expected_bytes >= 0),
  trigger_kind TEXT NOT NULL CHECK (trigger_kind IN ('manual', 'automatic')),
  plan_id TEXT,
  state TEXT NOT NULL CHECK (state IN ('intent', 'deleted', 'skipped', 'failed', 'uncertain')),
  detail TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX auxiliary_cleanup_events_path ON auxiliary_cleanup_events(task_id, source_path, created_at);
