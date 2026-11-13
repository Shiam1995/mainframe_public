"""Pydantic request/response models.

Neo4j is schemaless at the driver level, so these models are where shape and
validation actually live. Node property names match the spec's data model.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Papers
# --------------------------------------------------------------------------- #
# "revisit" = read it, but needs another pass
# "shelved" = put down on purpose, not finished — parked until you pick it back up
PaperStatus = Literal["unread", "reading", "read", "revisit", "shelved"]

# What a repository entry actually is. A :Paper node is really "a source" — the
# label is kept because every paper-scoped view (workspace, instances,
# highlights, terms, references, KG, deep dive) is already built on it, and a
# book or a video series wants all of that machinery, not a copy of it.
# A PDF is optional: a video series or a book you only own on paper still gets
# its own instances, notes and graph nodes.
# The first seven are things you *read* (or attend — an event); the last four are things you *work on* —
# a project, a decomposition node, an idea, or a plain untyped subject ("topic",
# shown as "general idea"). They share the label because the workspace machinery
# — passes, highlights, terms, mind dumps, images — is worth exactly as much on
# an idea you are chewing over as on a paper you are reading.
SourceKind = Literal[
    "paper", "book", "video", "course", "article", "note", "event",
    "project", "decomp", "idea", "topic",
]

# What an entry can point back at. A workspace subject brought in from elsewhere
# keeps a live reference rather than a copy, so opening it can jump to the real
# project / decomposition node / idea it is about.
LinkKind = Literal["project", "decomp", "idea"]


class PaperUpdate(BaseModel):
    title: Optional[str] = None
    kind: Optional[SourceKind] = None
    link_kind: Optional[LinkKind] = None
    link_id: Optional[str] = None
    authors: Optional[list[str]] = None
    year: Optional[int] = None
    venue: Optional[str] = None
    url: Optional[str] = None
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    abstract: Optional[str] = None
    status: Optional[PaperStatus] = None
    understanding: Optional[int] = None   # 0-10, how well you feel you grasp it
    # Border colours for the workspace section boxes, as a JSON object keyed by
    # section. The frontend owns the shape, so a new section costs no backend change.
    section_colors: Optional[str] = None
    # The card's border in the Repository list. "" = no choice made.
    color: Optional[str] = None
    # One line asked for when an entry goes onto the Finished shelf (repo.js
    # shelf). What you took away, shown in the shelf's info panel.
    takeaway: Optional[str] = None


class SourceCreate(BaseModel):
    """A repository entry typed in by hand — no file involved."""
    title: str
    # Untyped by default: you name the thing first, and say what it is only if
    # you feel like saying.
    kind: SourceKind = "topic"
    link_kind: Optional[LinkKind] = None
    link_id: Optional[str] = None
    authors: list[str] = []
    year: Optional[int] = None
    venue: Optional[str] = None      # publisher, channel, platform
    url: Optional[str] = None        # where it lives: a playlist, a course page
    abstract: Optional[str] = None   # your own blurb / what it's about
    status: PaperStatus = "unread"


class Paper(BaseModel):
    id: str
    title: str
    kind: SourceKind = "paper"
    link_kind: Optional[LinkKind] = None
    link_id: Optional[str] = None
    authors: list[str] = []
    year: Optional[int] = None
    venue: Optional[str] = None
    url: Optional[str] = None
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    abstract: Optional[str] = None
    original_path: Optional[str] = None
    status: PaperStatus = "unread"
    added_at: Optional[str] = None


# --------------------------------------------------------------------------- #
# Instances / highlights / terms
# --------------------------------------------------------------------------- #
CodeDepth = Literal["L0", "L1", "L2", "L3", "L4", "L5"]
HighlightTag = Literal["knew", "new", "rethink", "implement"]


# How a book session was spent. A chapter is not "done" because you read it —
# the exercises are the other half — so the mode is what the chapter-status rule
# is computed from, and it is asked for rather than guessed.
BookMode = Literal["read", "exercises", "code", "review"]
BOOK_MODES = ("read", "exercises", "code", "review")


class InstanceCreate(BaseModel):
    purpose: str = "first read"
    coverage_pre: float = 0.0
    read_date: Optional[str] = None      # when you actually read it (user-set)
    time_spent: Optional[str] = None     # legacy freeform, e.g. "45min" / "1.5hrs"
    notes: Optional[str] = None          # fill-in info after the session
    # The write-up split into the three questions worth answering after a read.
    # `notes` is what you took away; these two are the parts that were getting
    # buried inside it. All three are free text and any of them can stay empty.
    understood: Optional[str] = None     # what you actually understood
    main_question: Optional[str] = None  # the question the pass leaves you with
    # Set BEFORE the pass, not after: the things you already know you want to
    # come back to. Surfaces in the Master Instance so it isn't lost in a pass.
    look_into: Optional[str] = None
    # --- structured timing (see InstanceUpdate for the full set) ---
    start: str = ""
    end: str = ""
    mins: int = 0
    active_mins: int = 0
    passive_mins: int = 0
    distractions: int = 0
    # What pulled you away, one entry per interruption. A count alone says a
    # session went badly; the list says what to change, which is what makes it
    # pushable to Learning.
    distraction_items: list[str] = []
    # --- where in the book (books only; empty on a paper) ---------------
    # Chapter is TEXT, not an int: a session that ran across a boundary is
    # honestly "1 to 2", and forcing it to a number would either lose that or
    # invent a chapter it did not cover. Sorting parses the leading number.
    chapter: Optional[str] = None
    pages_from: Optional[int] = None
    # Open-ended on purpose: half the sessions already logged stopped at "xxx"
    # because the stopping page was not noted, and a null end is the truth.
    pages_to: Optional[int] = None
    mode: Optional[BookMode] = None


class InstanceUpdate(BaseModel):
    purpose: Optional[str] = None
    color: Optional[str] = None          # pass-chip border colour; "" = default
    coverage_pre: Optional[float] = None
    coverage_post: Optional[float] = None
    code_depth: Optional[CodeDepth] = None
    read_date: Optional[str] = None
    time_spent: Optional[str] = None
    notes: Optional[str] = None          # what you took away
    understood: Optional[str] = None     # what you actually understood
    main_question: Optional[str] = None  # the question the pass leaves you with
    # Structured timing for a reading session. `mins` is derived from
    # start/end when both are set, but a typed value always wins. active +
    # passive split the session; `distractions` is a COUNT, not minutes.
    # Anything that doesn't apply stays 0 / "".
    start: Optional[str] = None          # "HH:MM" started
    end: Optional[str] = None            # "HH:MM" ended
    mins: Optional[int] = None           # total time spent
    active_mins: Optional[int] = None    # of which active reading
    passive_mins: Optional[int] = None   # of which passive
    distractions: Optional[int] = None   # how many times you were pulled away
    distraction_items: Optional[list[str]] = None  # and what each one was
    look_into: Optional[str] = None      # things to come back to
    position: Optional[float] = None     # manual ordering of passes
    # --- where in the book (books only; empty on a paper) ---------------
    # Chapter is TEXT, not an int: a session that ran across a boundary is
    # honestly "1 to 2", and forcing it to a number would either lose that or
    # invent a chapter it did not cover. Sorting parses the leading number.
    chapter: Optional[str] = None
    pages_from: Optional[int] = None
    # Open-ended on purpose: half the sessions already logged stopped at "xxx"
    # because the stopping page was not noted, and a null end is the truth.
    pages_to: Optional[int] = None
    mode: Optional[BookMode] = None


# --------------------------------------------------------------------------- #
# Books — the pairing, the backfill and a chapter's two hand-set values
# --------------------------------------------------------------------------- #
class BookPair(BaseModel):
    book_id: str
    # None means "make one". The reviewed name travels with the row so an edit
    # made in the review step is what lands, not the server's own suggestion.
    project_id: Optional[str] = None
    project_name: Optional[str] = None


class BookPairingApply(BaseModel):
    pairs: list[BookPair] = []


class BookBackfillItem(BaseModel):
    instance_id: str
    chapter: Optional[str] = None
    pages_from: Optional[int] = None
    pages_to: Optional[int] = None
    mode: Optional[BookMode] = None


class BookBackfillApply(BaseModel):
    sessions: list[BookBackfillItem] = []


class BookChapterUpdate(BaseModel):
    # The hand tick. A chapter is done automatically once it has a read AND an
    # exercises session; this is the override for the chapters where that rule
    # does not apply (no exercises exist, or you decided it was enough).
    done: Optional[bool] = None
    # Hours this chapter is expected to take. What the phase forecast reads.
    estimate_h: Optional[float] = None


class HighlightCreate(BaseModel):
    section: str = ""
    excerpt: str = ""
    my_note: str = ""
    tag: HighlightTag = "new"
    page: Optional[int] = None


class HighlightUpdate(BaseModel):
    section: Optional[str] = None
    excerpt: Optional[str] = None
    my_note: Optional[str] = None
    tag: Optional[HighlightTag] = None
    page: Optional[int] = None


class TermCreate(BaseModel):
    name: str
    definition: Optional[str] = None
    domain: Optional[str] = None
    familiarity: int = Field(0, ge=0, le=10)
    optional: bool = False  # "review later" / low-priority flag


class TermUpdate(BaseModel):
    definition: Optional[str] = None
    domain: Optional[str] = None
    familiarity: Optional[int] = Field(None, ge=0, le=10)
    optional: Optional[bool] = None


# --------------------------------------------------------------------------- #
# Dictionary (global Mainframe service — :Term nodes, distinct from :Concept)
# --------------------------------------------------------------------------- #
# The star "tag" classifies each entry. `starred` is a separate quick flag the
# user toggles to mark favourites.
DictEntryType = Literal["term", "concept", "method", "person"]


class DictEntryCreate(BaseModel):
    name: str
    eli5: Optional[str] = None
    definition: Optional[str] = None
    familiarity: int = Field(0, ge=0, le=10)
    video: Optional[str] = None
    domain: Optional[str] = None
    source: Optional[str] = None
    type: DictEntryType = "term"
    starred: bool = False


class DictEntryUpdate(BaseModel):
    name: Optional[str] = None
    eli5: Optional[str] = None
    definition: Optional[str] = None
    familiarity: Optional[int] = Field(None, ge=0, le=10)
    video: Optional[str] = None
    domain: Optional[str] = None
    source: Optional[str] = None
    type: Optional[DictEntryType] = None
    starred: Optional[bool] = None


class DictQuestionCreate(BaseModel):
    question: str
    answer: Optional[str] = None


class DictQuestionUpdate(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None


class DictNoteCreate(BaseModel):
    text: str
    image: Optional[str] = None


class DictFromConcept(BaseModel):
    """One-click capture of a workspace :Concept into the dictionary."""
    name: str
    definition: Optional[str] = None
    domain: Optional[str] = None
    familiarity: int = Field(0, ge=0, le=10)
    type: DictEntryType = "term"


# --------------------------------------------------------------------------- #
# Tasks
# --------------------------------------------------------------------------- #
# Tasks are a Mainframe-level service (per TASKS_SPEC) — a task is a living
# journal, not a checkbox. Every field except title + horizon is optional.
Horizon = Literal["long", "medium", "short"]
ModuleName = Literal["synapse", "vitality", "cortex", "inventory"]
TaskStatus = Literal["active", "done", "hidden", "parked"]
Priority = Literal["low", "medium", "high"]
EntryType = Literal[
    "initial_idea", "progress", "note", "blocker", "reflection", "completed"
]


class TaskCreate(BaseModel):
    title: str
    horizon: Horizon = "short"
    module: ModuleName = "synapse"
    est_time: Optional[str] = None
    due_date: Optional[date] = None
    parent_id: Optional[str] = None
    priority: Priority = "medium"
    notes: Optional[str] = None  # if set → becomes the first "initial_idea" entry
    # When the clock starts. Defaults to now, but it's yours to set: a task
    # written down today may have actually begun last week, and `created_at`
    # (when the row was made) can't be changed without lying about the record.
    opened_at: Optional[str] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    horizon: Optional[Horizon] = None
    module: Optional[ModuleName] = None
    est_time: Optional[str] = None
    due_date: Optional[date] = None
    parent_id: Optional[str] = None
    priority: Optional[Priority] = None
    status: Optional[TaskStatus] = None
    done: Optional[bool] = None
    hidden: Optional[bool] = None  # convenience → maps to status active/hidden
    # The two ends of a task's life. Both editable, and both clearable by
    # sending null — together they're what "how long did this take" is measured
    # from, so a wrong one has to be fixable.
    opened_at: Optional[str] = None
    done_at: Optional[str] = None


class TaskEntryCreate(BaseModel):
    """One journal entry appended to a task's timeline.

    `date`/`time_of_day` are user-set (pre-filled with now client-side, but the
    user can log work they did earlier). `time_spent_mins` is what accumulates.
    """
    type: EntryType = "progress"
    date: Optional[str] = None        # ISO datetime the user set (not auto)
    time_of_day: Optional[str] = None
    time_spent_mins: int = 0
    time_spent_label: Optional[str] = None
    notes: str
    learned: Optional[str] = None
    next_step: Optional[str] = None


class TaskEntryUpdate(BaseModel):
    """Edit an existing journal entry (e.g. fix its date from the timeline)."""
    type: Optional[EntryType] = None
    date: Optional[str] = None
    time_of_day: Optional[str] = None
    time_spent_mins: Optional[int] = None
    time_spent_label: Optional[str] = None
    notes: Optional[str] = None
    learned: Optional[str] = None
    next_step: Optional[str] = None


# --------------------------------------------------------------------------- #
# References
# --------------------------------------------------------------------------- #
class RefToggle(BaseModel):
    source_id: str  # cites
    target_id: str  # cited
    state: Literal["none", "cites", "highlighted"]


class ReferenceCreate(BaseModel):
    """One cited work stored on a paper (name + link, citation-map ready)."""
    title: str
    link: Optional[str] = None
    year: Optional[int] = None


# How far you've got with a reference while scanning a bibliography.
# in_library is set automatically when the title matches a paper you own.
RefState = Literal["unread", "read", "in_library", "dismissed"]


class RefStateSet(BaseModel):
    state: RefState


class RefFlagSet(BaseModel):
    """Star a cited work, and pin the reason to it.

    The star is what draws the citation edge yellow on the Reference Map; the
    note is why it's yellow ("read after the methods paper"). Both are optional
    and independent — sending one leaves the other alone.
    """
    starred: Optional[bool] = None
    note: Optional[str] = None


class BulkRefs(BaseModel):
    """A bibliography pasted as text. `commit=False` previews without storing."""
    text: str
    commit: bool = False
    replace: bool = False   # clear the paper's existing references first


class RefNodeCreate(BaseModel):
    """A manual node on the Reference Map (not tied to a paper)."""
    label: str
    type: str = "note"


class RefEdgeCreate(BaseModel):
    """A manual edge between any two Reference-Map nodes (paper/reference/manual)."""
    source_id: str
    target_id: str
    label: str = "relates"


# --------------------------------------------------------------------------- #
# Mind dump — global quick-capture inbox (Mainframe-level)
# --------------------------------------------------------------------------- #
MindKind = Literal["idea", "look-at", "note"]


class MindDumpCreate(BaseModel):
    text: str
    detail: str = ""                 # longer body, shown when the card is expanded
    kind: MindKind = "idea"
    link: Optional[str] = None       # optional URL to "come look at this"
    paper_id: Optional[str] = None   # optional link back to a paper


class MindAnalyse(BaseModel):
    """POST /api/mind/analyse — a spoken (or typed) journal to pull points from.
    Returns a proposal and saves nothing."""
    text: str
    prompt_override: Optional[str] = None


class MindPoint(BaseModel):
    """One proposed point, after the user has corrected it.

    `dest` is where it lands. "journal" keeps it as a capture card here;
    "inbox" sends it to the Inbox as a real row, where `inbox_kind` decides
    idea or task and `project_id` optionally gives it to a project in the same
    move — which is what puts it in the project tree while leaving it visible
    in the Inbox. A point you only wanted to remember saying stays here.
    """
    text: str
    kind: MindKind = "note"          # the journal card's kind
    quote: str = ""                  # the words it came from, verbatim
    dest: Literal["journal", "inbox"] = "journal"
    inbox_kind: Literal["idea", "task"] = "idea"
    project_id: str = ""             # only meaningful when dest == "inbox"


class MindCommit(BaseModel):
    """Save a talked-through journal: the transcript, and the points kept.

    `transcript` is saved whole and first — the points hang off it, so a point
    can always show the sentence it came from even after you edit its wording.
    """
    transcript: str
    title: str = ""                  # defaults to the first line of the transcript
    points: list[MindPoint] = []


class MindDumpUpdate(BaseModel):
    text: Optional[str] = None
    detail: Optional[str] = None
    kind: Optional[str] = None
    status: Optional[str] = None     # "open" | "done"
    link: Optional[str] = None
    paper_id: Optional[str] = None


# --------------------------------------------------------------------------- #
# Vault — finance / inventory / assets (VAULT_SPEC)
# --------------------------------------------------------------------------- #
AccountType = Literal["current", "savings", "digital", "cash", "investment", "crypto"]
TxType = Literal["expense", "income", "transfer"]
Verdict = Literal["needed", "wanted", "wasteful", ""]


class AccountCreate(BaseModel):
    name: str
    type: AccountType = "current"
    provider: str = ""
    balance: float = 0.0
    currency: str = "GBP"


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    provider: Optional[str] = None
    balance: Optional[float] = None
    currency: Optional[str] = None


class TransactionCreate(BaseModel):
    date: str
    description: str
    amount: float                  # sign is normalised server-side from `type`
    type: TxType = "expense"
    category: str = "Other"
    account_id: Optional[str] = None
    verdict: Verdict = ""
    tags: list[str] = []
    notes: str = ""


class TransactionUpdate(BaseModel):
    date: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    type: Optional[str] = None
    category: Optional[str] = None
    account_id: Optional[str] = None
    verdict: Optional[str] = None
    tags: Optional[list[str]] = None
    notes: Optional[str] = None


class BudgetCategoryCreate(BaseModel):
    """User-defined — the spec is explicit that budget categories are NOT
    hardcoded. Name should match the transaction category it budgets for."""

    name: str
    icon: str = "📌"
    amount: float = 0.0          # monthly target in £


class BudgetCategoryUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    amount: Optional[float] = None
    order: Optional[int] = None


class MonthCellSet(BaseModel):
    """A hand-typed month × category spend. amount None clears it, and the
    cell falls back to the sum from Transactions."""
    month: str                   # "YYYY-MM"
    category: str
    amount: Optional[float] = None


class IncomeSet(BaseModel):
    month: str                   # "YYYY-MM"
    amount: float


class InvestmentCreate(BaseModel):
    """Snapshot values — nothing here auto-updates (spec). `extra=allow` keeps
    the door open for the spec's future api_source / ticker / last_api_sync."""

    model_config = {"extra": "allow"}
    name: str
    type: str = "ETF"            # ETF | Stock | Crypto | Bond | Property | Other
    platform: str = ""
    amount_invested: float = 0.0
    current_value: float = 0.0
    strategy: str = "Monthly DCA"   # Monthly DCA | Lump sum | Opportunistic | Hold
    notes: str = ""


