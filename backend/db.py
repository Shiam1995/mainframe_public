"""Neo4j connection layer + schema bootstrap.

All persistent data lives in Neo4j (per the spec — no SQLite, no JSON store).
This module owns a single async driver, exposes small read/write helpers, and
creates the constraints/indexes the app relies on.

Cypher is written inline in the route modules; these helpers just execute it.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase

import row_fields
from config import settings

log = logging.getLogger("synapse.db")

_driver: AsyncDriver | None = None


def get_driver() -> AsyncDriver:
    """Return the process-wide async driver (created lazily)."""
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _driver


async def close_driver() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None


async def run_write(cypher: str, **params: Any) -> list[dict]:
    """Run a write query in a managed transaction; return rows as dicts."""
    driver = get_driver()
    async with driver.session(database=settings.neo4j_database) as session:
        result = await session.run(cypher, **params)
        return [record.data() async for record in result]


async def run_read(cypher: str, **params: Any) -> list[dict]:
    """Run a read query; return rows as dicts."""
    driver = get_driver()
    async with driver.session(database=settings.neo4j_database) as session:
        result = await session.run(cypher, **params)
        return [record.data() async for record in result]


# Constraints (uniqueness) and indexes. IF NOT EXISTS makes this idempotent, so
# it's safe to run on every startup.
_SCHEMA_STATEMENTS: list[str] = [
    "CREATE CONSTRAINT paper_id IF NOT EXISTS FOR (p:Paper) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT instance_id IF NOT EXISTS FOR (i:Instance) REQUIRE i.id IS UNIQUE",
    "CREATE CONSTRAINT highlight_id IF NOT EXISTS FOR (h:Highlight) REQUIRE h.id IS UNIQUE",
    "CREATE CONSTRAINT concept_id IF NOT EXISTS FOR (c:Concept) REQUIRE c.id IS UNIQUE",
    # Concepts are MERGEd by name (terms.py) and shared across papers — that's
    # what makes the KG ring indicators work. Without this, a race could leave
    # two nodes of the same name and split a concept's encounters in half.
    "CREATE CONSTRAINT concept_name IF NOT EXISTS FOR (c:Concept) REQUIRE c.name IS UNIQUE",
    "CREATE CONSTRAINT question_id IF NOT EXISTS FOR (q:Question) REQUIRE q.id IS UNIQUE",
    # Gratitude tab: one node per row, plus the excited-for list.
    "CREATE CONSTRAINT gratitude_id IF NOT EXISTS FOR (g:Gratitude) REQUIRE g.id IS UNIQUE",
    "CREATE INDEX gratitude_period_date IF NOT EXISTS FOR (g:Gratitude) ON (g.period, g.date)",
    "CREATE CONSTRAINT excited_id IF NOT EXISTS FOR (x:Excited) REQUIRE x.id IS UNIQUE",
    "CREATE CONSTRAINT row_id IF NOT EXISTS FOR (r:Row) REQUIRE r.id IS UNIQUE",
    # + rows hang off these too, and the row's parent is found by id seek.
    "CREATE CONSTRAINT projectpass_id IF NOT EXISTS FOR (p:ProjectPass) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT baseline_id IF NOT EXISTS FOR (b:Baseline) REQUIRE b.id IS UNIQUE",
    "CREATE CONSTRAINT assumption_id IF NOT EXISTS FOR (a:Assumption) REQUIRE a.id IS UNIQUE",
    # Lattice canvas — prefixed label because :Concept belongs to the Synapse KG.
    "CREATE CONSTRAINT lattice_concept_id IF NOT EXISTS FOR (l:LatticeConcept) REQUIRE l.id IS UNIQUE",
    "CREATE CONSTRAINT task_id IF NOT EXISTS FOR (t:Task) REQUIRE t.id IS UNIQUE",
    "CREATE CONSTRAINT entry_id IF NOT EXISTS FOR (e:TaskEntry) REQUIRE e.id IS UNIQUE",
    "CREATE CONSTRAINT author_name IF NOT EXISTS FOR (a:Author) REQUIRE a.name IS UNIQUE",
    "CREATE CONSTRAINT venue_name IF NOT EXISTS FOR (v:Venue) REQUIRE v.name IS UNIQUE",
    "CREATE CONSTRAINT deepdive_id IF NOT EXISTS FOR (d:DeepDive) REQUIRE d.id IS UNIQUE",
    "CREATE CONSTRAINT idea_id IF NOT EXISTS FOR (i:Idea) REQUIRE i.id IS UNIQUE",
    "CREATE CONSTRAINT header_id IF NOT EXISTS FOR (h:CustomHeader) REQUIRE h.id IS UNIQUE",
    "CREATE CONSTRAINT kgnode_id IF NOT EXISTS FOR (n:KGNode) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT reference_id IF NOT EXISTS FOR (r:Reference) REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT minddump_id IF NOT EXISTS FOR (m:MindDump) REQUIRE m.id IS UNIQUE",
    "CREATE CONSTRAINT refnode_id IF NOT EXISTS FOR (n:RefNode) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT project_id IF NOT EXISTS FOR (p:Project) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT projectfile_id IF NOT EXISTS FOR (f:ProjectFile) REQUIRE f.id IS UNIQUE",
    "CREATE CONSTRAINT ddsource_id IF NOT EXISTS FOR (s:DeepDiveSource) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT heatcell_date IF NOT EXISTS FOR (c:HeatCell) REQUIRE c.date IS UNIQUE",
    "CREATE CONSTRAINT worksession_id IF NOT EXISTS FOR (w:WorkSession) REQUIRE w.id IS UNIQUE",
    # Phase dashboard: the goals the time viewer shows and the changes the
    # renegotiation flow writes. Both are seeded by activity.record()'s entity
    # lookup and phasehook's indexed seek, which read this list.
    "CREATE CONSTRAINT poolgoal_id IF NOT EXISTS FOR (g:PoolGoal) REQUIRE g.id IS UNIQUE",
    "CREATE CONSTRAINT change_id IF NOT EXISTS FOR (c:Change) REQUIRE c.id IS UNIQUE",
    # Notes, and the (:Hop) that stands in for an edge so a relationship can
    # carry them. Both need the id constraint to be reachable by the shared
    # entity lookup in activity.py.
    "CREATE CONSTRAINT note_id IF NOT EXISTS FOR (n:Note) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT hop_id IF NOT EXISTS FOR (h:Hop) REQUIRE h.id IS UNIQUE",
    # Lessons, and the groups you sort them into.
    "CREATE CONSTRAINT lesson_id IF NOT EXISTS FOR (l:Lesson) REQUIRE l.id IS UNIQUE",
    "CREATE CONSTRAINT lessongroup_name IF NOT EXISTS FOR (g:LessonGroup) REQUIRE g.name IS UNIQUE",
    "CREATE INDEX lesson_date IF NOT EXISTS FOR (l:Lesson) ON (l.date)",
    "CREATE INDEX note_kind IF NOT EXISTS FOR (n:Note) ON (n.kind)",
    "CREATE INDEX hop_edge IF NOT EXISTS FOR (h:Hop) ON (h.from_id, h.rel, h.to_id)",
    "CREATE INDEX poolgoal_horizon IF NOT EXISTS FOR (g:PoolGoal) ON (g.horizon)",
    "CREATE INDEX worksession_date IF NOT EXISTS FOR (w:WorkSession) ON (w.date)",
    "CREATE CONSTRAINT ideacategory_name IF NOT EXISTS FOR (c:IdeaCategory) REQUIRE c.name IS UNIQUE",
    # Learning Opportunities (Mainframe-level service)
    "CREATE CONSTRAINT learnop_id IF NOT EXISTS FOR (l:LearningOpportunity) REQUIRE l.id IS UNIQUE",
    "CREATE CONSTRAINT learnnote_id IF NOT EXISTS FOR (n:LearningNote) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT learnopt_id IF NOT EXISTS FOR (o:LearningOption) REQUIRE o.id IS UNIQUE",
    "CREATE INDEX learnop_kind IF NOT EXISTS FOR (l:LearningOpportunity) ON (l.kind)",
    # Planner (PLANNER_SPEC — Mainframe-level service)
    "CREATE CONSTRAINT plan_item_id IF NOT EXISTS FOR (p:PlanItem) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT session_id IF NOT EXISTS FOR (s:Session) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT plan_note_id IF NOT EXISTS FOR (n:PlanNote) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT weekly_report_id IF NOT EXISTS FOR (r:WeeklyReport) REQUIRE r.id IS UNIQUE",
    "CREATE INDEX session_start IF NOT EXISTS FOR (s:Session) ON (s.start)",
    "CREATE INDEX plan_item_status IF NOT EXISTS FOR (p:PlanItem) ON (p.status)",
    # Planner v2 (PLANNER_SPEC v2 §2) — the calendar surface. Only hand-placed
    # and externally-synced blocks are rows; auto-placed study/build blocks are
    # computed on read from PlanItem + slot template, never stored.
    "CREATE CONSTRAINT cal_event_id IF NOT EXISTS FOR (e:CalEvent) REQUIRE e.id IS UNIQUE",
    "CREATE CONSTRAINT day_block_id IF NOT EXISTS FOR (d:DayBlock) REQUIRE d.date IS UNIQUE",
    "CREATE INDEX cal_event_start IF NOT EXISTS FOR (e:CalEvent) ON (e.start)",
    # The planner settings singleton (capacity, horizon, slot template) predates
    # v2 but was never keyed; without this a second MERGE could fork the node.
    "CREATE CONSTRAINT planner_settings_id IF NOT EXISTS FOR (s:PlannerSettings) REQUIRE s.id IS UNIQUE",
    # Decomposition module (DECOMPOSITION_SPEC)
    "CREATE CONSTRAINT op_id IF NOT EXISTS FOR (o:Op) REQUIRE o.id IS UNIQUE",
    "CREATE CONSTRAINT snap_id IF NOT EXISTS FOR (s:Snapshot) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT arch_id IF NOT EXISTS FOR (a:Architecture) REQUIRE a.id IS UNIQUE",
    "CREATE INDEX op_tag IF NOT EXISTS FOR (o:Op) ON (o.tag)",
    "CREATE FULLTEXT INDEX op_text IF NOT EXISTS FOR (o:Op) ON EACH [o.label, o.summary, o.notes]",
    # Pulse module
    "CREATE CONSTRAINT habit_id IF NOT EXISTS FOR (h:Habit) REQUIRE h.id IS UNIQUE",
    "CREATE CONSTRAINT subhabit_id IF NOT EXISTS FOR (s:SubHabit) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT habitnote_id IF NOT EXISTS FOR (n:HabitNote) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT habitlog_id IF NOT EXISTS FOR (l:HabitLog) REQUIRE l.id IS UNIQUE",
    "CREATE CONSTRAINT exp_id IF NOT EXISTS FOR (e:Experiment) REQUIRE e.id IS UNIQUE",
    "CREATE CONSTRAINT routine_id IF NOT EXISTS FOR (r:Routine) REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT routinestep_id IF NOT EXISTS FOR (s:RoutineStep) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT steplog_id IF NOT EXISTS FOR (l:StepLog) REQUIRE l.id IS UNIQUE",
    "CREATE CONSTRAINT routinenote_id IF NOT EXISTS FOR (n:RoutineNote) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT medentry_id IF NOT EXISTS FOR (m:MedicalEntry) REQUIRE m.id IS UNIQUE",
    "CREATE CONSTRAINT medmed_id IF NOT EXISTS FOR (m:MedEntry) REQUIRE m.id IS UNIQUE",
    "CREATE INDEX habit_cat IF NOT EXISTS FOR (h:Habit) ON (h.category)",
    "CREATE INDEX medentry_section IF NOT EXISTS FOR (m:MedicalEntry) ON (m.section)",
    "CREATE INDEX medmed_section IF NOT EXISTS FOR (m:MedEntry) ON (m.section)",
    # Pulse Fitness sub-module
    "CREATE CONSTRAINT workout_id IF NOT EXISTS FOR (w:Workout) REQUIRE w.id IS UNIQUE",
    "CREATE CONSTRAINT exercise_id IF NOT EXISTS FOR (e:Exercise) REQUIRE e.id IS UNIQUE",
    "CREATE CONSTRAINT cycle_id IF NOT EXISTS FOR (c:Cycle) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT program_day_id IF NOT EXISTS FOR (d:ProgramDay) REQUIRE d.id IS UNIQUE",
    "CREATE CONSTRAINT prescription_id IF NOT EXISTS FOR (p:Prescription) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT workout_block_id IF NOT EXISTS FOR (b:WorkoutBlock) REQUIRE b.id IS UNIQUE",
    "CREATE CONSTRAINT lift_max_id IF NOT EXISTS FOR (m:LiftMax) REQUIRE m.id IS UNIQUE",
    "CREATE INDEX lift_max_key IF NOT EXISTS FOR (m:LiftMax) ON (m.key)",
    "CREATE CONSTRAINT goal_id IF NOT EXISTS FOR (g:Goal) REQUIRE g.id IS UNIQUE",
    "CREATE CONSTRAINT actlog_id IF NOT EXISTS FOR (a:ActivityLog) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT stretch_id IF NOT EXISTS FOR (s:StretchSession) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT bodystate_region IF NOT EXISTS FOR (b:BodyState) REQUIRE b.region IS UNIQUE",
    "CREATE CONSTRAINT bodyissue_id IF NOT EXISTS FOR (i:BodyIssue) REQUIRE i.id IS UNIQUE",
    "CREATE CONSTRAINT bodyissueupd_id IF NOT EXISTS FOR (u:BodyIssueUpdate) REQUIRE u.id IS UNIQUE",
    "CREATE INDEX bodyissue_region IF NOT EXISTS FOR (i:BodyIssue) ON (i.region, i.status)",
    "CREATE CONSTRAINT bodynote_id IF NOT EXISTS FOR (n:BodyNote) REQUIRE n.id IS UNIQUE",
    "CREATE INDEX workout_date IF NOT EXISTS FOR (w:Workout) ON (w.date)",
    "CREATE INDEX workout_type IF NOT EXISTS FOR (w:Workout) ON (w.type)",
    # Benchmarks
    "CREATE CONSTRAINT assessment_id IF NOT EXISTS FOR (a:Assessment) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT metricval_id IF NOT EXISTS FOR (m:MetricValue) REQUIRE m.id IS UNIQUE",
    "CREATE CONSTRAINT benchmetric_key IF NOT EXISTS FOR (m:BenchmarkMetric) REQUIRE m.key IS UNIQUE",
    "CREATE INDEX assessment_date IF NOT EXISTS FOR (a:Assessment) ON (a.date)",
    # Nutrition
    "CREATE CONSTRAINT food_id IF NOT EXISTS FOR (f:Food) REQUIRE f.id IS UNIQUE",
    # NUTRITION_SPEC — food log, recipes, water, weight, body, fasting
    "CREATE CONSTRAINT foodentry_id IF NOT EXISTS FOR (f:FoodEntry) REQUIRE f.id IS UNIQUE",
    "CREATE CONSTRAINT recipe_id IF NOT EXISTS FOR (r:Recipe) REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT water_id IF NOT EXISTS FOR (w:WaterEntry) REQUIRE w.id IS UNIQUE",
    "CREATE CONSTRAINT weight_id IF NOT EXISTS FOR (w:WeightEntry) REQUIRE w.id IS UNIQUE",
    "CREATE CONSTRAINT bodymeas_id IF NOT EXISTS FOR (b:BodyMeasurement) REQUIRE b.id IS UNIQUE",
    "CREATE CONSTRAINT fasting_id IF NOT EXISTS FOR (f:FastingSession) REQUIRE f.id IS UNIQUE",
    "CREATE INDEX food_name IF NOT EXISTS FOR (f:Food) ON (f.name)",
    "CREATE INDEX food_category IF NOT EXISTS FOR (f:Food) ON (f.category)",
    "CREATE INDEX food_usecount IF NOT EXISTS FOR (f:Food) ON (f.use_count)",
    "CREATE INDEX foodentry_date IF NOT EXISTS FOR (f:FoodEntry) ON (f.date)",
    "CREATE INDEX weight_date IF NOT EXISTS FOR (w:WeightEntry) ON (w.date)",
    "CREATE CONSTRAINT foodlog_id IF NOT EXISTS FOR (l:FoodLog) REQUIRE l.id IS UNIQUE",
    "CREATE CONSTRAINT intolerance_id IF NOT EXISTS FOR (i:Intolerance) REQUIRE i.id IS UNIQUE",
    "CREATE CONSTRAINT nsupp_id IF NOT EXISTS FOR (s:Supplement) REQUIRE s.id IS UNIQUE",
    "CREATE INDEX foodlog_date IF NOT EXISTS FOR (l:FoodLog) ON (l.date)",
    # Food catalogue — the imported USDA reference table (see foodcatalog.py).
    # Deliberately NOT :Food: your personal library still starts empty and stays
    # small, and 13k reference rows must never appear in "my foods".
    "CREATE CONSTRAINT catalogfood_fdc IF NOT EXISTS FOR (c:CatalogFood) REQUIRE c.fdc_id IS UNIQUE",
    "CREATE INDEX catalogfood_source IF NOT EXISTS FOR (c:CatalogFood) ON (c.source)",
    "CREATE INDEX catalogfood_search IF NOT EXISTS FOR (c:CatalogFood) ON (c.search_name)",
    # Full-text is what makes "chicken breast raw" find the right row out of
    # millions; the CONTAINS fallback in the route covers a missing index.
    # Brand is indexed too, so "tesco hobnobs" works on branded data.
    "CREATE FULLTEXT INDEX catalogfood_search_text IF NOT EXISTS FOR (c:CatalogFood) ON EACH [c.name, c.brand]",
    # Superseded by the index above (which indexed name only). DROP IF EXISTS is
    # a no-op after the first run; keeping it would hold a second copy of
    # millions of product names for nothing.
    "DROP INDEX catalogfood_text IF EXISTS",
    # Barcodes arrive with branded/Open Food Facts data — scanning a packet is
    # the point of having them.
    "CREATE INDEX catalogfood_barcode IF NOT EXISTS FOR (c:CatalogFood) ON (c.barcode)",
    "CREATE CONSTRAINT catalogmeta_id IF NOT EXISTS FOR (m:CatalogMeta) REQUIRE m.id IS UNIQUE",
    # Calendar — a Mainframe-level service, like tasks. Imported events use a
    # composite id (uid + occurrence date), which is what makes a re-import
    # update in place instead of duplicating every repeating event.
    "CREATE CONSTRAINT calevent_id IF NOT EXISTS FOR (e:CalEvent) REQUIRE e.id IS UNIQUE",
    "CREATE INDEX calevent_date IF NOT EXISTS FOR (e:CalEvent) ON (e.date)",
    "CREATE INDEX calevent_source IF NOT EXISTS FOR (e:CalEvent) ON (e.source)",
    # Recovery
    "CREATE CONSTRAINT rectype_id IF NOT EXISTS FOR (t:RecoveryType) REQUIRE t.id IS UNIQUE",
    "CREATE CONSTRAINT recsession_id IF NOT EXISTS FOR (s:RecoverySession) REQUIRE s.id IS UNIQUE",
    "CREATE INDEX recsession_date IF NOT EXISTS FOR (s:RecoverySession) ON (s.date)",
    "CREATE CONSTRAINT logentry_id IF NOT EXISTS FOR (l:LogEntry) REQUIRE l.id IS UNIQUE",
    # Dictionary (:Term nodes — global Mainframe service, distinct from :Concept).
    "CREATE CONSTRAINT term_id IF NOT EXISTS FOR (t:Term) REQUIRE t.id IS UNIQUE",
    "CREATE CONSTRAINT term_name IF NOT EXISTS FOR (t:Term) REQUIRE t.name IS UNIQUE",
    "CREATE CONSTRAINT dictq_id IF NOT EXISTS FOR (q:DictQuestion) REQUIRE q.id IS UNIQUE",
    "CREATE CONSTRAINT dictn_id IF NOT EXISTS FOR (n:DictNote) REQUIRE n.id IS UNIQUE",
    # Lookups the UI does a lot:
    "CREATE INDEX paper_status IF NOT EXISTS FOR (p:Paper) ON (p.status)",
    "CREATE INDEX paper_year IF NOT EXISTS FOR (p:Paper) ON (p.year)",
    "CREATE INDEX log_ts IF NOT EXISTS FOR (l:LogEntry) ON (l.ts)",
    # ChangeEvent = LogEntry (dual-labelled). Index the richer fields.
    "CREATE INDEX ce_module IF NOT EXISTS FOR (l:LogEntry) ON (l.module)",
    "CREATE INDEX ce_trigger IF NOT EXISTS FOR (l:LogEntry) ON (l.trigger)",
    "CREATE INDEX kgnode_paper IF NOT EXISTS FOR (n:KGNode) ON (n.paper_id)",
    "CREATE INDEX task_status IF NOT EXISTS FOR (t:Task) ON (t.status)",
    "CREATE INDEX task_horizon IF NOT EXISTS FOR (t:Task) ON (t.horizon)",
    "CREATE INDEX task_module IF NOT EXISTS FOR (t:Task) ON (t.module)",
    "CREATE INDEX task_parent IF NOT EXISTS FOR (t:Task) ON (t.parent_id)",
    "CREATE INDEX term_type IF NOT EXISTS FOR (t:Term) ON (t.type)",
    "CREATE INDEX term_fam IF NOT EXISTS FOR (t:Term) ON (t.familiarity)",
    # Images — Mainframe-level service, attachable to any entity by context_id.
    "CREATE CONSTRAINT image_id IF NOT EXISTS FOR (i:Image) REQUIRE i.id IS UNIQUE",
    "CREATE INDEX image_module IF NOT EXISTS FOR (i:Image) ON (i.module)",
    "CREATE INDEX image_context IF NOT EXISTS FOR (i:Image) ON (i.context_id)",
    # Vision module (VISION_SPEC)
    "CREATE CONSTRAINT pipeline_id IF NOT EXISTS FOR (p:Pipeline) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT pstage_id IF NOT EXISTS FOR (s:PipelineStage) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT tool_name IF NOT EXISTS FOR (t:Tool) REQUIRE t.name IS UNIQUE",
    "CREATE CONSTRAINT video_id IF NOT EXISTS FOR (v:Video) REQUIRE v.id IS UNIQUE",
    "CREATE CONSTRAINT jentry_id IF NOT EXISTS FOR (e:JournalEntry) REQUIRE e.id IS UNIQUE",
    "CREATE CONSTRAINT diary_id IF NOT EXISTS FOR (e:DiaryEntry) REQUIRE e.id IS UNIQUE",
    "CREATE INDEX diary_date IF NOT EXISTS FOR (e:DiaryEntry) ON (e.date)",
    "CREATE INDEX diary_module IF NOT EXISTS FOR (e:DiaryEntry) ON (e.module)",
    "CREATE INDEX video_type IF NOT EXISTS FOR (v:Video) ON (v.type)",
    "CREATE INDEX video_stage IF NOT EXISTS FOR (v:Video) ON (v.stage)",
    "CREATE CONSTRAINT research_id IF NOT EXISTS FOR (r:ResearchNote) REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT prompt_id IF NOT EXISTS FOR (p:PromptEntry) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT marker_id IF NOT EXISTS FOR (m:ScriptMarker) REQUIRE m.id IS UNIQUE",
    "CREATE CONSTRAINT panel_id IF NOT EXISTS FOR (p:StoryPanel) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT thumbopt_id IF NOT EXISTS FOR (t:ThumbnailOption) REQUIRE t.id IS UNIQUE",
    "CREATE CONSTRAINT writing_id IF NOT EXISTS FOR (w:WritingPiece) REQUIRE w.id IS UNIQUE",
    "CREATE CONSTRAINT pfproject_id IF NOT EXISTS FOR (p:PortfolioProject) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT contact_id IF NOT EXISTS FOR (c:Contact) REQUIRE c.id IS UNIQUE",
    # Vault module (VAULT_SPEC)
    "CREATE CONSTRAINT account_id IF NOT EXISTS FOR (a:Account) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT tx_id IF NOT EXISTS FOR (t:Transaction) REQUIRE t.id IS UNIQUE",
    "CREATE INDEX tx_date IF NOT EXISTS FOR (t:Transaction) ON (t.date)",
    "CREATE INDEX tx_category IF NOT EXISTS FOR (t:Transaction) ON (t.category)",
    "CREATE INDEX tx_verdict IF NOT EXISTS FOR (t:Transaction) ON (t.verdict)",
    "CREATE CONSTRAINT budget_id IF NOT EXISTS FOR (b:BudgetCategory) REQUIRE b.id IS UNIQUE",
    "CREATE CONSTRAINT income_month IF NOT EXISTS FOR (m:MonthlyIncome) REQUIRE m.month IS UNIQUE",
    "CREATE CONSTRAINT inv_id IF NOT EXISTS FOR (i:Investment) REQUIRE i.id IS UNIQUE",
    "CREATE CONSTRAINT item_id IF NOT EXISTS FOR (i:InventoryItem) REQUIRE i.id IS UNIQUE",
    "CREATE CONSTRAINT findiary_id IF NOT EXISTS FOR (d:FinanceDiary) REQUIRE d.id IS UNIQUE",
    "CREATE INDEX item_status IF NOT EXISTS FOR (i:InventoryItem) ON (i.status)",
    # Documents (Mainframe word processor). Folder is indexed because the
    # sidebar groups by it on every load.
    "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
    "CREATE INDEX document_folder IF NOT EXISTS FOR (d:Document) ON (d.folder)",
    # Sheets — user-defined databases.
    "CREATE CONSTRAINT sheet_id IF NOT EXISTS FOR (s:Sheet) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT sheetcol_id IF NOT EXISTS FOR (c:SheetColumn) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT sheetrow_id IF NOT EXISTS FOR (r:SheetRow) REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT sheetview_id IF NOT EXISTS FOR (v:SheetView) REQUIRE v.id IS UNIQUE",
    # Recurring payments + reminders.
    "CREATE CONSTRAINT recurring_id IF NOT EXISTS FOR (r:Recurring) REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT reminder_id IF NOT EXISTS FOR (r:Reminder) REQUIRE r.id IS UNIQUE",
    "CREATE INDEX reminder_due IF NOT EXISTS FOR (r:Reminder) ON (r.due)",
    # Focus (the quick-overview phase) + its goals.
    "CREATE CONSTRAINT focus_id IF NOT EXISTS FOR (f:Focus) REQUIRE f.id IS UNIQUE",
    "CREATE CONSTRAINT goal_id IF NOT EXISTS FOR (g:Goal) REQUIRE g.id IS UNIQUE",
    # Phases, per-period + per-day notes. (The Goals view that shared this
    # block was removed with the Inbox rework — see routes/inbox.py.)
    "CREATE CONSTRAINT phase_id IF NOT EXISTS FOR (p:Phase) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT daynote_date IF NOT EXISTS FOR (n:DayNote) REQUIRE n.date IS UNIQUE",
    # Framework — the approach being taken, and why.
    "CREATE CONSTRAINT framework_id IF NOT EXISTS FOR (f:Framework) REQUIRE f.id IS UNIQUE",
]

# References pipeline (synapse/references) keeps its DDL next to its code —
# one source of truth, same idempotent treatment as the statements above.
_REF_SCHEMA = Path(__file__).resolve().parent / "synapse" / "references" / "schema.cypher"
if _REF_SCHEMA.exists():
    _ref_ddl = "\n".join(
        ln for ln in _REF_SCHEMA.read_text().splitlines()
        if not ln.strip().startswith("//")
    )
    _SCHEMA_STATEMENTS += [s.strip() for s in _ref_ddl.split(";") if s.strip()]


# Idempotent data migrations run after the schema DDL on every startup. Each is
# a no-op once applied (guarded by WHERE/coalesce), so re-running is harmless.
_MIGRATIONS: list[str] = [
    # The Project tab's list: rank, priority and status are columns you edit in
    # place, so every project needs them present rather than null — Neo4j drops
    # nulls, and a missing property would change the shape of the API response
    # row by row. Priority defaults to 2 (soon) because 1 (now) is a claim.
    """
    MATCH (p:Project) WHERE p.priority IS NULL
    SET p.priority = 2, p.priority_order = 0.0, p.status = 'active',
        p.done_at = '', p.est_override = false
    """,
    # The card border colour. "" means no choice made and the card falls back
    # to its priority colour, so this is defaulted rather than left null.
    """
    MATCH (p:Project) WHERE p.color IS NULL SET p.color = ''
    """,
    # --- work type: study | build | admin | body ----------------------------
    # What working on a project IS, backfilled by name because the four types
    # were invented after the projects were. A few name keywords pick out the
    # obvious cases; everything else lands on study, which is what most of a
    # typical list is. Only ever fills a NULL, so a type set by hand
    # is never overwritten by a later boot.
    """
    MATCH (p:Project) WHERE p.kind IS NULL
    WITH p, toLower(coalesce(p.name, '')) AS n
    SET p.kind = CASE
        WHEN n CONTAINS 'engine' OR n CONTAINS 'build' OR n CONTAINS 'kit' THEN 'build'
        WHEN n CONTAINS 'mainframe' OR n CONTAINS 'admin' THEN 'admin'
        ELSE 'study'
    END
    """,
    # A sheet's project is an edge; the property mirrors it so a client can
    # read the pair back without walking the graph. Sheets that predate the
    # edge get "" rather than null — "no project" is a real answer here.
    """
    MATCH (s:Sheet) WHERE s.project_id IS NULL SET s.project_id = ''
    """,
    # The same type on the sessions, taken from the project the session is on.
    # A session reaches its project either directly or through the task it was
    # logged against, and one that reaches neither is study — see the default
    # in models.WorkType. Sessions carry their own copy rather than reading
    # through the edge: retyping one hour of reading on a build project must
    # not retype the project, and the Database tab filters on the row.
    """
    MATCH (w:WorkSession) WHERE w.kind IS NULL
    OPTIONAL MATCH (w)-[:ON]->(direct:Project)
    OPTIONAL MATCH (w)-[:ON]->(:Task)-[:GIVEN_TO]->(viaTask:Project)
    OPTIONAL MATCH (byRef:Project) WHERE w.ref_kind = 'project' AND byRef.id = w.ref_id
    WITH w, coalesce(direct.kind, viaTask.kind, byRef.kind, 'study') AS k
    SET w.kind = k
    """,
    # Estimates and due dates arrived with the Inbox; older projects predate them.
    """
    MATCH (p:Project) WHERE p.low_h IS NULL
    SET p.low_h = 0.0, p.high_h = 0.0, p.due = '', p.done_when = ''
    """,
    # Tasks gained done_at when the tree learned to tick them.
    """
    MATCH (t:Task) WHERE t.done_at IS NULL SET t.done_at = ''
    """,
    # CHILD_OF and GIVEN_TO carry an explicit order so a drag can rewrite it.
    """
    MATCH (:Project)-[r:CHILD_OF]->(:Project) WHERE r.order IS NULL
    SET r.order = 0.0
    """,
    """
    MATCH (:Task)-[r:GIVEN_TO]->(:Project) WHERE r.order IS NULL
    SET r.order = 0.0
    """,
    # The diary became one store with a `module` facet, so a Vault entry and a
    # Mainframe day entry are the same node seen through two tabs. Vault's
    # standalone :FinanceDiary is copied across rather than moved — the
    # originals stay put as a backup, exactly like :LearningOpportunity.ideas.
    """
    MATCH (d:FinanceDiary)
    WHERE NOT EXISTS { MATCH (e:DiaryEntry {id: d.id}) }
    CREATE (e:DiaryEntry {
        id: d.id, date: coalesce(d.date, ''), text: coalesce(d.text, ''),
        title: coalesce(d.title, ''), module: 'vault', section: 'findiary',
        tags: coalesce(d.tags, []), source: 'section',
        created_at: coalesce(d.created_at, ''), updated_at: coalesce(d.created_at, '')
    })
    WITH e MERGE (m:Module {name: 'vault'}) MERGE (e)-[:OWNED_BY]->(m)
    """,
    # Inventory estimates became a range: a thing you want to buy is rarely one
    # price. `value` is the low end (or the only figure), `value_max` the high
    # end; 0 means "not a range", so old single-figure items read unchanged.
    """
    MATCH (i:InventoryItem) WHERE i.value_max IS NULL
    SET i.value_max = 0.0
    """,
    # Body map issues: regions flagged under the old cycle system become open
    # issues (severity 3 — the middle of the new 1–5 scale) so nothing already
    # flagged vanishes. Guarded on "no issue exists for that region yet";
    # closing an issue blanks the matching :BodyState, so this cannot re-fire.
    """
    MATCH (b:BodyState) WHERE coalesce(b.state, '') <> ''
      AND NOT EXISTS { MATCH (:BodyIssue {region: b.region}) }
    CREATE (i:BodyIssue {id: randomUUID(), region: b.region,
                         kind: CASE b.state WHEN 'pain' THEN 'pain'
                               WHEN 'tight' THEN 'tight' ELSE 'imbalance' END,
                         severity: 3, status: 'open',
                         opened_at: coalesce(b.date, ''), closed_at: ''})
    CREATE (i)-[:HAS_UPDATE]->(:BodyIssueUpdate {id: randomUUID(),
                               ts: coalesce(b.date, ''), severity: 3,
                               note: 'migrated from the old body-map flag'})
    """,
    # The repository holds sources, not only papers (books, video series,
    # courses). Everything that predates `kind` was uploaded as a PDF paper.
    """
    MATCH (p:Paper) WHERE p.kind IS NULL
    SET p.kind = 'paper'
    """,
    # Repository cards became movable. Seed `position` from the order they're
    # already displayed in (year desc, then added_at desc) so nothing jumps the
    # first time an arrow is used — same approach as mind-dumps and ideas.
    """
    MATCH (p:Paper) WHERE p.position IS NULL
    WITH p ORDER BY coalesce(p.year, 0) DESC, p.added_at DESC
    WITH collect(p) AS ps
    UNWIND range(0, size(ps) - 1) AS i
    WITH ps[i] AS node, i
    SET node.position = toFloat(i)
    """,
    # Workspace section boxes gained a border colour you pick per workspace.
    # The shape is a JSON object keyed by section ("terms", "mind", …) and owned
    # by the frontend, so adding a section never needs a backend change. Empty
    # object rather than null: a missing property would change the response shape.
    """
    MATCH (p:Paper) WHERE p.section_colors IS NULL SET p.section_colors = '{}'
    """,
    # And a reading pass gained one of its own, so a skim and a deep read are
    # told apart at a glance. "" means no choice made — the chip keeps its
    # default look — so this is defaulted rather than left null, as with Project.
    """
    MATCH (i:Instance) WHERE i.color IS NULL SET i.color = ''
    """,
    # Repository cards gained a border colour of their own, the same seven names
    # Projects and the workspace boxes use. Defaulted rather than left null so
    # every row has the property, as with Project.color.
    """
    MATCH (p:Paper) WHERE p.color IS NULL SET p.color = ''
    """,
    # Tasks gained an editable `opened_at` (when the work started, as opposed to
    # `created_at`, when the row was made). Seed it from created_at so every
    # existing task already has a measurable age.
    """
    MATCH (t:Task) WHERE t.opened_at IS NULL
    SET t.opened_at = t.created_at
    """,
    # Reading passes became reorderable and gained two written fields. Seed
    # `position` from `version` so existing passes keep the order they were read
    # in, and default the text to "" — Neo4j drops nulls, which would change the
    # shape of the API response.
    """
    MATCH (i:Instance) WHERE i.position IS NULL
    SET i.position = toFloat(coalesce(i.version, 0))
    """,
    """
    MATCH (i:Instance) WHERE i.look_into IS NULL SET i.look_into = ''
    """,
    # "pushed" became "completed" — same flag, a name that says what it means.
    # The old property is left in place so nothing that still reads it breaks.
    """
    MATCH (w:WorkSession) WHERE w.completed IS NULL
    SET w.completed = coalesce(w.pushed, false)
    """,
    # Learning entries gained a long-form `detail` plus repeatable idea and
    # consultation lists. Default them so the API's response shape is the same
    # for an old entry as a new one (Neo4j drops nulls).
    """
    MATCH (l:LearningOpportunity) WHERE l.detail IS NULL SET l.detail = ''
    """,
    """
    MATCH (l:LearningOpportunity) WHERE l.ideas IS NULL SET l.ideas = []
    """,
    """
    MATCH (l:LearningOpportunity) WHERE l.consulted IS NULL SET l.consulted = []
    """,
    # Register every kind already in use, so the catalogue starts complete and
    # groups can be assigned to what's actually there.
    """
    MATCH (l:LearningOpportunity) WHERE trim(coalesce(l.kind,'')) <> ''
    MERGE (:LearningKind {name: toLower(trim(l.kind))})
    """,
    # Options became real: a mistake now carries a set of candidate responses
    # you pick from, rather than a flat list of ideas. Every existing idea
    # becomes an option, in the order it was written, so nothing has to be
    # retyped. Guarded on "this entry has no options yet", so it runs once; the
    # original `l.ideas` list is deliberately left in place as the backup.
    """
    MATCH (l:LearningOpportunity)
    WHERE l.ideas IS NOT NULL AND size(l.ideas) > 0
      AND NOT EXISTS { MATCH (l)-[:HAS_OPTION]->(:LearningOption) }
    UNWIND range(0, size(l.ideas) - 1) AS i
    WITH l, i, trim(l.ideas[i]) AS text WHERE text <> ''
    CREATE (l)-[:HAS_OPTION]->(:LearningOption {
        id: randomUUID(), text: text, status: 'option', order: i,
        created_at: toString(datetime()), decided_at: ''
    })
    """,
    # Distractions became a list — one entry per interruption — because a single
    # comma-joined string can't say what each one was. Split the old field on
    # commas so anything already written is carried over, not dropped.
    """
    MATCH (i:Instance) WHERE i.distraction_items IS NULL
    SET i.distraction_items =
        CASE WHEN coalesce(i.distraction_types, '') = '' THEN []
             ELSE [x IN split(i.distraction_types, ',') WHERE trim(x) <> '' | trim(x)]
        END
    """,
    # Increment #8: promote legacy :LogEntry rows to the richer ChangeEvent
    # schema — add the :ChangeEvent label + the module/trigger/timestamp fields.
    """
    MATCH (l:LogEntry) WHERE NOT l:ChangeEvent
    SET l:ChangeEvent,
        l.module = coalesce(l.module, 'synapse'),
        l.trigger = coalesce(l.trigger, 'manual'),
        l.timestamp = coalesce(l.timestamp, l.ts)
    """,
    # Deep Dive redesigned topic-first — carry old month/theme/notes into the
    # new topic/info fields so existing dives aren't lost.
    """
    MATCH (d:DeepDive)
    SET d.topic = coalesce(d.topic, d.theme, d.month, 'Untitled'),
        d.info = coalesce(d.info, d.notes, '')
    """,
    # Manual card ordering: seed `position` on pre-existing mind-dumps and ideas
    # from their current (newest-first) display order so nothing jumps around
    # the first time the reorder arrows are used.
    """
    MATCH (m:MindDump) WHERE m.position IS NULL
    WITH m ORDER BY m.created_at DESC
    WITH collect(m) AS ms
    UNWIND range(0, size(ms) - 1) AS i
    WITH ms[i] AS node, i
    SET node.position = toFloat(i)
    """,
    """
    MATCH (i:Idea) WHERE i.position IS NULL
    WITH i ORDER BY i.created_at DESC
    WITH collect(i) AS xs
    UNWIND range(0, size(xs) - 1) AS n
    WITH xs[n] AS node, n
    SET node.position = toFloat(n)
    """,
    # Contribution grid rework: projects gained a "add to the contributions"
    # flag (border on the day square). Existing projects default to opted-in.
    """
    MATCH (p:Project) WHERE p.contributes IS NULL
    SET p.contributes = true, p.status = coalesce(p.status, 'active'), p.repo = coalesce(p.repo, '')
    """,
    # Ideas are now marked by kind, and the colour lives on the kind. Seed the
    # kinds that were previously hard-coded in the frontend, plus any kind
    # already in use on an existing idea, each with a distinct colour.
    """
    UNWIND [
      {name: 'research',       color: '#5A9DE0'},
      {name: 'implementation', color: '#00D4AA'},
      {name: 'content',        color: '#FF4757'},
      {name: 'experiment',     color: '#F0A030'},
      {name: 'tool',           color: '#7FA8C8'},
      {name: 'personal',       color: '#F4709C'}
    ] AS seed
    MERGE (c:IdeaCategory {name: seed.name})
      ON CREATE SET c.color = seed.color
    """,
    """
    MATCH (i:Idea) WHERE i.category IS NOT NULL AND trim(i.category) <> ''
    MERGE (c:IdeaCategory {name: i.category})
      ON CREATE SET c.color = '#7FA8C8'
    """,
    # Reading instances gained structured timing (started/ended, time spent,
    # the active/passive split, and a distraction count). Backfill the defaults
    # so existing instances read back with the full shape instead of nulls.
    """
    MATCH (i:Instance) WHERE i.mins IS NULL
    SET i.start = coalesce(i.start, ''),
        i.end = coalesce(i.end, ''),
        i.mins = 0,
        i.active_mins = coalesce(i.active_mins, 0),
        i.passive_mins = coalesce(i.passive_mins, 0),
        i.distractions = coalesce(i.distractions, 0)
    """,
    # Planner v2: plan items gained a category (which drives whether they are
    # auto-placed onto the calendar or hand-placed), an explicit placement
    # override, and a priority marker. v1 items predate all three — default them
    # to study/auto/none so an old item reads back with the same shape as a new
    # one and starts participating in auto-placement immediately.
    """
    MATCH (p:PlanItem) WHERE p.category IS NULL
    SET p.category = 'study',
        p.placement = coalesce(p.placement, 'auto'),
        p.marker = coalesce(p.marker, 'none')
    """,
    # Same node, older rows that already had a category but neither of the
    # other two (defensive: the pass above only fires when category IS NULL).
    """
    MATCH (p:PlanItem) WHERE p.placement IS NULL OR p.marker IS NULL
    SET p.placement = coalesce(p.placement, 'auto'),
        p.marker = coalesce(p.marker, 'none')
    """,
    # The planner settings singleton gained a horizon date and a slot template.
    # v1 only ever wrote `capacity`; seed the v2 fields on the existing node so
    # GET /settings has the full shape before the user touches anything.
    """
    MATCH (s:PlannerSettings) WHERE s.horizon_date IS NULL
    SET s.horizon_date = '',
        s.template = coalesce(s.template, '')
    """,
    # Phases tab: the :Phase node the Goals view already scopes goals to gains a
    # sprint lifecycle (one active at a time, closed with a reflection) plus the
    # phase-long goal and its length in weeks. Phases that already ended are
    # closed on sight; anything still running or still ahead stays open, so the
    # tab opens on the phase the user is actually in.
    """
    MATCH (p:Phase) WHERE p.status IS NULL
    WITH p, toString(date()) AS today
    SET p.status = CASE WHEN p.end < today THEN 'closed' ELSE 'active' END,
        p.goal = coalesce(p.goal, ''),
        p.reflection = coalesce(p.reflection, ''),
        p.weeks = coalesce(p.weeks,
                  CASE WHEN duration.inDays(date(p.start), date(p.end)).days < 7 THEN 1
                       ELSE toInteger(round(duration.inDays(date(p.start), date(p.end)).days / 7.0)) END)
    """,
    # Phase numbers ("phase 02") are the order they started in, not the order
    # they were typed in. Number the pre-existing ones once, by start date.
    """
    MATCH (p:Phase) WHERE p.seq IS NULL
    WITH p ORDER BY p.start
    WITH collect(p) AS xs
    UNWIND range(0, size(xs) - 1) AS n
    WITH xs[n] AS node, n
    SET node.seq = n + 1
    """,
    # Documents gained a project BINDING — (:Document)-[:FOR]->(:Project) — which
    # is what the hours you spend writing follow. Every document already saying
    # it is ABOUT a project meant exactly that, so draw the edge for them rather
    # than making the binding something to set a second time. The :ABOUT link is
    # left in place: "what this is about" is still its own question.
    """
    MATCH (d:Document)-[:ABOUT]->(p:Project)
    WHERE NOT EXISTS { MATCH (d)-[:FOR]->(:Project) }
    MERGE (d)-[:FOR]->(p)
    """,
    # A document's hours are the sessions WORKED_ON it. Sessions logged against a
    # document before that edge existed are joined to it by :ON — the same hours
    # under the older name — so give them the edge too, or every doc that was
    # ever pushed reads as 0h.
    """
    MATCH (w:WorkSession)-[:ON]->(d:Document)
    WHERE NOT EXISTS { MATCH (w)-[:WORKED_ON]->(d) }
    MERGE (w)-[:WORKED_ON]->(d)
    """,
    # Lessons v2 (2026-10-04): a distraction row's `group` held its PATTERN
    # ("phone notification"), while a written lesson's `group` held its
    # CATEGORY. Two meanings in one field. Patterns move to `pattern`, and
    # `group` means category everywhere.
    """
    MATCH (l:Lesson) WHERE l.source = 'distraction' AND l.pattern IS NULL
    SET l.pattern = coalesce(l.group, ''), l.group = ''
    """,
    # The eight starting categories from the Lessons mockup. Seeded once, behind
    # a marker, so deleting one you don't use keeps it deleted. Existing groups
    # keep their colour; they only gain a description if they had none.
    """
    OPTIONAL MATCH (m:Marker {name: 'lesson-categories-v1'})
    WITH m WHERE m IS NULL
    UNWIND [
      {ord: 1, name: 'Environment', color: '#F0A030', note: 'interruptions, place'},
      {ord: 2, name: 'Planning',    color: '#5A9DE0', note: 'estimates, order'},
      {ord: 3, name: 'Method',      color: '#8B7EC8', note: 'read without doing'},
      {ord: 4, name: 'Focus',       color: '#00D4AA', note: 'drift, tabs'},
      {ord: 5, name: 'Energy',      color: '#4ADE80', note: 'sleep, food'},
      {ord: 6, name: 'Tooling',     color: '#DE7BA4', note: 'setup, lost work'},
      {ord: 7, name: 'People',      color: '#8A97A8', note: 'replies, yeses'},
      {ord: 8, name: 'Money',       color: '#D4A017', note: 'renewals, spend'}
    ] AS c
    MERGE (g:LessonGroup {name: c.name})
    ON CREATE SET g.color = c.color, g.note = c.note, g.order = c.ord
    WITH count(*) AS n
    MERGE (:Marker {name: 'lesson-categories-v1'})
    """,
    # Reference lists keep the order they were put in (2026-11-11); they used
    # to be listed newest year first. Each one was saved entry by entry in
    # list order, so created_at is that order: number them by it. Only refs
    # with no position yet, so this is a no-op after the first run.
    """
    MATCH (p:Paper)-[:REFERENCES]->(r:Reference) WHERE r.position IS NULL
    WITH p, r ORDER BY r.created_at
    WITH p, collect(r) AS rs
    OPTIONAL MATCH (p)-[:REFERENCES]->(o:Reference) WHERE o.position IS NOT NULL
    WITH rs, coalesce(max(o.position), -1) AS top
    UNWIND range(0, size(rs) - 1) AS i
    WITH rs[i] AS r, top + 1 + i AS pos
    SET r.position = pos
    """,
]


async def init_schema() -> None:
    driver = get_driver()
    async with driver.session(database=settings.neo4j_database) as session:
        for stmt in _SCHEMA_STATEMENTS:
            await session.run(stmt)
        for stmt in _MIGRATIONS:
            await session.run(stmt)
        # Textareas that became + rows: move what was typed in them, once.
        await row_fields.migrate(session)
    log.info(
        "Neo4j schema ready (%d constraints/indexes, %d migrations)",
        len(_SCHEMA_STATEMENTS), len(_MIGRATIONS),
    )


async def verify_connectivity() -> bool:
    try:
        await get_driver().verify_connectivity()
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Neo4j not reachable: %s", exc)
        return False
