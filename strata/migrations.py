"""Ordered, additive-only migrations. Never edit an applied step; append a new one.

Steps are SQL strings or Python callables taking the connection (for changes
SQLite cannot express in SQL, like widening a CHECK constraint).
"""


def _workspaces_v7(conn) -> None:
    """Allow kind='growth' and add per-workspace feature flags.

    SQLite cannot alter a CHECK constraint, so rebuild the table. Foreign keys
    are disabled for the rebuild; a DROP with them on would fire ON DELETE SET
    NULL into tasks and classes.
    """
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        with conn:
            conn.executescript(
                """
                CREATE TABLE workspaces_new (
                  id INTEGER PRIMARY KEY,
                  name TEXT NOT NULL,
                  kind TEXT NOT NULL DEFAULT 'job'
                    CHECK (kind IN ('job','school','growth')),
                  has_waiting INTEGER NOT NULL DEFAULT 0,
                  has_agendas INTEGER NOT NULL DEFAULT 0,
                  position INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL DEFAULT (datetime('now')),
                  archived_at TEXT
                );
                INSERT INTO workspaces_new
                  (id, name, kind, position, created_at, archived_at)
                  SELECT id, name, kind, position, created_at, archived_at
                  FROM workspaces;
                DROP TABLE workspaces;
                ALTER TABLE workspaces_new RENAME TO workspaces;
                """
            )
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        -- NOW + NUISANCES
        CREATE TABLE tasks (
          id INTEGER PRIMARY KEY,
          title TEXT NOT NULL,
          notes TEXT NOT NULL DEFAULT '',
          horizon TEXT NOT NULL DEFAULT 'inbox'
            CHECK (horizon IN ('inbox','today','next','horizon')),
          context TEXT NOT NULL DEFAULT '' CHECK (context IN ('','job','personal')),
          nuisance INTEGER NOT NULL DEFAULT 0,
          pinned INTEGER NOT NULL DEFAULT 0,
          snoozed_until TEXT,
          position INTEGER NOT NULL DEFAULT 0,
          done_at TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX idx_tasks_horizon ON tasks(horizon, done_at, position);

        -- PACK: trips snapshot-copy labels so template edits never mutate past trips
        CREATE TABLE pack_templates (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE pack_template_items (
          id INTEGER PRIMARY KEY,
          template_id INTEGER NOT NULL REFERENCES pack_templates(id) ON DELETE CASCADE,
          label TEXT NOT NULL,
          position INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE trips (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','closed')),
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          closed_at TEXT
        );
        CREATE TABLE trip_templates (
          trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          template_id INTEGER NOT NULL REFERENCES pack_templates(id) ON DELETE CASCADE,
          PRIMARY KEY (trip_id, template_id)
        );
        CREATE TABLE trip_items (
          id INTEGER PRIMARY KEY,
          trip_id INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
          label TEXT NOT NULL,
          checked INTEGER NOT NULL DEFAULT 0,
          position INTEGER NOT NULL DEFAULT 0,
          source_template_item_id INTEGER REFERENCES pack_template_items(id) ON DELETE SET NULL,
          added_during_trip INTEGER NOT NULL DEFAULT 0,
          offer_status TEXT CHECK (offer_status IN ('accepted','dismissed'))
        );

        -- MODEL
        CREATE TABLE boards (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          notes TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          archived_at TEXT
        );
        CREATE TABLE buckets (
          id INTEGER PRIMARY KEY,
          board_id INTEGER NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          position INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE cards (
          id INTEGER PRIMARY KEY,
          bucket_id INTEGER NOT NULL REFERENCES buckets(id) ON DELETE CASCADE,
          title TEXT NOT NULL,
          notes TEXT NOT NULL DEFAULT '',
          position INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- LEARN: lock state is derived, never stored
        CREATE TABLE tracks (
          id INTEGER PRIMARY KEY,
          slug TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          position INTEGER NOT NULL DEFAULT 0,
          touched_at TEXT
        );
        CREATE TABLE nodes (
          id INTEGER PRIMARY KEY,
          track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
          slug TEXT NOT NULL,
          title TEXT NOT NULL,
          summary TEXT NOT NULL DEFAULT '',
          origin TEXT NOT NULL DEFAULT 'seed' CHECK (origin IN ('seed','user','ai')),
          position INTEGER NOT NULL DEFAULT 0,
          done_at TEXT,
          UNIQUE (track_id, slug)
        );
        CREATE TABLE node_edges (
          prereq_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
          node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
          origin TEXT NOT NULL DEFAULT 'seed' CHECK (origin IN ('seed','user','ai')),
          PRIMARY KEY (prereq_id, node_id),
          CHECK (prereq_id <> node_id)
        );
        CREATE INDEX idx_edges_node ON node_edges(node_id);
        CREATE TABLE suggestions (
          id INTEGER PRIMARY KEY,
          track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
          payload TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending','accepted','dismissed')),
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          resolved_at TEXT
        );
        """,
    ),
    (
        2,
        """
        -- Where a task came from ('', 'api', 'slack', 'granola', ...).
        ALTER TABLE tasks ADD COLUMN source TEXT NOT NULL DEFAULT '';

        -- SCHOOL: classes and assignments, sorted by deadline and burden
        CREATE TABLE classes (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          canvas_course_id INTEGER UNIQUE,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          archived_at TEXT
        );
        CREATE TABLE assignments (
          id INTEGER PRIMARY KEY,
          class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
          title TEXT NOT NULL,
          notes TEXT NOT NULL DEFAULT '',
          due_date TEXT,
          burden TEXT NOT NULL DEFAULT 'm' CHECK (burden IN ('s','m','l')),
          canvas_id INTEGER UNIQUE,
          done_at TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX idx_assignments_due ON assignments(done_at, due_date);

        -- EVENINGS: quick after-work lists with approximate time blocks
        CREATE TABLE evening_plans (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          start_time TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          archived_at TEXT
        );
        CREATE TABLE evening_items (
          id INTEGER PRIMARY KEY,
          plan_id INTEGER NOT NULL REFERENCES evening_plans(id) ON DELETE CASCADE,
          title TEXT NOT NULL,
          minutes INTEGER NOT NULL DEFAULT 30,
          done INTEGER NOT NULL DEFAULT 0,
          position INTEGER NOT NULL DEFAULT 0
        );
        """,
    ),
    (
        3,
        """
        -- Personalization: display names and labels, the seed of a future
        -- product onboarding survey. Keys: name, job_label, ...
        CREATE TABLE prefs (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        """,
    ),
    (
        4,
        """
        -- Conversations parsed from a ChatGPT data export, awaiting triage
        -- into the learn trees.
        CREATE TABLE imported_chats (
          id INTEGER PRIMARY KEY,
          title TEXT NOT NULL,
          chat_created TEXT,
          digest TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','used','dismissed')),
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
    ),
    (
        5,
        """
        -- Recurring life upkeep. No streaks stored on purpose: only when it
        -- was last done, so being late never accumulates guilt.
        CREATE TABLE routines (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          every_days INTEGER NOT NULL DEFAULT 7,
          last_done TEXT,
          preset_key TEXT UNIQUE,
          active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
    ),
    (
        6,
        """
        -- Work areas are additive, not a fixed job/school pair: one per job,
        -- school, side gig. Kind decides which machinery a section gets.
        CREATE TABLE workspaces (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          kind TEXT NOT NULL DEFAULT 'job' CHECK (kind IN ('job','school')),
          position INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          archived_at TEXT
        );
        ALTER TABLE tasks ADD COLUMN workspace_id INTEGER
          REFERENCES workspaces(id) ON DELETE SET NULL;
        ALTER TABLE classes ADD COLUMN workspace_id INTEGER
          REFERENCES workspaces(id) ON DELETE SET NULL;
        """,
    ),
    (7, _workspaces_v7),
    (
        8,
        """
        -- Per-workspace sub-modules
        CREATE TABLE waiting_on (
          id INTEGER PRIMARY KEY,
          workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
          title TEXT NOT NULL,
          who TEXT NOT NULL DEFAULT '',
          nudged_at TEXT,
          resolved_at TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE agendas (
          id INTEGER PRIMARY KEY,
          workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          position INTEGER NOT NULL DEFAULT 0,
          archived_at TEXT
        );
        CREATE TABLE agenda_items (
          id INTEGER PRIMARY KEY,
          agenda_id INTEGER NOT NULL REFERENCES agendas(id) ON DELETE CASCADE,
          text TEXT NOT NULL,
          done_at TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- Growth workspaces: future plans as a pipeline
        CREATE TABLE pipeline_items (
          id INTEGER PRIMARY KEY,
          workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
          title TEXT NOT NULL,
          notes TEXT NOT NULL DEFAULT '',
          stage TEXT NOT NULL DEFAULT 'someday'
            CHECK (stage IN ('someday','researching','in-motion','done')),
          position INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- LIFE: finance (bills and renewals), appointments, meal planning
        CREATE TABLE bills (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          next_due TEXT NOT NULL,
          every_months INTEGER,                -- NULL = one-time renewal
          archived_at TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE appointments (
          id INTEGER PRIMARY KEY,
          title TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'needs_booking'
            CHECK (status IN ('needs_booking','booked')),
          when_at TEXT,
          resolved_at TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE grocery_items (
          id INTEGER PRIMARY KEY,
          label TEXT NOT NULL,
          staple INTEGER NOT NULL DEFAULT 0,
          checked INTEGER NOT NULL DEFAULT 0,
          position INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE meals (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          this_week INTEGER NOT NULL DEFAULT 0,
          position INTEGER NOT NULL DEFAULT 0
        );
        """,
    ),
    (
        9,
        """
        -- PAUSE: anti-impulsivity. An impulse waits out a timer; if still
        -- wanted it can be acted on, and the outcome (regret or not) is
        -- logged as self-knowledge, never as shame.
        CREATE TABLE impulses (
          id INTEGER PRIMARY KEY,
          title TEXT NOT NULL,
          category TEXT NOT NULL DEFAULT 'shopping'
            CHECK (category IN ('shopping','food','social','other')),
          wait_minutes INTEGER NOT NULL DEFAULT 1440,
          status TEXT NOT NULL DEFAULT 'waiting'
            CHECK (status IN ('waiting','released','acted')),
          acted_at TEXT,
          regret INTEGER,                      -- NULL = not yet logged; 0/1
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
    ),
    (
        10,
        """
        -- LEARN metadata: headliners, streaks, and where things were learned
        ALTER TABLE nodes ADD COLUMN learning_now INTEGER NOT NULL DEFAULT 0;
        CREATE TABLE learning_log (
          day TEXT PRIMARY KEY,
          source TEXT NOT NULL DEFAULT 'manual'
        );
        CREATE TABLE resources (
          id INTEGER PRIMARY KEY,
          track_id INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
          title TEXT NOT NULL,
          url TEXT NOT NULL DEFAULT '',
          kind TEXT NOT NULL DEFAULT 'article'
            CHECK (kind IN ('article','book','pdf','video','course','other')),
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
    ),
    (
        11,
        """
        -- The horizon column retired in favor of the written manifesto;
        -- parked far-off tasks join Next.
        UPDATE tasks SET horizon = 'next' WHERE horizon = 'horizon';
        """,
    ),
    (
        12,
        """
        -- RESCUE: the anhedonia list. Things that have ever helped, with an
        -- honest record of how often they actually did.
        CREATE TABLE rescue_items (
          id INTEGER PRIMARY KEY,
          title TEXT NOT NULL,
          tries INTEGER NOT NULL DEFAULT 0,
          helped INTEGER NOT NULL DEFAULT 0,
          pending_at TEXT,
          last_suggested TEXT,
          preset_key TEXT UNIQUE,
          active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
    ),
    (
        13,
        """
        -- The Next layer retires; the board merges into home. Uncommitted
        -- tasks return to the inbox for triage.
        UPDATE tasks SET horizon = 'inbox' WHERE horizon = 'next';
        """,
    ),
    (
        14,
        """
        -- Model buckets nest: a bucket may live inside another bucket.
        ALTER TABLE buckets ADD COLUMN parent_id INTEGER
          REFERENCES buckets(id) ON DELETE CASCADE;
        """,
    ),
    (
        15,
        """
        -- Workspace blocks reorganized: waiting-on retires (table kept),
        -- agendas become meetings, growth gains applications + a monologue,
        -- jobs gain named areas, classes become individually hideable.
        ALTER TABLE workspaces RENAME COLUMN has_waiting TO has_monologue;
        ALTER TABLE workspaces RENAME COLUMN has_agendas TO has_meetings;
        ALTER TABLE workspaces ADD COLUMN has_applications INTEGER NOT NULL DEFAULT 1;
        ALTER TABLE workspaces ADD COLUMN monologue TEXT NOT NULL DEFAULT '';
        UPDATE workspaces SET has_monologue = 0;
        CREATE TABLE areas (
          id INTEGER PRIMARY KEY,
          workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          hidden INTEGER NOT NULL DEFAULT 0,
          position INTEGER NOT NULL DEFAULT 0,
          archived_at TEXT
        );
        ALTER TABLE tasks ADD COLUMN area_id INTEGER
          REFERENCES areas(id) ON DELETE SET NULL;
        ALTER TABLE classes ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0;
        """,
    ),
    (
        16,
        """
        -- Learn tracks get a freeform notes space.
        ALTER TABLE tracks ADD COLUMN notes TEXT NOT NULL DEFAULT '';
        """,
    ),
    (
        17,
        """
        -- Work tasks carry deadlines and a computed burden
        -- (from a time estimate and a dread level).
        ALTER TABLE tasks ADD COLUMN due_date TEXT;
        ALTER TABLE tasks ADD COLUMN burden TEXT NOT NULL DEFAULT '';
        ALTER TABLE tasks ADD COLUMN effort_minutes INTEGER;
        ALTER TABLE tasks ADD COLUMN dread INTEGER;
        """,
    ),
    (
        18,
        """
        -- Deadlines come in three flavors: on a date, around a date, or soon.
        ALTER TABLE tasks ADD COLUMN due_kind TEXT NOT NULL DEFAULT 'on'
          CHECK (due_kind IN ('on','about','soon'));
        """,
    ),
    (
        19,
        """
        -- Sources and notes live on the learn item itself.
        ALTER TABLE nodes ADD COLUMN notes TEXT NOT NULL DEFAULT '';
        ALTER TABLE resources ADD COLUMN node_id INTEGER
          REFERENCES nodes(id) ON DELETE CASCADE;
        """,
    ),
    (
        20,
        """
        -- A learn item can carry any number of notes.
        CREATE TABLE node_notes (
          id INTEGER PRIMARY KEY,
          node_id INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
          text TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
    ),
    (
        21,
        """
        -- Grocery lists reuse the packing machinery, flavored by kind.
        ALTER TABLE pack_templates ADD COLUMN kind TEXT NOT NULL DEFAULT 'pack'
          CHECK (kind IN ('pack','grocery'));
        ALTER TABLE trips ADD COLUMN kind TEXT NOT NULL DEFAULT 'pack'
          CHECK (kind IN ('pack','grocery'));
        """,
    ),
    (
        22,
        """
        -- Financials, the gaming half: cards and how to win with them.
        CREATE TABLE credit_cards (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          use_for TEXT NOT NULL DEFAULT '',
          wins TEXT NOT NULL DEFAULT '',
          position INTEGER NOT NULL DEFAULT 0,
          archived_at TEXT
        );
        """,
    ),
    (
        23,
        """
        -- Meetings can carry a date.
        ALTER TABLE agendas ADD COLUMN when_at TEXT;
        """,
    ),
    (
        24,
        """
        -- Financial items split by what you do about them: pay it yourself,
        -- let it autopay, or decide before it renews.
        ALTER TABLE bills ADD COLUMN amount REAL;
        ALTER TABLE bills ADD COLUMN mode TEXT NOT NULL DEFAULT 'manual'
          CHECK (mode IN ('manual','auto','renewal'));
        """,
    ),
    (
        25,
        """
        -- Pages and databases parsed from a Notion workspace export,
        -- awaiting triage into the inbox or into model boards.
        CREATE TABLE imported_pages (
          id INTEGER PRIMARY KEY,
          kind TEXT NOT NULL CHECK (kind IN ('page','database')),
          title TEXT NOT NULL,
          digest TEXT NOT NULL DEFAULT '',
          payload TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','used','dismissed')),
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
    ),
    (
        26,
        """
        -- Credit cards drop the strategy notes for operational facts:
        -- when the payment is due and how much the card gets used.
        ALTER TABLE credit_cards ADD COLUMN due_date TEXT;
        ALTER TABLE credit_cards ADD COLUMN usage TEXT NOT NULL DEFAULT 'occasion'
          CHECK (usage IN ('daily','occasion','dead'));
        """,
    ),
]