class InvestmentUpdate(BaseModel):
    model_config = {"extra": "allow"}
    name: Optional[str] = None
    type: Optional[str] = None
    platform: Optional[str] = None
    amount_invested: Optional[float] = None
    current_value: Optional[float] = None
    strategy: Optional[str] = None
    notes: Optional[str] = None


class InventoryCreate(BaseModel):
    name: str
    category: str = "other"      # tech|books|gaming|tools|clothing|furniture|other
    location: str = ""
    status: str = "owned"        # active|in-use|owned|stored|need|want|broken|sold
    value: float = 0.0           # what it's worth, or the LOW end of an estimate
    value_max: float = 0.0       # optional HIGH end; 0 means "it's a single figure"
    acquired: str = ""           # when you got it: YYYY | YYYY-MM | YYYY-MM-DD ("" = unknown)
    notes: str = ""
    link: str = ""


class InventoryUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    location: Optional[str] = None
    status: Optional[str] = None
    value: Optional[float] = None
    value_max: Optional[float] = None
    acquired: Optional[str] = None
    notes: Optional[str] = None
    link: Optional[str] = None


class FinDiaryCreate(BaseModel):
    date: str
    title: str = ""
    text: str
    tags: list[str] = []


class FinDiaryUpdate(BaseModel):
    date: Optional[str] = None
    title: Optional[str] = None
    text: Optional[str] = None
    tags: Optional[list[str]] = None


class BulkImport(BaseModel):
    """Paste straight from a banking app. `dry_run` parses and returns a preview
    without writing anything — the spec requires a preview step before import."""

    text: str
    account_id: Optional[str] = None
    dry_run: bool = True


# --------------------------------------------------------------------------- #
# Vision — content-creation module (VISION_SPEC)
# --------------------------------------------------------------------------- #
class PipelineCreate(BaseModel):
    name: str
    description: str = ""


class PipelineUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class StageCreate(BaseModel):
    """A pipeline stage. The user defines every field — Blueprint is a template
    builder, so nothing here is a fixed/known stage (spec is explicit)."""

    name: str
    inputs: list[str] = []       # what feeds in — one per line in the UI
    outputs: list[str] = []      # what it produces
    tools: list[str] = []        # tools/LLMs, e.g. "Claude — script refinement"
    process: str = ""            # freeform checklist of how you do this stage


class StageUpdate(BaseModel):
    name: Optional[str] = None
    inputs: Optional[list[str]] = None
    outputs: Optional[list[str]] = None
    tools: Optional[list[str]] = None
    process: Optional[str] = None


class StageReorder(BaseModel):
    stage_ids: list[str]         # full ordered list of this pipeline's stages


VideoType = Literal["educational", "short", "big-project", "tutorial", "vlog", "series"]


class VideoCreate(BaseModel):
    """A YouTube video is a production workspace (VISION_UPDATE_SPEC), not just
    a tracking card. Research/markers/prompts/panels/thumbnails hang off it as
    their own nodes; these are the fields that live on the video itself."""

    title: str
    type: VideoType = "educational"
    pipeline_id: Optional[str] = None    # which Blueprint pipeline it follows
    stage: str = ""                      # comes from that pipeline's stage list
    target_date: Optional[str] = None
    description: str = ""                # concept / hook / angle
    framework: str = ""                  # e.g. "Hook→Story→CTA"
    llms_used: str = ""
    tags: list[str] = []
    notes: str = ""


class VideoUpdate(BaseModel):
    title: Optional[str] = None
    type: Optional[str] = None
    pipeline_id: Optional[str] = None
    stage: Optional[str] = None
    target_date: Optional[str] = None
    thumbnail: Optional[str] = None
    description: Optional[str] = None
    script: Optional[str] = None
    framework: Optional[str] = None
    llms_used: Optional[str] = None
    tags: Optional[list[str]] = None
    notes: Optional[str] = None


class JournalEntryCreate(BaseModel):
    text: str
    date: Optional[str] = None           # defaults to now


class ResearchNoteCreate(BaseModel):
    """Where you dump links, paper references, competitor video analysis."""

    title: str
    url: Optional[str] = None
    summary: str = ""


class ResearchNoteUpdate(BaseModel):
    title: Optional[str] = None
    url: Optional[str] = None
    summary: Optional[str] = None


# The 8 marker labels the spec enumerates. Stored as these keys; the frontend
# owns their icon/colour so the two never drift apart in the database.
MarkerLabel = Literal[
    "hook", "key-point", "abstraction", "data", "transition", "climax", "cta", "broll",
]


class ScriptMarkerCreate(BaseModel):
    """Annotates a LINE RANGE of the script — "the hook is here, the CTA is at
    the end". A visual map of the script's structure, for the user's own eye."""

    line_start: int = Field(1, ge=1)
    line_end: int = Field(1, ge=1)
    label: MarkerLabel = "key-point"
    note: str = ""


class ScriptMarkerUpdate(BaseModel):
    line_start: Optional[int] = Field(None, ge=1)
    line_end: Optional[int] = Field(None, ge=1)
    label: Optional[str] = None
    note: Optional[str] = None


class WritingCreate(BaseModel):
    """A blog/article/thread tracked through a Blueprint pipeline, same as a
    video — the stage list comes from the pipeline, never hardcoded."""

    title: str
    type: str = "Blog"           # Blog | Article | Thread | Newsletter | Essay
    platform: str = "Blog"       # Blog | Medium | Substack | LinkedIn | Twitter | Other
    pipeline_id: Optional[str] = None
    stage: str = ""
    link: str = ""
    notes: str = ""


