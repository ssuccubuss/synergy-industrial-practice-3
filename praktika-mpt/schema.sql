CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    cohort TEXT NOT NULL,
    profile TEXT NOT NULL,
    resume TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS places (
    id INTEGER PRIMARY KEY,
    organization_id INTEGER NOT NULL REFERENCES organizations(id),
    title TEXT NOT NULL,
    profile TEXT NOT NULL,
    capacity INTEGER NOT NULL CHECK(capacity BETWEEN 1 AND 100)
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    login TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('coordinator', 'student', 'partner')),
    student_id INTEGER UNIQUE REFERENCES students(id),
    organization_id INTEGER REFERENCES organizations(id),
    CHECK(
        (role = 'student' AND student_id IS NOT NULL AND organization_id IS NULL)
        OR (role = 'partner' AND student_id IS NULL AND organization_id IS NOT NULL)
        OR (role = 'coordinator' AND student_id IS NULL AND organization_id IS NULL)
    )
);
CREATE TABLE IF NOT EXISTS preferences (
    student_id INTEGER NOT NULL REFERENCES students(id),
    place_id INTEGER NOT NULL REFERENCES places(id),
    rank INTEGER NOT NULL CHECK(rank BETWEEN 1 AND 3),
    PRIMARY KEY (student_id, place_id),
    UNIQUE (student_id, rank)
);
CREATE TABLE IF NOT EXISTS feedback (
    student_id INTEGER NOT NULL,
    place_id INTEGER NOT NULL,
    comment TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (student_id, place_id),
    FOREIGN KEY (student_id, place_id) REFERENCES preferences(student_id, place_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS assignments (
    student_id INTEGER PRIMARY KEY REFERENCES students(id),
    place_id INTEGER NOT NULL REFERENCES places(id),
    rank INTEGER NOT NULL CHECK(rank BETWEEN 1 AND 3),
    published INTEGER NOT NULL DEFAULT 0 CHECK(published IN (0, 1)),
    FOREIGN KEY (student_id, place_id) REFERENCES preferences(student_id, place_id)
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY,
    login TEXT NOT NULL,
    event TEXT NOT NULL,
    recorded TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

