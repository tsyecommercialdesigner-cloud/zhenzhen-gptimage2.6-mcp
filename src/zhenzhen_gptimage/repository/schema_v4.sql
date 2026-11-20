CREATE TABLE static_size_candidates (
  task_id TEXT PRIMARY KEY REFERENCES tasks(task_id) ON DELETE RESTRICT,
  digest TEXT NOT NULL CHECK(length(digest)=64),
  accepted_at INTEGER
) STRICT;
CREATE TABLE recovery_exports (
  id INTEGER PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE RESTRICT,
  image_index INTEGER NOT NULL,
  sha256 TEXT NOT NULL CHECK(length(sha256)=64),
  created_at INTEGER NOT NULL
) STRICT;