class WritingUpdate(BaseModel):
    title: Optional[str] = None
    type: Optional[str] = None
    platform: Optional[str] = None
    pipeline_id: Optional[str] = None
    stage: Optional[str] = None
    link: Optional[str] = None
    notes: Optional[str] = None


class PortfolioCreate(BaseModel):
    title: str
    description: str = ""
    type: str = "Code"           # Code | Research | Video | Design | Tool | Writing | Other
    link: str = ""
    image: str = ""
    images: list[str] = []
    tags: list[str] = []


class PortfolioUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    link: Optional[str] = None
    image: Optional[str] = None
    images: Optional[list[str]] = None
    tags: Optional[list[str]] = None


class ContactCreate(BaseModel):
    name: str
    role: str = ""               # e.g. "AI YouTuber", "lab researcher"
    platform: str = ""
    link: str = ""
    notes: str = ""
    avatar: str = ""
    known_from: str = ""         # where you know them from — "Twitter", "uni cohort"
    first_contact: str = ""      # YYYY-MM-DD; "" not null (Neo4j drops null props)
    email: str = ""
    urgency: Literal["", "red", "blue", "green"] = ""   # the "!" you click to cycle


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    platform: Optional[str] = None
    link: Optional[str] = None
    notes: Optional[str] = None
    avatar: Optional[str] = None
    known_from: Optional[str] = None
    first_contact: Optional[str] = None
    email: Optional[str] = None
    urgency: Optional[Literal["", "red", "blue", "green"]] = None


class ContactInteractionCreate(BaseModel):
    """One time you were in touch — the dated log behind "last contacted"."""
    date: str                    # YYYY-MM-DD
    channel: str = ""            # email, DM, call, met in person…
    note: str = ""


class StoryPanelCreate(BaseModel):
    """One storyboard panel: the PLAN for a shot, never the shot itself.
    `image` is a URL string — either external, or /api/images/<id>/file for one
    uploaded through the Mainframe image service. Video files are never stored."""

    caption: str = ""
    dialog: str = ""
    duration: str = ""           # rough timing, e.g. "0:00-0:15"
    notes: str = ""              # camera angle, b-roll, effects
    image: str = ""


class StoryPanelUpdate(BaseModel):
    caption: Optional[str] = None
    dialog: Optional[str] = None
    duration: Optional[str] = None
    notes: Optional[str] = None
    image: Optional[str] = None


class PanelReorder(BaseModel):
    panel_ids: list[str]


class ThumbnailOptionCreate(BaseModel):
    image: str = ""
    style: str = ""              # e.g. "minimal text", "face close-up"
    notes: str = ""


class ThumbFeedbackCreate(BaseModel):
    text: str
    verdict: Literal["", "like", "dislike"] = ""


class ThumbnailOptionUpdate(BaseModel):
    image: Optional[str] = None
    style: Optional[str] = None
    notes: Optional[str] = None
    chosen: Optional[bool] = None


PromptStatus = Literal["draft", "approved", "rejected", "edited"]


class PromptEntryCreate(BaseModel):
    """One LLM prompt/response pair. MANUAL — the user pastes both in; nothing
    here calls a model API (spec is explicit).

    `model_config extra="allow"` deliberately leaves room for the spec's FUTURE
    input_tokens / output_tokens / cost / energy fields without a migration.
    """

    model_config = {"extra": "allow"}
    llm: str                             # e.g. "Claude Opus", "GPT-4o"
    prompt: str
    response: str = ""
    variation: str = ""                  # how this differed from other attempts
    status: PromptStatus = "draft"
    notes: str = ""


class PromptEntryUpdate(BaseModel):
    model_config = {"extra": "allow"}
    llm: Optional[str] = None
    prompt: Optional[str] = None
    response: Optional[str] = None
    variation: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class ImageUpdate(BaseModel):
    """Rename only — the file itself is immutable once uploaded."""

    name: Optional[str] = None


class ReorderRequest(BaseModel):
    """Manual card ordering: the listed ids take the positions those same nodes
    currently occupy, reassigned in the order given. Sending just two ids is a
    swap; sending the whole list is a full reorder. Untouched nodes keep their
    slots, so reordering inside a filtered view is safe."""

    ids: list[str]


# --------------------------------------------------------------------------- #
# Work type — the second axis, shared by a Project and by every WorkSession
# logged against one. Defined here because a Project is the first thing to
# carry it; the work models below reuse these same names.
#
# Distinct from `ref_kind` further down, which says what the work was ON (a
# paper, a project, a habit). This says what doing it actually was: reading a
# book and writing a compiler are both "on a project" and are not the same
# activity. Closed because the whole point is comparing four totals at the end
# of a week; a fifth type invented on a Tuesday makes last month unreadable.
# --------------------------------------------------------------------------- #
WorkType = Literal["study", "build", "admin", "body"]
WORK_TYPES = ("study", "build", "admin", "body")
# What an unclassified thing falls back to. Study, not build: most of what gets
# logged here is reading, and a wrong default that flatters the build number is
# worse than one that does not.
DEFAULT_WORK_TYPE = "study"


# --------------------------------------------------------------------------- #
# Projects — files uploaded or linked, each with a note (Mainframe-level)
# --------------------------------------------------------------------------- #
class ProjectCreate(BaseModel):
    name: str
    note: str = ""
    # What working on this project IS — and the default every session pushed
    # onto it inherits. See WorkType.
    kind: WorkType = DEFAULT_WORK_TYPE
    # Same "point it at something real" pair the Repository uses (see
    # ProjectUpdate) — a project can be brought in already knowing what it is
    # about.
    link_kind: Optional[str] = None
    link_id: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    note: Optional[str] = None
    kind: Optional[WorkType] = None
    # Projects nest: (:Project)-[:PARENT]->(:Project). An empty string detaches,
    # which is why this is a string rather than None-means-clear — None already
    # means "not sent".
    parent_id: Optional[str] = None
    # "add to the contributions" — when true, working on this project puts a
    # border on that day's square in the grid.
    contributes: Optional[bool] = None
    status: Optional[str] = None
    repo: Optional[str] = None
    # The referenced id: what this project IS ABOUT elsewhere in Mainframe — a
    # paper, a decomposition node, an idea, or another project. Exactly the
    # pair a Repository entry carries, so the two read the same way. Sending
    # link_kind = "" detaches (null can't, the patch drops nulls).
    link_kind: Optional[str] = None
    link_id: Optional[str] = None


# --------------------------------------------------------------------------- #
# Project passes — v1, v2, ... on a project.
#
# The Repository's reading instances, for work you do rather than read: a pass
# is one run at a project with a purpose ("scaffold", "vault module") and the
# things you already know you want to come back to. Work sessions are logged
# INTO a pass (WorkSession.pass_id), so the hours group by what you were
# trying to do, not just by date.
# --------------------------------------------------------------------------- #
class ProjectPassCreate(BaseModel):
    purpose: str = "first pass"
    look_into: Optional[str] = None
    notes: Optional[str] = None
    link_kind: Optional[str] = None    # what this pass was worked against
    link_id: Optional[str] = None


class ProjectPassUpdate(BaseModel):
    purpose: Optional[str] = None
    look_into: Optional[str] = None
    notes: Optional[str] = None
    link_kind: Optional[str] = None
    link_id: Optional[str] = None
    position: Optional[float] = None   # manual ordering; `version` never moves


class ProjectLinkCreate(BaseModel):
    """Register a file/repo the user already owns (not uploaded)."""
    name: str
    url: Optional[str] = None     # external URL
    path: Optional[str] = None    # local filesystem path
    note: str = ""


class ProjectPush(BaseModel):
    """Mark that the project was pushed — puts a ★ on that day's square."""
    date: Optional[str] = None    # YYYY-MM-DD; defaults to today
    note: str = ""
    mins: int = 0                 # optional time attached to the push


class HeatCellUpdate(BaseModel):
    date: str            # "YYYY-MM-DD"
    color: Optional[str] = None  # hex; empty/None clears the override


# --------------------------------------------------------------------------- #
# Work sessions — the Mainframe-level "database" row.
#
# One row = one block of work. Every module pushes into the same shape, and the
# same rows drive the contribution grid (time worked → colour, a contributing
# project → border, a push → star). Every field is present on every session;
# anything that doesn't apply to a given row is masked with 0 / "" / "none"
# rather than being absent, so the table stays one uniform grid.
# --------------------------------------------------------------------------- #
WorkModule = Literal["synapse", "pulse", "vision", "vault", "mainframe"]
# What a work session was ON. Deliberately a plain string, not a Literal: the
# kinds are user-extensible (:WorkKind nodes) — "book", "client", whatever you
# work on — and a closed enum would reject a kind you'd just created.
RefKind = str
FocusKind = Literal["active", "passive", "none"]


class WorkSessionCreate(BaseModel):
    date: Optional[str] = None        # YYYY-MM-DD; defaults to today
    start: str = ""                   # "HH:MM" — blank when not tracked
    end: str = ""                     # "HH:MM"
    mins: int = 0                     # duration; 0 = not recorded
    module: WorkModule = "synapse"
    ref_kind: RefKind = "other"
    ref_id: Optional[str] = None
    ref_title: str = ""
    # study | build | admin | body. Left unset, it is taken from the project
    # the session is being pushed onto, which is why it is Optional rather
    # than defaulted here: "not sent" and "deliberately study" have to be
    # tellable apart, or every push would overwrite the project's own type.
    kind: Optional[WorkType] = None
    what: str = ""                    # what I did
    focus: FocusKind = "none"         # active learning / passive / n-a
    distraction_mins: int = 0         # legacy: still accepted, no longer shown
    distraction: str = ""             # (the workspace logs distractions properly)
    notes: str = ""
    # Marks the row as a finished piece of work — set by hand from the table.
    # `pushed` is the old name for the same flag and is still accepted so
    # anything posting the old field keeps working.
    completed: bool = False
    pushed: bool = False
    # Which project pass this hour belongs to, when it belongs to one. Plain
    # string, not a relationship: a session outlives the pass it was logged
    # under, and deleting a pass must not take the hours with it.
    pass_id: str = ""
    # The Repository reading pass (:Instance) this hour belongs to. Same rule
    # as pass_id and for the same reason: a paper's hours outlive the pass they
    # were read in, so deleting a pass must not delete the time.
    instance_id: str = ""
    # The document this session was written in, when it was pushed from one.
    # Drawn as (:WorkSession)-[:WORKED_ON]->(:Document) rather than a property:
    # the doc's hours are an aggregate over that edge, and a deleted document
    # must take its edge with it without touching the hours.
    doc_id: Optional[str] = None


class WorkSessionUpdate(BaseModel):
    date: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    mins: Optional[int] = None
    module: Optional[WorkModule] = None
    ref_kind: Optional[RefKind] = None
    ref_id: Optional[str] = None
    ref_title: Optional[str] = None
    kind: Optional[WorkType] = None
    what: Optional[str] = None
    focus: Optional[FocusKind] = None
    distraction_mins: Optional[int] = None
    distraction: Optional[str] = None
    notes: Optional[str] = None
    completed: Optional[bool] = None
    pushed: Optional[bool] = None
    pass_id: Optional[str] = None     # "" moves the session out of every pass
    instance_id: Optional[str] = None  # "" unfiles it from its reading pass


class WorkKindCreate(BaseModel):
    """A user-defined kind of thing you work on — book, client, admin…"""
    name: str


# --------------------------------------------------------------------------- #
# Knowledge graph (triple layer)
# --------------------------------------------------------------------------- #
KGLayer = Literal["manual", "auto", "auto_edit"]


class KGNodeCreate(BaseModel):
    paper_id: Optional[str] = None
    name: str
    type: str = "concept"
    layer: KGLayer = "manual"
    x: Optional[float] = None
    y: Optional[float] = None


class KGNodeUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    edit_reason: Optional[str] = None


class KGEdgeCreate(BaseModel):
    source_id: str
    target_id: str
    label: str = "RELATES"
    layer: KGLayer = "manual"


# --------------------------------------------------------------------------- #
# Deep dive
# --------------------------------------------------------------------------- #
DeepDiveStatus = Literal["planned", "active", "completed"]


class DeepDiveCreate(BaseModel):
    topic: str
    info: str = ""
    module: str = "synapse"


class DeepDiveUpdate(BaseModel):
    topic: Optional[str] = None
    info: Optional[str] = None
    sources_text: Optional[str] = None


class DeepDiveSourceCreate(BaseModel):
    title: str
    link: Optional[str] = None


# --------------------------------------------------------------------------- #
# Planner (PLANNER_SPEC — Mainframe-level service, tab lives in Synapse)
# --------------------------------------------------------------------------- #
PlanCategory = Literal["study", "build", "paper", "fixed", "fitness", "event"]
PlanPlacement = Literal["auto", "manual"]
PlanMarker = Literal["none", "priority", "important"]
# weekday = Mon–Fri slots only, weekend = Sat–Sun only, any = every slot
PlanDayPref = Literal["any", "weekday", "weekend"]


class PlanItemCreate(BaseModel):
    name: str
    description: str = ""
    module: str = "general"          # synapse | vision | pulse | vault | general
    category: PlanCategory = "study"
    # total is the planning number; omit it and it becomes the midpoint of
    # the low/high estimate range
    total_hours: Optional[float] = None
    hours_low: Optional[float] = None
    hours_high: Optional[float] = None
    reasoning: str = ""              # why this item, why these numbers
    hours_per_week: float = 0.0      # 0 means unscheduled (v2 §2)
    # placement defaults from category: study/build/paper auto, the rest manual
    placement: Optional[PlanPlacement] = None
    marker: PlanMarker = "none"
    day_pref: PlanDayPref = "any"    # optional guide for auto-placement
    start_date: Optional[date] = None   # defaults to today


class PlanItemUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    module: Optional[str] = None
    category: Optional[PlanCategory] = None
    total_hours: Optional[float] = None
    hours_low: Optional[float] = None
    hours_high: Optional[float] = None
    reasoning: Optional[str] = None
    hours_per_week: Optional[float] = None
    placement: Optional[PlanPlacement] = None
    marker: Optional[PlanMarker] = None
    day_pref: Optional[PlanDayPref] = None
    start_date: Optional[date] = None
    status: Optional[Literal["active", "queued", "done", "dropped"]] = None


class PlanReorder(BaseModel):
    ids: list[str]


class PlanCompleteBody(BaseModel):
    note: str = ""                   # the single conclusion note (spec §4)


class PlanSessionManual(BaseModel):
    start: datetime
    minutes: int
    note: str = ""


class PlanSessionUpdate(BaseModel):
    minutes: Optional[int] = None
    note: Optional[str] = None


class PlanFocusStop(BaseModel):
    note: str = ""


class PlanNoteCreate(BaseModel):
    text: str
    item_id: Optional[str] = None    # None → inbox
    origin: Literal["topbar", "focus_view", "session_close"] = "topbar"


class PlanLinkCreate(BaseModel):
    kind: Literal["task", "paper", "video"]
    target_id: str


class PlanSlot(BaseModel):
    """One recurring open slot in the weekly rhythm (v2 §2 :SlotTemplate)."""
    dow: int = Field(ge=0, le=6)      # 0 = Monday
    start: str                        # "HH:MM"
    length_min: int = Field(gt=0, le=24 * 60)


class PlanDayBounds(BaseModel):
    start: str = "06:00"
    end: str = "22:00"


class PlannerSettingsUpdate(BaseModel):
    """Every field optional — the Budget sliders PATCH one at a time."""
    capacity: Optional[float] = None            # v1 name, kept as an alias
    capacity_per_week: Optional[float] = None
    horizon_date: Optional[date] = None
    day_bounds: Optional[PlanDayBounds] = None
    slots: Optional[list[PlanSlot]] = None


# Named Plan* rather than Cal*: the Calendar module further down this file
# already owns CalEventCreate/CalEventUpdate with a different shape (date +
# "HH:MM"), and the later definition would silently shadow these.
class PlanEventCreate(BaseModel):
    title: str
    start: datetime
    end: datetime
    category: PlanCategory = "event"
    marker: PlanMarker = "none"
    item_id: Optional[str] = None


class PlanEventUpdate(BaseModel):
    title: Optional[str] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    category: Optional[PlanCategory] = None
    marker: Optional[PlanMarker] = None
    item_id: Optional[str] = None
    hidden: Optional[bool] = None               # external events hide, never delete


class PlanDayBlockCreate(BaseModel):
    reason: str = ""


# --------------------------------------------------------------------------- #
# Ideas (spreadsheet-like; extra columns allowed)
# --------------------------------------------------------------------------- #
class IdeaCreate(BaseModel):
    model_config = {"extra": "allow"}  # user-defined custom columns
    title: str = ""
    description: str = ""
    category: str = "research"
    priority: Literal["low", "medium", "high"] = "medium"
    # raw -> given -> (or) dropped. `given` is never typed: it is set when the
    # GIVEN_TO edge is drawn. Rows created before this vocabulary keep whatever
    # status they had; the table still offers it on those rows so nothing is
    # silently rewritten.
    status: Literal["raw", "given", "dropped"] = "raw"
    paper_id: Optional[str] = None   # kept in step with the CAME_FROM edge
    notes: str = ""


class RaiseToGoal(BaseModel):
    """POST /api/projects/{id}/goals — the only way a goal is created.

    `idea_ids` are ideas from the given-to table above the form, ticked as what
    this goal came out of. `why` is written as a note against the goal, so the
    Reasoning tab picks it up like every other why in the system.
    """
    text: str
    estimate_h: float = 0.0
    due: str = ""
    horizon: Literal["day", "week", "month"] = "month"
    why: str = ""
    idea_ids: list[str] = []


class IdeaGivenTo(BaseModel):
    """POST /api/synapse/ideas/{id}/given-to — hand an idea to a project.

    An empty `project_id` takes it back: the edge is deleted and the idea
    returns to `raw`. The why is written separately, against the edge, by the
    client at the same moment; it is not carried here because a note that only
    exists as a side effect of another write is a note that gets skipped.
    """
    project_id: str = ""


class IdeaCameFrom(BaseModel):
    """POST /api/synapse/ideas/{id}/came-from — where an idea came out of.

    One edge for both kinds of source. An empty `source_id` clears it.
    """
    source_id: str = ""
    kind: Literal["project", "paper"] = "project"


class IdeaCategoryUpsert(BaseModel):
    """A kind of idea and the colour that marks it. Kinds are user-extensible —
    the colour lives on the kind, so every idea of that kind reads the same."""
    name: str
    color: str = "#7FA8C8"


class IdeaUpdate(BaseModel):
    model_config = {"extra": "allow"}
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    paper_id: Optional[str] = None
    notes: Optional[str] = None


# --------------------------------------------------------------------------- #
# Custom headers / sections
# --------------------------------------------------------------------------- #
class HeaderCreate(BaseModel):
    name: str
    description: Optional[str] = None
    order: int = 0
    paper_id: Optional[str] = None
    content: str = ""


class HeaderUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    order: Optional[int] = None
    content: Optional[str] = None


# --------------------------------------------------------------------------- #
# Raw Cypher (power user)
# --------------------------------------------------------------------------- #
class CypherQuery(BaseModel):
    cypher: str
    params: dict[str, Any] = {}


# --------------------------------------------------------------------------- #
# PULSE module — habits, experiments, routines, medical, medications
# --------------------------------------------------------------------------- #
HabitFrequency = Literal["daily", "weekdays", "3x-week", "weekly", "custom"]
# Habits by area (mainframe_habits_areas.html). How a habit's days get ticked:
#   tick      — by hand (HabitLog level > 0)
#   recovery  — a recovery session of one of `source_types` that day
#   workout   — a logged workout (any type, or one of `source_types`)
#   food      — anything logged in Nutrition that day
#   study     — work sessions of kind `source_types` (default study+build), ≥ `source_min` minutes
#   no_spend  — no expense transaction that day
HabitSource = Literal["tick", "recovery", "workout", "food", "study", "no_spend"]
HabitTier = Literal["main", "experimental", "minor"]


class HabitAreaFields(BaseModel):
    """Fields shared by create and update for the areas view. All optional."""
    area: Optional[str] = None           # HabitArea key; unset → derived from category
    tier: Optional[HabitTier] = None
    trial_weeks: Optional[int] = Field(None, ge=1, le=52)
    trial_start: Optional[str] = None    # YYYY-MM-DD, set when a trial starts
    source: Optional[HabitSource] = None
    source_types: Optional[list[str]] = None
    source_min: Optional[int] = Field(None, ge=0)
    per_week: Optional[int] = Field(None, ge=1, le=7)   # weekly target, for weekly habits
    icon: Optional[str] = None


# Scheduling shared by habits and routines, so a calendar module can read
# either one without knowing which it is. days_of_week: 0=Mon … 6=Sun.
class Schedulable(BaseModel):
    days_of_week: Optional[list[int]] = None
    time_of_day: Optional[str] = None      # "HH:MM"
    duration_mins: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class HabitCreate(HabitAreaFields):
    name: str
    category: str
    frequency: HabitFrequency = "daily"
    target: Optional[str] = None
    tags: list[str] = []
    main_notes: str = ""
    days_of_week: list[int] = []
    time_of_day: str = ""
    duration_mins: int = 0


class HabitUpdate(HabitAreaFields):
    name: Optional[str] = None
    category: Optional[str] = None
    frequency: Optional[HabitFrequency] = None
    target: Optional[str] = None
    tags: Optional[list[str]] = None
    main_notes: Optional[str] = None
    active: Optional[bool] = None
    days_of_week: Optional[list[int]] = None
    time_of_day: Optional[str] = None
    duration_mins: Optional[int] = None


class HabitDayMark(BaseModel):
    date: str
    # done = ticked · exception = excused · adjust = moved/made up (on a future
    # day: a planned make-up) · clear = remove the hand mark
    state: Literal["done", "exception", "adjust", "clear"]


class HabitAreaCreate(BaseModel):
    name: str
    color: str = "#8a97a8"
    link_tab: str = ""


class HabitAreaUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    link_tab: Optional[str] = None
    order: Optional[int] = None


class SubHabitCreate(BaseModel):
    name: str


class HabitNoteCreate(BaseModel):
    text: str
    date: Optional[str] = None


class HabitLogCreate(BaseModel):
    date: str                        # the day being logged (user-set)
    level: int = Field(0, ge=0, le=4)
    time_spent: str = ""
    notes: str = ""
    feel: str = ""
    connections: str = ""            # links to other Mainframe modules


# An experiment runs for a set span. `unit` is what you typed; `days` is always
# the resolved total, so everything downstream counts in days.
DurationUnit = Literal["days", "weeks"]


class ExperimentCreate(BaseModel):
    name: str
    days: int = Field(..., ge=1)
    unit: DurationUnit = "days"
    start_date: str
    hypothesis: str = ""


class ExperimentUpdate(BaseModel):
    name: Optional[str] = None
    days: Optional[int] = None
    unit: Optional[DurationUnit] = None
    start_date: Optional[str] = None
    hypothesis: Optional[str] = None
    conclusion: Optional[str] = None
    status: Optional[Literal["active", "completed"]] = None
    days_done: Optional[list[int]] = None   # legacy toggle; day journals supersede it


class ExperimentDayUpdate(BaseModel):
    """One day of an experiment — a journal entry, not a checkbox."""
    notes: str = ""
    what_happened: str = ""
    adherence: Optional[int] = Field(None, ge=0, le=4)   # 0 missed → 4 nailed it
    feel: str = ""
    done: Optional[bool] = None


RoutineUnit = Literal["days", "weeks", "months", "ongoing"]


class RoutineCreate(BaseModel):
    name: str
    duration: Optional[int] = None
    unit: RoutineUnit = "ongoing"
    category: str = "other"
    main_notes: str = ""
    days_of_week: list[int] = []
    time_of_day: str = ""
    duration_mins: int = 0
    start_date: Optional[str] = None


class RoutineUpdate(BaseModel):
    name: Optional[str] = None
    duration: Optional[int] = None
    unit: Optional[RoutineUnit] = None
    category: Optional[str] = None
    main_notes: Optional[str] = None
    status: Optional[Literal["active", "completed", "paused"]] = None
    days_of_week: Optional[list[int]] = None
    time_of_day: Optional[str] = None
    duration_mins: Optional[int] = None
    start_date: Optional[str] = None


class RoutineStepCreate(BaseModel):
    name: str


class StepLogCreate(BaseModel):
    date: Optional[str] = None       # pre-filled today client-side
    time: str = ""
    note: str = ""


class RoutineNoteCreate(BaseModel):
    text: str


class MedicalEntryCreate(BaseModel):
    title: str
    date: str
    details: str = ""
    severity: str = ""               # mild|moderate|severe|active|resolved|chronic|monitoring|""
    tags: list[str] = []
    notes: str = ""
    links: str = ""


class MedicalEntryUpdate(BaseModel):
    title: Optional[str] = None
    date: Optional[str] = None
    details: Optional[str] = None
    severity: Optional[str] = None
    tags: Optional[list[str]] = None
    notes: Optional[str] = None
    links: Optional[str] = None


class MedEntryCreate(BaseModel):
    name: str
    date: str
    details: str = ""
    dose: str = ""
    frequency: str = ""
    status: str = ""                 # active|paused|stopped|as-needed|effective|ineffective|side-effects|""
    notes: str = ""
    tags: list[str] = []


class MedEntryUpdate(BaseModel):
    name: Optional[str] = None
    date: Optional[str] = None
    details: Optional[str] = None
    dose: Optional[str] = None
    frequency: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[list[str]] = None


# --------------------------------------------------------------------------- #
# PULSE FITNESS sub-module
# --------------------------------------------------------------------------- #
WorkoutType = Literal["Push", "Pull", "Legs", "Upper", "Lower", "Full Body", "Cardio", "HIIT", "Sport", "Other"]
Interrupted = Literal["no", "yes — pain", "yes — time", "yes — fatigue"]
CyclePhase = Literal["Hypertrophy", "Strength", "Power", "Endurance", "Deload", "Cut", "Bulk", "Maintenance", "Rehab"]
BodyStateKind = Literal["", "pain", "imbalance", "tight"]


class ExerciseIn(BaseModel):
    name: str
    detail: str = ""


class BlockIn(BaseModel):
    """One timed row of the Log workout form, warm up or exercise."""
    kind: Literal["warmup", "exercise"] = "exercise"
    from_: str = Field("", alias="from")
    to: str = ""
    exercise: str = ""
    reps: float = 0
    kg: float = 0
    rpe: Optional[int] = Field(None, ge=1, le=10)
    raw: str = ""
    group: str = ""

    model_config = {"populate_by_name": True}


class MaxIn(BaseModel):
    """A max ticked on the Log form, or set by hand on the Program tab."""
    exercise: str
    kg: float = Field(..., gt=0)
    reps: int = 1
    from_kg: Optional[float] = None
    from_reps: Optional[int] = None
    date: Optional[str] = None


class WorkoutCreate(BaseModel):
    date: str
    type: WorkoutType = "Other"
    duration: int = 0
    intensity: int = Field(5, ge=1, le=10)
    interrupted: Interrupted = "no"
    notes: str = ""
    exercises: list[ExerciseIn] = []
    cycle_id: Optional[str] = None
    # The timed Log form (fitness-logworkout.js). All optional so the old
    # single-textarea payload still posts.
    fatigue_before: Optional[int] = Field(None, ge=1, le=10)
    warmup_min: Optional[int] = None
    duration_min: Optional[int] = None
    program_day_id: Optional[str] = None
    blocks: list[BlockIn] = []
    confirmed_maxes: list[MaxIn] = []
    # Cardio rows, each saved as a (:CardioSession) linked to the workout.
    cardio: list[CardioBlockIn] = []


class PrescriptionIn(BaseModel):
    exercise: str
    sets: Optional[int] = None
    reps: Optional[int] = None
    pct_max: Optional[float] = None
    notes: str = ""


class ProgramDaySet(BaseModel):
    """A cycle's training day. Days repeat every week of the cycle."""
    day: int = Field(..., ge=1)
    label: str = ""
    prescriptions: list[PrescriptionIn] = []


class WorkoutUpdate(BaseModel):
    date: Optional[str] = None
    type: Optional[WorkoutType] = None
    duration: Optional[int] = None
    intensity: Optional[int] = Field(None, ge=1, le=10)
    interrupted: Optional[Interrupted] = None
    notes: Optional[str] = None


class CycleCreate(BaseModel):
    name: str
    weeks: int = Field(..., ge=1)
    start_date: str
    phase: CyclePhase = "Hypertrophy"
    goals: str = ""
    notes: str = ""


class CycleUpdate(BaseModel):
    name: Optional[str] = None
    weeks: Optional[int] = None
    phase: Optional[CyclePhase] = None
    goals: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[Literal["active", "completed"]] = None
    weeks_done: Optional[list[int]] = None


class GoalCreate(BaseModel):
    text: str
    current: str = ""
    target: str = ""


class GoalUpdate(BaseModel):
    text: Optional[str] = None
    current: Optional[str] = None
    target: Optional[str] = None


class ActivityLogCreate(BaseModel):
    model_config = {"extra": "allow"}   # metric fields vary with what's tracked
    date: str
    notes: str = ""


class StretchCreate(BaseModel):
    date: str
    duration: int = 0
    stretches: list[str] = []
    focus: str = ""
    notes: str = ""


class RecoveryTypeCreate(BaseModel):
    name: str
    icon: str = ""


class RecoverySessionCreate(BaseModel):
    date: str
    type_id: str
    duration: int = 0
    feel: str = ""
    notes: str = ""


# Recovery protocol. A protocol is a versioned bundle of habits with a reason;
# its habits are ordinary :Habit nodes, so the Habits tab sees them too.
ProtocolRule = Literal["tick", "sessions"]     # ticked by hand, or derived from sessions
ProtocolTier = Literal["main", "experimental"]


class ProtocolCreate(BaseModel):
    why: str = ""


class ProtocolUpdate(BaseModel):
    why: Optional[str] = None


class ProtocolRevise(BaseModel):
    why: str = ""
    end_reason: str = ""                 # what happened to the version being closed


class ProtocolHabitCreate(BaseModel):
    name: str
    icon: str = ""
    rule: ProtocolRule = "sessions"
    rule_types: list[str] = []           # recovery type NAMES that count (sessions rule)
    tier: ProtocolTier = "main"


class ProtocolHabitUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    rule: Optional[ProtocolRule] = None
    rule_types: Optional[list[str]] = None
    tier: Optional[ProtocolTier] = None


class ProtocolDayMark(BaseModel):
    date: str
    state: Literal["done", "exception", "clear"]


class BodyStateUpdate(BaseModel):
    state: BodyStateKind = ""


class BodyNoteCreate(BaseModel):
    text: str


class BodyDayUpdate(BaseModel):
    date: str
    state: BodyStateKind = ""


class BodyDayNoteUpdate(BaseModel):
    date: str
    text: str = ""


# --------------------------------------------------------------------------- #
# Nutrition — Pulse top-level (food DB, diary, targets, intolerances, supps)
# --------------------------------------------------------------------------- #
# NUTRITION_SPEC: nutrition is stated PER SERVING, not per 100g. A serving is
# whatever you actually eat — a slice, a scoop, 150g — so logging is "one of
# those" rather than arithmetic. Only name, serving and the four macros are
# required; every micronutrient is optional (spec's explicit DO-NOT).
SERVING_UNITS = ["g", "ml", "piece", "slice", "cup", "tbsp", "tsp", "scoop", "bowl", "can", "bottle"]

FOOD_CATEGORIES = [
    "protein", "grains", "vegetables", "fruit", "dairy", "nuts_seeds",
    "oils_fats", "bread_bakery", "drinks", "snacks", "condiments",
    "prepared_meals", "other",
]

MEAL_SLOTS = ["breakfast", "lunch", "dinner", "snacks", "pre_workout", "post_workout"]


class FoodCreate(BaseModel):
    model_config = {"extra": "allow"}   # optional micros arrive as extra fields
    name: str
    brand: str = ""
    category: str = "other"
    serving_size: float = 100
    serving_unit: str = "g"
    calories: float = 0
    protein: float = 0
    carbs: float = 0
    fat: float = 0
    # everything below is optional — never demanded when creating a food
    fibre: Optional[float] = None
    sugar: Optional[float] = None
    saturated_fat: Optional[float] = None
    sodium: Optional[float] = None
    potassium: Optional[float] = None
    cholesterol: Optional[float] = None
    vitamin_a: Optional[float] = None
    vitamin_c: Optional[float] = None
    calcium: Optional[float] = None
    iron: Optional[float] = None
    barcode: str = ""      # read by the camera scanner, or typed off the packet
    verified: bool = False


class CalEventCreate(BaseModel):
    """A block of time. Deliberately mirrors :WorkSession's shape — a separate
    `date` plus `HH:MM` start/end — so the whole app agrees on what a time is,
    and the existing date/time input helpers work unchanged."""
    model_config = {"extra": "allow"}
    title: str
    date: str                              # YYYY-MM-DD, the day it starts
    start: str = ""                        # HH:MM, empty for an all-day event
    end: str = ""
    end_date: str = ""                     # set only for multi-day events
    all_day: bool = False
    location: str = ""
    notes: str = ""
    kind: str = "event"                    # event | block | reminder
    module: str = ""                       # which module it belongs to, if any
    task_id: Optional[str] = None          # planning a task into a slot
    colour: str = ""
    # "weekly" repeats on the same weekday from `date` on, until repeat_until
    # (inclusive) or for ever. Expanded on read in list_events; one node per
    # series, so editing it edits every week.
    repeat: str = ""
    repeat_until: str = ""


class CalEventUpdate(BaseModel):
    model_config = {"extra": "allow"}
    title: Optional[str] = None
    date: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    end_date: Optional[str] = None
    all_day: Optional[bool] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    kind: Optional[str] = None
    module: Optional[str] = None
    task_id: Optional[str] = None
    colour: Optional[str] = None


class CatalogAdopt(BaseModel):
    """Copy a USDA catalogue food into the personal library at a chosen portion.

    `serving_g` is the bridge between USDA's per-100g data and the spec's
    per-serving library; `serving_label` is what you'll actually read on the
    card ("1 cup", "1 medium banana").
    """
    serving_g: float
    serving_label: str = ""
    name: str = ""            # override the USDA description if it's unwieldy


class FoodUpdate(BaseModel):
    model_config = {"extra": "allow"}
    name: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    serving_size: Optional[float] = None
    serving_unit: Optional[str] = None
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fat: Optional[float] = None
    verified: Optional[bool] = None
    favourite: Optional[bool] = None


class FoodEntryCreate(BaseModel):
    """One food eaten. `food_id` is optional so a quick-add needs no library entry."""
    date: Optional[str] = None          # defaults to today
    meal_slot: str = "snacks"
    food_id: Optional[str] = None
    food_name: str = ""
    serving_size: float = 1
    serving_unit: str = "serving"
    calories: float = 0
    protein: float = 0
    carbs: float = 0
    fat: float = 0
    fibre: Optional[float] = None
    sugar: Optional[float] = None
    sodium: Optional[float] = None
    notes: str = ""
    time: str = ""


class FoodEntryUpdate(BaseModel):
    meal_slot: Optional[str] = None
    serving_size: Optional[float] = None
    serving_unit: Optional[str] = None
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fat: Optional[float] = None
    notes: Optional[str] = None
    time: Optional[str] = None
    date: Optional[str] = None


class BulkPasteRequest(BaseModel):
    """Lines like: `Chicken breast, 150g, 248 cal, 46g protein, 0g carbs, 5g fat`."""
    text: str
    date: Optional[str] = None
    meal_slot: str = "snacks"
    dry_run: bool = False


class CopyMealsRequest(BaseModel):
    from_date: str
    to_date: Optional[str] = None       # defaults to today
    meal_slot: Optional[str] = None     # None = the whole day


class RecipeIngredientIn(BaseModel):
    food_id: Optional[str] = None
    food_name: str
    serving_size: float = 1
    serving_unit: str = "serving"
    calories: float = 0
    protein: float = 0
    carbs: float = 0
    fat: float = 0


class RecipeCreate(BaseModel):
    name: str
    servings: int = 1
    ingredients: list[RecipeIngredientIn] = []
    instructions: str = ""
    prep_time: Optional[int] = None
    cook_time: Optional[int] = None
    category: str = "other"


class RecipeUpdate(BaseModel):
    name: Optional[str] = None
    servings: Optional[int] = None
    ingredients: Optional[list[RecipeIngredientIn]] = None
    instructions: Optional[str] = None
    prep_time: Optional[int] = None
    cook_time: Optional[int] = None
    category: Optional[str] = None


class WaterCreate(BaseModel):
    date: Optional[str] = None
    amount: float                        # ml
    time: str = ""


class WeightCreate(BaseModel):
    date: Optional[str] = None
    weight: float                        # kg
    notes: str = ""


class BodyMeasurementCreate(BaseModel):
    model_config = {"extra": "allow"}
    date: Optional[str] = None
    chest: Optional[float] = None
    waist: Optional[float] = None
    hips: Optional[float] = None
    left_arm: Optional[float] = None
    right_arm: Optional[float] = None
    left_thigh: Optional[float] = None
    right_thigh: Optional[float] = None
    left_calf: Optional[float] = None
    right_calf: Optional[float] = None
    neck: Optional[float] = None
    shoulders: Optional[float] = None
    body_fat: Optional[float] = None
    notes: str = ""


class FastingStart(BaseModel):
    target_hours: float = 16
    start_time: Optional[str] = None     # defaults to now
    notes: str = ""


class FastingEnd(BaseModel):
    end_time: Optional[str] = None       # defaults to now
    notes: Optional[str] = None


class NutritionGoalsUpdate(BaseModel):
    daily_calories: Optional[int] = None
    protein_g: Optional[int] = None
    carbs_g: Optional[int] = None
    fat_g: Optional[int] = None
    fibre_g: Optional[int] = None
    water_ml: Optional[int] = None
    weight_target: Optional[float] = None
    weight_goal: Optional[str] = None    # lose | gain | maintain
    fasting_protocol: Optional[str] = None
    macro_mode: Optional[str] = None     # grams | percentage
    height_cm: Optional[float] = None    # for BMI / waist-to-height


class TargetUpdate(BaseModel):
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fat: Optional[float] = None
    sugar: Optional[float] = None
    fibre: Optional[float] = None
    salt: Optional[float] = None


class IntoleranceCreate(BaseModel):
    name: str
    severity: str = ""
    notes: str = ""


class SupplementCreate(BaseModel):
    name: str
    dose: str = ""
    timing: str = ""
    notes: str = ""


class ActivityConfigUpdate(BaseModel):
    tracked: list[str] = []


# --------------------------------------------------------------------------- #
# Benchmarks (periodic health/fitness assessments) — Pulse Fitness
# --------------------------------------------------------------------------- #
class BaselineUpdate(BaseModel):
    # extra="allow" lets the baseline also carry current metric readings as
    # mv_<metric_key> fields (e.g. mv_glucose) alongside the fixed fields below.
    model_config = {"extra": "allow"}
    age: Optional[str] = None
    height: Optional[str] = None
    weight: Optional[str] = None
    body_fat: Optional[str] = None
    resting_hr: Optional[str] = None
    goals: Optional[str] = None
    notes: Optional[str] = None


class MetricConfigUpdate(BaseModel):
    tracked: Optional[bool] = None
    name: Optional[str] = None
    unit: Optional[str] = None
    higher_is_better: Optional[bool] = None


class CustomMetricCreate(BaseModel):
    name: str
    unit: str = ""
    higher_is_better: bool = True
    category: str = "custom"


class AssessmentCreate(BaseModel):
    date: str
    label: str = ""
    type: Literal["fitness", "blood", "combined"] = "combined"
    notes: str = ""
    values: dict[str, Any] = {}   # {metric_key: {value, notes}}
    baseline: Optional[dict[str, Any]] = None   # frozen baseline fields; None = capture current


class SnapshotQuick(BaseModel):
    """One-click 'save current baseline as a snapshot'."""
    date: Optional[str] = None
    label: str = ""
    notes: str = ""


class ScheduleUpdate(BaseModel):
    frequency: Literal["monthly", "quarterly", "6-monthly", "yearly"] = "quarterly"


class ScanRequest(BaseModel):
    """Paste paper text; get back candidate terms by frequency.

    Deliberately NOT LLM-powered — the spec says the prototype uses the
    frequency algorithm, with LLM extraction as a future enhancement.
    """

    text: str
    limit: int = 80


class BulkAddTerms(BaseModel):
    """Create stub terms from the scanner: name + familiarity 0, nothing else.
    The user fills in ELI5s afterwards."""

    terms: list[str]


class HomePrefsUpdate(BaseModel):
    """Home-screen settings as an opaque blob — background choice, dim level,
    particles on/off, module card art. The frontend owns the shape so a new
    setting never needs a backend change."""

    data: dict[str, Any] = {}


# --------------------------------------------------------------------------- #
# Cardio — kept separate from strength workouts: the metrics that matter are
# distance/pace/heart rate, not sets and reps.
# --------------------------------------------------------------------------- #
CardioType = Literal["run", "walk", "cycle", "swim", "row", "hike", "other"]
# LISS = steady state; HIIT = intervals, counted in sets.
CardioStyle = Literal["liss", "hiit"]


class CardioCreate(BaseModel):
    date: str
    type: CardioType = "run"
    distance_km: float = 0.0
    duration_mins: int = 0
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None
    # minutes spent in each heart-rate zone; index 0 = Z1 … 4 = Z5
    zones: list[int] = [0, 0, 0, 0, 0]
    perceived_effort: Optional[int] = Field(None, ge=1, le=10)
    route: str = ""
    notes: str = ""
    style: Optional[CardioStyle] = None
    sets: Optional[int] = Field(None, ge=1)   # HIIT only; dropped for LISS


class CardioBlockIn(BaseModel):
    """One cardio row of the Log workout form. Duration comes from from/to."""
    from_: str = Field("", alias="from")
    to: str = ""
    type: CardioType = "run"
    distance_km: float = 0.0
    avg_hr: Optional[int] = None
    perceived_effort: Optional[int] = Field(None, ge=1, le=10)
    notes: str = ""
    style: Optional[CardioStyle] = None
    sets: Optional[int] = Field(None, ge=1)

    model_config = {"populate_by_name": True}


class CardioUpdate(BaseModel):
    date: Optional[str] = None
    type: Optional[CardioType] = None
    style: Optional[CardioStyle] = None
    sets: Optional[int] = Field(None, ge=1)
    distance_km: Optional[float] = None
    duration_mins: Optional[int] = None
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None
    zones: Optional[list[int]] = None
    perceived_effort: Optional[int] = Field(None, ge=1, le=10)
    route: Optional[str] = None
    notes: Optional[str] = None


# --------------------------------------------------------------------------- #
# Fitness baseline test — the reference point every later Benchmark compares to
# --------------------------------------------------------------------------- #
class FitnessBaselineSet(BaseModel):
    """Starting measurements + performance metrics, taken once and frozen.

    `is_reference` marks the row Benchmark assessments measure against. Exactly
    one baseline is the reference at a time.
    """
    date: Optional[str] = None
    # measurements
    weight_kg: Optional[float] = None
    height_cm: Optional[float] = None
    body_fat_pct: Optional[float] = None
    resting_hr: Optional[int] = None
    waist_cm: Optional[float] = None
    chest_cm: Optional[float] = None
    arm_cm: Optional[float] = None
    thigh_cm: Optional[float] = None
    # performance
    push_ups: Optional[int] = None
    pull_ups: Optional[int] = None
    squat_kg: Optional[float] = None
    bench_kg: Optional[float] = None
    deadlift_kg: Optional[float] = None
    plank_secs: Optional[int] = None
    run_5k_mins: Optional[float] = None
    vo2max: Optional[float] = None
    notes: str = ""


# --------------------------------------------------------------------------- #
# Documents — the Mainframe word processor (Mainframe-level, /api/docs)
#
# `format` decides how the editor treats the body and which extension the file
# on disk gets: markdown (.md) · latex (.tex) · plain (.txt).
# --------------------------------------------------------------------------- #
DocFormat = Literal["markdown", "latex", "plain"]


class DocumentCreate(BaseModel):
    title: str = "Untitled"
    format: DocFormat = "markdown"
    folder: str = ""
    content: str = ""


class DocumentUpdate(BaseModel):
    """Metadata patch. Body text goes through PUT /{id}/content instead, so a
    fast-firing autosave never has to resend the title or re-trigger a rename."""
    title: Optional[str] = None
    format: Optional[DocFormat] = None
    folder: Optional[str] = None
    starred: Optional[bool] = None
    # What this document IS PART OF — the same pair a Paper or a Project
    # carries, resolved through an :ABOUT relationship rather than a copied
    # name. Sending link_kind = "" detaches (null can't, the patch drops nulls).
    link_kind: Optional[str] = None
    link_id: Optional[str] = None
    # The project this document is FOR — the binding that sends the hours you
    # spend writing it to that project. Sending it at all is what asks to change
    # it (null clears); leaving the field off leaves the binding alone.
    project_id: Optional[str] = None


class DocumentPush(BaseModel):
    """Mark that work on this document was pushed — puts a ★ on that day's
    square, same as a project push."""
    date: Optional[str] = None    # YYYY-MM-DD; defaults to today
    note: str = ""
    mins: int = 0                 # optional time attached to the push


class DocumentContent(BaseModel):
    content: str


# --------------------------------------------------------------------------- #
# Sheets — user-defined databases (Mainframe-level, /api/sheets)
#
# A sheet is a table you design yourself: columns with types, rows, formulas,
# saved views. Cell values live as `c_<column key>` properties on :SheetRow, so
# a sheet is queryable Cypher like everything else rather than an opaque blob.
# --------------------------------------------------------------------------- #
ColumnType = Literal[
    "text", "longtext", "number", "date", "checkbox",
    "select", "multiselect", "url", "email", "formula", "link",
]


class SheetCreate(BaseModel):
    name: str = "Untitled sheet"
    description: str = ""
    # The project this table belongs to, drawn as (:Sheet)-[:FOR]->(:Project).
    # A sheet made from a project page arrives with it already set; one made in
    # the Sheets tab may or may not have picked a project. "" is no project.
    project_id: str = ""
    # Columns to open with, in order. A table created for a project usually
    # knows its own headings, and seeding them here means the sheet is never
    # briefly wrong (a "Name"/"Notes" table you then have to rename twice).
    # Left empty, the default pair is seeded instead.
    columns: list[str] = Field(default_factory=list)


class SheetUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    # Sending "" detaches. None means "not sent" and leaves the edge alone,
    # the same contract ProjectUpdate.link_kind uses.
    project_id: Optional[str] = None


class ColumnCreate(BaseModel):
    name: str = "Column"
    type: ColumnType = "text"
    # `select`/`multiselect` choices, or the entity kind a `link` column points at.
    options: list[str] = Field(default_factory=list)
    formula: str = ""
    link_kind: str = ""
    width: int = 160


class ColumnUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[ColumnType] = None
    options: Optional[list[str]] = None
    formula: Optional[str] = None
    link_kind: Optional[str] = None
    width: Optional[int] = None
    # Per-column footer aggregate: sum · avg · min · max · count · filled · empty
    summary: Optional[str] = None


class SheetRowCreate(BaseModel):
    # Keyed by column key. Missing columns are simply empty.
    values: dict[str, Any] = Field(default_factory=dict)
    after: Optional[str] = None      # insert below this row id


class SheetRowUpdate(BaseModel):
    values: dict[str, Any]


class RowsBulk(BaseModel):
    """Paste / import: a block of rows in one write."""
    rows: list[dict[str, Any]]


class SheetViewSave(BaseModel):
    name: str
    filters: list[dict[str, Any]] = Field(default_factory=list)
    sorts: list[dict[str, Any]] = Field(default_factory=list)
    hidden: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Project ideas — the reference list / database / knowledge graph of a project
#
# One relationship, three lenses: (:Project)-[:HAS_IDEA]->(:Idea) carries the
# per-project status ("to look at"), a note, and the node's position on the
# graph canvas. Ideas themselves stay global, so the same idea can sit in two
# projects and the graph can show that it does.
# --------------------------------------------------------------------------- #
IdeaLookStatus = Literal["to-look-at", "looking", "used", "parked"]


class ProjectIdeaAttach(BaseModel):
    """Attach an existing idea by id, or create one from `title` on the spot."""
    idea_id: Optional[str] = None
    title: str = ""
    category: str = "research"
    status: IdeaLookStatus = "to-look-at"
    note: str = ""


class ProjectIdeaUpdate(BaseModel):
    status: Optional[IdeaLookStatus] = None
    note: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    # How big this node's box is on the knowledge map. Per-node and per-project
    # (it lives on the HAS_IDEA edge, next to x/y), so a box you widened to fit
    # a long title is still that width tomorrow. Unset → the canvas default.
    w: Optional[float] = None
    h: Optional[float] = None


class IdeaLinkCreate(BaseModel):
    """A connection the user draws between two ideas on the graph canvas."""
    from_id: str
    to_id: str
    label: str = ""


# --------------------------------------------------------------------------- #
# Recurring payments — subscriptions and one-offs (Vault → Transactions)
#
# A :Recurring is a COMMITMENT, not a transaction: it says "£11.99 leaves on
# the 14th of every month". Marking one paid mints a real :Transaction and
# rolls the due date forward, so the ledger stays the single record of what
# actually moved.
# --------------------------------------------------------------------------- #
Cadence = Literal["once", "weekly", "fortnightly", "4weekly", "monthly", "quarterly", "yearly"]
SubStatus = Literal["active", "trial", "paused", "cancelled"]


class RecurringCreate(BaseModel):
    name: str
    amount: float = 0.0
    cadence: Cadence = "monthly"
    next_due: str = ""                 # YYYY-MM-DD
    category: str = "Subscriptions"
    account_id: Optional[str] = None
    notes: str = ""
    active: bool = True
    # Remind me this many days before it's due. 0 = on the day.
    remind_days_before: int = 2
    # Subscriptions tab (2026-11-10, from subscriptions.html). A subscription is
    # a :Recurring with these extras; none of them change how paying works.
    what: str = ""                     # what it is — "music streaming"
    gets: str = ""                     # what I get — "ad-free, offline, Duo"
    area: str = "other"                # synapse|pulse|vision|vault|fun|other
    area_manual: bool = False          # False = guessed from the name, re-guessable
    status: SubStatus = "active"       # active|trial count as live; sets `active`
    start: str = ""                    # YYYY-MM-DD
    cancel_by: str = ""                # trial end / notice deadline
    worth: str = ""                    # ""|yes|unsure|no
    paid_from: str = ""                # free text (PayPal…) when it isn't an account


class RecurringUpdate(BaseModel):
    name: Optional[str] = None
    amount: Optional[float] = None
    cadence: Optional[Cadence] = None
    next_due: Optional[str] = None
    category: Optional[str] = None
    account_id: Optional[str] = None
    notes: Optional[str] = None
    active: Optional[bool] = None
    remind_days_before: Optional[int] = None
    what: Optional[str] = None
    gets: Optional[str] = None
    area: Optional[str] = None
    area_manual: Optional[bool] = None
    status: Optional[SubStatus] = None
    start: Optional[str] = None
    cancel_by: Optional[str] = None
    worth: Optional[str] = None
    paid_from: Optional[str] = None


class RecurringPay(BaseModel):
    """Confirm a payment happened. Defaults to the due date and the set amount,
    but both can differ — bills change."""
    date: Optional[str] = None
    amount: Optional[float] = None
    note: str = ""


# --------------------------------------------------------------------------- #
# Reminders — messages you leave for yourself, due on a date
# --------------------------------------------------------------------------- #
class ReminderCreate(BaseModel):
    message: str
    due: str                            # YYYY-MM-DD
    # Optional link back to whatever this is about.
    ref_kind: str = ""
    ref_id: Optional[str] = None
    ref_title: str = ""
    repeat: Cadence = "once"


class ReminderUpdate(BaseModel):
    message: Optional[str] = None
    due: Optional[str] = None
    done: Optional[bool] = None
    repeat: Optional[Cadence] = None


# --------------------------------------------------------------------------- #
# Focus — the top-bar quick overview: where I am right now
#
# A single :Focus node holds the current phase (of life, of learning, of the
# plan — deliberately one free-text field, because which of those it means
# changes), and :Goal nodes hang off it. Everything else on the panel is
# derived from data that already exists.
# --------------------------------------------------------------------------- #
GoalHorizon = Literal["now", "quarter", "year", "someday"]
GoalStatus = Literal["active", "done", "parked"]


class FocusUpdate(BaseModel):
    phase: Optional[str] = None          # "building the Mainframe core"
    note: Optional[str] = None           # why this phase, what ends it
    # Which snapshot sections are shown, and in what order — a JSON array of
    # keys, stored as an opaque string. The shape belongs to the frontend (the
    # same call :HomePrefs makes), so adding a way to arrange the panel never
    # needs a migration. It lives in Neo4j rather than localStorage so the
    # panel looks the same in whichever browser you open it in.
    sections: Optional[str] = None


class GoalCreate(BaseModel):
    title: str
    note: str = ""
    horizon: GoalHorizon = "now"


class GoalUpdate(BaseModel):
    title: Optional[str] = None
    note: Optional[str] = None
    horizon: Optional[GoalHorizon] = None
    status: Optional[GoalStatus] = None
    position: Optional[float] = None


# --------------------------------------------------------------------------- #
# Framework — the approach I'm taking, and why
#
# Not a decomposition (that's `Op`), not a template (that's `Architecture`).
# This is reasoning you can re-read later: what I decided to do, why, what I
# ruled out — with a simple box diagram when a picture says it faster.
#
# `boxes` and `arrows` are opaque JSON on the node. A diagram this simple has
# no business being graph structure: it's a drawing, and drawings get replaced
# wholesale rather than edited node by node.
# --------------------------------------------------------------------------- #
FrameworkStatus = Literal["current", "considering", "superseded"]


class FrameworkCreate(BaseModel):
    title: str
    approach: str = ""                  # what I'm doing
    why: str = ""                       # the reasoning
    rejected: str = ""                  # what I chose against, and why
    status: FrameworkStatus = "current"


class FrameworkUpdate(BaseModel):
    title: Optional[str] = None
    approach: Optional[str] = None
    why: Optional[str] = None
    rejected: Optional[str] = None
    status: Optional[FrameworkStatus] = None


class DiagramSave(BaseModel):
    """The whole drawing at once — boxes and the arrows between them."""
    boxes: list[dict[str, Any]] = Field(default_factory=list)
    arrows: list[dict[str, Any]] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Goals view (topbar) — period-scoped aims + phases
# --------------------------------------------------------------------------- #
# A goal belongs to exactly one period of one scope: the day "2026-08-03", the


class PhaseCreate(BaseModel):
    name: str
    start: str                           # ISO date, inclusive
    end: str                             # ISO date, inclusive
    note: str = ""


class PhaseUpdate(BaseModel):
    name: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    note: Optional[str] = None


# --------------------------------------------------------------------------- #
# Phases as sprints — the Phases tab (Mainframe-level)
#
# The same :Phase node the Goals view scopes goals to, grown a lifecycle. One
# phase is active at a time; projects join it (:Project)-[:IN_PHASE]->(:Phase)
# and the phase cannot close until every one of them has an outcome. Hours and
# sessions are never typed: they are summed from the :WorkSession rows sitting
# on those projects inside the phase's window, so the summary row cannot lie.
# --------------------------------------------------------------------------- #
PhaseOutcomeKind = Literal["done", "carried", "dropped"]


class PhaseStart(BaseModel):
    """POST /api/phases — the opening lineup of a new phase."""
    name: str
    start: str                           # ISO date, inclusive
    weeks: int = 14                      # end is derived from start + weeks
    goal: str = ""
    project_ids: list[str] = []


# The goals the phase dashboard's time viewer shows. These carry :PoolGoal on
# top of :Goal: the bare label already has two tenants with different shapes
# (the focus panel and fitness), and goals.py warns in as many words that a
# third would make every MATCH a guessing game. The extra label is what lets
# those two keep their own goals to themselves.
PoolGoalHorizon = Literal["day", "week", "month"]
# on -> flagged is drift.py's doing; renegotiated is what "talk this through"
# leaves behind; done is yours.
PoolGoalStatus = Literal["on", "flagged", "renegotiated", "done"]
# How a goal's progress bar fills. count: scope_done of scope_total, bumped by
# hand. hours: sessions logged on its project inside the goal's window (this
# week / this month) against target_h, never typed. tasks: tasks that SERVE it.
PoolGoalMeasure = Literal["count", "hours", "tasks"]
# The three levers behind a flag. Each one writes a :Change and clears the flag.
RenegotiateLever = Literal["move_due", "cut_scope", "add_hours"]


# One note shape for the whole Mainframe. See routes/notes.py for why edges get
# a (:Hop) node rather than relationship properties, and why there is no PATCH.
NoteKind = Literal["note", "why"]


class LessonCreate(BaseModel):
    """POST /api/lessons — what went wrong and what you would do instead.

    `repeated` is absent on purpose: it is set by naming the earlier lesson
    this one is the same as, never typed. See routes/lessons.py.
    """
    wrong: str
    instead: str = ""
    date: str = ""                       # ISO date; defaults to today
    group: str = ""
    about_id: str = ""                   # the thing it happened to, if any
    same_as: str = ""                    # an earlier lesson this repeats
    detail: str = ""                     # this occurrence, when it is an instance
    pattern: str = ""                    # distraction pattern (session tally)
    source: str = ""                     # 'distraction' for session-logged rows


class LessonUpdate(BaseModel):
    wrong: Optional[str] = None
    instead: Optional[str] = None
    date: Optional[str] = None
    group: Optional[str] = None
    about_id: Optional[str] = None
    same_as: Optional[str] = None
    detail: Optional[str] = None
    status: Optional[Literal["", "trying", "solved"]] = None


class LessonInstanceCreate(BaseModel):
    """POST /api/lessons/{id}/instances — it happened again. Either a fresh
    occurrence (`detail`) or an existing distraction row (`from_id`)."""
    detail: str = ""
    date: str = ""
    from_id: str = ""


class LessonPromote(BaseModel):
    """POST /api/lessons/promote — turn a distraction pattern into a lesson."""
    pattern: str
    wrong: str = ""
    group: str = ""


class LessonMerge(BaseModel):
    into: str


class LessonGroupUpsert(BaseModel):
    """A user-defined grouping of mistakes, and the colour it reads as. There is
    no fixed taxonomy: the useful groupings are the ones you notice yourself
    making, and they change."""
    name: str
    color: str = "#7FA8C8"
    note: Optional[str] = None           # what belongs in it, e.g. "estimates, order"


class NoteCreate(BaseModel):
    """POST /api/notes — a note about a node, or about an edge between two.

    Give either `target_id` (a node) or all three of `from_id` / `rel` / `to_id`
    (an edge). `supersedes` is how editing works: the old note is kept and this
    one chains to it, because a reason you have since revised is still a reason
    you once had.
    """
    text: str
    kind: NoteKind = "note"
    target_id: str = ""
    from_id: str = ""
    rel: str = ""
    to_id: str = ""
    date: str = ""                       # ISO date; defaults to today
    supersedes: str = ""


class PoolGoalCreate(BaseModel):
    """POST /api/phases/goals — one claim about the week or the month.

    Everything past `text` and `horizon` is optional, but the planning fields
    are what the drift rules read: a goal with no due date, no project and no
    planned hours can never be flagged, because nothing about it can be checked.
    """
    text: str
    horizon: PoolGoalHorizon = "week"
    due: str = ""                        # ISO date
    project_id: str = ""                 # the work runs through this project
    plan_h_day: float = 0.0              # hours a day it was planned at
    plan_h_week: float = 0.0             # hours in the week it was planned at
    estimate_h: float = 0.0                   # estimated hours to finish it
    scope_total: float = 0.0             # "5 sections"
    scope_done: float = 0.0              # "3 of" them
    note: str = ""
    measure: PoolGoalMeasure = "count"   # how the progress bar fills
    target_h: float = 0.0                # hours target when measure == "hours"


class PoolGoalUpdate(BaseModel):
    text: Optional[str] = None
    horizon: Optional[PoolGoalHorizon] = None
    due: Optional[str] = None
    project_id: Optional[str] = None
    plan_h_day: Optional[float] = None
    plan_h_week: Optional[float] = None
    estimate_h: Optional[float] = None
    scope_total: Optional[float] = None
    scope_done: Optional[float] = None
    note: Optional[str] = None
    status: Optional[PoolGoalStatus] = None
    measure: Optional[PoolGoalMeasure] = None
    target_h: Optional[float] = None


class ServesGoal(BaseModel):
    """POST /api/phases/goals/{id}/serves — the chip on a task, or a block booked
    for a goal.

    One endpoint for both because they are the same statement about different
    things: this piece of the week exists in order to move that goal along. A
    task says so on the day list; a calendar block says so to drift rule 1,
    which is how "the thursday block was lost to the team dinner" is knowable
    at all.
    """
    kind: Literal["task", "event"]
    id: str


class PullIn(BaseModel):
    """POST /api/phases/{id}/pull — claim something into the running phase.

    Claiming is not creating. The project, task or habit already exists in its
    own pool and outlives the phase; this says the phase is taking it on, and
    for how many hours. `why` is optional and is written as a note against the
    claim edge, so the reason belongs to this claim rather than to the thing
    itself: a project claimed by two phases was claimed for two different
    reasons.

    Claiming a project claims every project under it — see routes/phases.py.
    """
    kind: Literal["project", "task", "habit"]
    id: str
    hours: float = 0.0
    why: str = ""


class Renegotiate(BaseModel):
    """POST /api/phases/goals/{id}/renegotiate — pulling one of the three levers.

    `value` is read against the lever: a date for move_due, the new scope total
    for cut_scope, the new hours-a-day for add_hours. The reason is not optional
    on purpose. The whole value of the change log is that it says why.
    """
    lever: RenegotiateLever
    value: str
    reason: str


class PhaseEdit(BaseModel):
    """PATCH /api/phases/{id} — the pencil on the banner.

    Everything here is optional and only what is sent is written, so setting a
    banner does not silently clear the goal. `weeks` re-derives `end`; `end`
    itself is never posted, because a phase's length is the thing you decide and
    its last day is the consequence.
    """
    name: Optional[str] = None
    start: Optional[str] = None
    weeks: Optional[int] = None
    goal: Optional[str] = None
    banner_url: Optional[str] = None


class PhaseOutcomeIn(BaseModel):
    project_id: str
    outcome: PhaseOutcomeKind
    note: str = ""


class PhaseClose(BaseModel):
    """POST /api/phases/{id}/close — refused while any project is unanswered."""
    outcomes: list[PhaseOutcomeIn] = []
    reflection: str = ""


class DayNotePut(BaseModel):
    """Snapshot view — the free-text note pinned to one calendar day."""
    date: str
    text: str = ""


# --------------------------------------------------------------------------- #
# Body issues — a flagged problem (soreness, pain…) that lives across days
# --------------------------------------------------------------------------- #
# Flagging a region opens an issue; it stays open — and keeps colouring the
# body map — until it is explicitly closed. Severity (1 mild … 5 severe)
# drives the colour and can be re-scored over time: each re-score or note is
# an update on the issue's own timeline, so "started Monday, eased by evening"
# is two updates on one issue, not two disconnected states.
BodyIssueKind = Literal["soreness", "pain", "tight", "imbalance"]


class BodyIssueCreate(BaseModel):
    region: str
    kind: BodyIssueKind = "soreness"
    severity: int = Field(3, ge=1, le=5)
    note: str = ""


class BodyIssueUpdateCreate(BaseModel):
    severity: Optional[int] = Field(None, ge=1, le=5)   # None → severity unchanged
    note: str = ""


class BodyIssuePatch(BaseModel):
    status: Optional[Literal["open", "closed"]] = None
    kind: Optional[BodyIssueKind] = None


class BodyDayEntrySet(BaseModel):
    """One region on one day's body snapshot."""
    kind: BodyIssueKind = "soreness"
    severity: int = Field(3, ge=1, le=5)
    note: str = ""


class BodyDayAllClear(BaseModel):
    """A day checked and fine. Setting it removes that day's entries."""
    all_clear: bool = True


class BodyDayCarry(BaseModel):
    """Copy another day's entries into this one (regions already set are kept)."""
    from_date: str


class BodyIssuesToDay(BaseModel):
    """Move open issues from the old always-on map into a day, optionally closing them."""
    date: str
    close: bool = True


# --------------------------------------------------------------------------- #
# Diary — one store, two doors: the Mainframe day view and each module's tab
# --------------------------------------------------------------------------- #
class DiaryCreate(BaseModel):
    date: str
    text: str
    title: str = ""
    module: str = "mainframe"    # synapse|pulse|vision|vault|mainframe
    section: str = ""            # optional finer label, e.g. "nutrition"
    tags: list[str] = []
    source: str = "section"      # section|dump — how the entry got here


class DiaryUpdate(BaseModel):
    date: Optional[str] = None
    text: Optional[str] = None
    title: Optional[str] = None
    module: Optional[str] = None
    section: Optional[str] = None
    tags: Optional[list[str]] = None


class DiarySplitRequest(BaseModel):
    """A day dumped in one go. Returns a proposal; saves nothing."""
    text: str
    prompt_override: Optional[str] = None


class DiaryCommit(BaseModel):
    """The proposal after you've corrected it."""
    date: str
    segments: list[DiaryCreate] = []


# --------------------------------------------------------------------------- #
# Inbox and the project tree (routes/inbox.py)
#
# One leaf node type. `kind` flips in place between idea and task, which is why
# the create and update bodies carry the fields of both rather than splitting
# into two shapes that would have to be converted into each other.
# --------------------------------------------------------------------------- #
class InboxCreate(BaseModel):
    title: str
    kind: str = "idea"
    category: Optional[str] = ""


class InboxUpdate(BaseModel):
    kind: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    low_h: Optional[float] = None
    high_h: Optional[float] = None
    due: Optional[str] = None
    # When you mean to do it (not the deadline — that's `due`) and how long you
    # expect it to take. A row with do_on AND do_at shows as a block on the
    # Calendar, computed on read; "" clears.
    do_on: Optional[str] = None          # ISO date
    do_at: Optional[str] = None          # "HH:MM"
    takes_min: Optional[int] = None      # expected minutes
    # The day you actually began it — stamped by the row's "start" button,
    # editable after; "" un-starts it.
    started_on: Optional[str] = None     # ISO date


# Every move carries an optional why, written against the edge it draws rather
# than against the row. See the module docstring in routes/inbox.py.
class MoveGive(BaseModel):
    project_id: str
    why: Optional[str] = ""


class MovePromote(BaseModel):
    parent_id: Optional[str] = None
    why: Optional[str] = ""


class MoveGrow(BaseModel):
    parent_id: Optional[str] = None
    why: Optional[str] = ""


class MoveStar(BaseModel):
    """Flag a row as one that matters. Not a status and not a priority — see
    the module docstring in routes/inbox.py."""
    starred: bool = True
    # which star: "priority" (yellow) or "soon" (teal — do it sooner rather
    # than later). Omitted on a star means priority.
    tone: Optional[str] = None


class MoveDrop(BaseModel):
    why: Optional[str] = ""


# Cache2 — the shelf. Same shape as a drop because it is the same gesture with
# the opposite meaning: one line saying why, and the row waits instead of
# ending. Uncache takes the same body, so "why I brought this back" is askable
# in the place you would expect to be asked it.
class MoveCache(BaseModel):
    why: Optional[str] = ""


class ProjectNest(BaseModel):
    name: str
    parent_id: Optional[str] = None
    why: Optional[str] = ""


class ProjectSplit(BaseModel):
    title: str
    why: Optional[str] = ""


class ProjectOffshoot(BaseModel):
    title: str
    why: Optional[str] = ""


class TreeProjectUpdate(BaseModel):
    name: Optional[str] = None
    done_when: Optional[str] = None
    low_h: Optional[float] = None
    high_h: Optional[float] = None
    due: Optional[str] = None
    est_override: Optional[bool] = None
    priority: Optional[int] = None          # 1 now | 2 soon | 3 later
    priority_order: Optional[float] = None  # the drag rank on the list
    status: Optional[str] = None            # active|paused|not started|holding|done
    kind: Optional[WorkType] = None         # study|build|admin|body, see WorkType
    color: Optional[str] = None             # the card's border, see PROJECT_COLORS
    done_at: Optional[str] = None
    why: Optional[str] = ""                 # an override prompts for one


class ProjectReorder(BaseModel):
    """POST /api/synapse/projects/reorder — the whole list, in its new order."""
    ids: list[str] = []


class ProjectMove(BaseModel):
    """Re-parent a project. A null parent puts it back at the top level."""
    parent_id: Optional[str] = None
    why: Optional[str] = ""


class ProjectDone(BaseModel):
    """Tick a project. `cascade` marks everything under it done as well, and is
    asked for rather than assumed."""
    done: bool = True
    cascade: bool = False
    why: Optional[str] = ""


class WhyIn(BaseModel):
    """One entry in a project's why-and-notes list. Same :Note node either way;
    `kind` is the whole difference between a reason and a remark."""
    text: str
    kind: Optional[str] = "why"


class TreeTaskCreate(BaseModel):
    project_id: str
    title: str
    why: Optional[str] = ""


class TreeTaskUpdate(BaseModel):
    title: Optional[str] = None
    low_h: Optional[float] = None
    high_h: Optional[float] = None
    due: Optional[str] = None
    done: Optional[bool] = None
    parent_id: Optional[str] = None         # dragged onto another project
    why: Optional[str] = ""


class QuestionCreate(BaseModel):
    """One row of a question list box. `parent_id` is whatever it was asked of
    — a reading instance, a paper, a task — and may be omitted for a question
    that is not about anything in particular yet.

    `row_id` is the Inbox row this question ALREADY is. Asking a question
    normally writes one: the question is the record, the row is the decision
    about it. Marking an idea you have already written as a question is the
    same act from the other end, and it must reuse that row rather than write
    a second one saying the same sentence."""
    text: str
    kind: str = "question"           # the label of the box it was typed into
    parent_id: Optional[str] = None
    row_id: Optional[str] = None     # an existing Inbox row, not a new one


class QuestionUpdate(BaseModel):
    text: Optional[str] = None
    answer: Optional[str] = None
    answered: Optional[bool] = None
    # the Inbox's stars: priority (yellow) | soon (teal, "possible priority")
    # | later (grey, "could be important in a later phase")
    starred: Optional[bool] = None
    star_tone: Optional[str] = None


class RowCreate(BaseModel):
    """One + row: a note, a thing to look into, a follow-up. Same shape as a
    question so the one ListBox serves both. `inbox` False is for rows moved
    across from an old textarea, which should not all land in the Inbox.

    2026-11-08: a row no longer files an Inbox row unless `inbox` is True
    explicitly — notes stay in their own area. `area` is the module the box
    sits in (Synapse | Pulse | Vault | Vision, '' on a shared tab); the server
    derives it from the parent's label when the page does not say."""
    text: str
    kind: str = "note"               # the box it was typed into
    parent_id: Optional[str] = None
    inbox: Optional[bool] = None
    area: Optional[str] = None
    intent: Optional[str] = None     # log | idea | task — default log


class RowUpdate(BaseModel):
    text: Optional[str] = None
    done: Optional[bool] = None      # a to-do row (e.g. "look into") ticked off


class AssumptionCreate(BaseModel):
    """One row of an assumptions list box. Same shape as a question, so the one
    ListBox component serves both; `parent_id` is what it was assumed about."""
    text: str
    kind: str = "assumption"
    parent_id: Optional[str] = None


class AssumptionUpdate(BaseModel):
    text: Optional[str] = None
    status: Optional[str] = None     # open | held | broke
    note: Optional[str] = None


class LessonEntryCreate(BaseModel):
    """One row of a suggestion or note list box on a lesson. `kind` is the label
    of the box it was typed into, so one shape serves both."""
    text: str
    kind: str = "note"
    parent_id: str = ""


class LessonEntryUpdate(BaseModel):
    text: Optional[str] = None
    # Solutions only: how trying it went. '' = not tried yet.
    status: Optional[Literal["", "worked", "mixed", "failed"]] = None
    outcome: Optional[str] = None


# Project attachments (notes/ui/mainframe_project_attach.html). Attaching writes
# an edge and moves nothing: (:X)-[:PART_OF {date}]->(:Project), and optionally
# (:X)-[:SOURCE_OF {date}]->(:Document) for a doc that is part of the project.
AttachKind = Literal["project", "paper", "doc", "sheet", "video", "writing"]


class ProjectAttach(BaseModel):
    kind: AttachKind
    id: str
    part_of: bool = True
    source_of: Optional[str] = None      # a :Document id in this project
    why: str = ""                        # becomes a dated why Note on the edge
