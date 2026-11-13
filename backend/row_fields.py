"""The textareas that became + rows, and the one-off move of what was in them.

Each entry is (node label, old property, row kind[, extra WHERE on n]). At startup every
entry runs once (a :Marker records it): the old string is split on newlines,
leading bullets are stripped, and each non-blank line becomes a (:Row)-[:ON]->
the node it was written on, in the order it was written.

THE OLD PROPERTY IS LEFT WHERE IT IS. Nothing reads it any more, but deleting
what someone typed on the strength of a migration is a bet with their notes;
leaving it costs a few bytes and makes the move undoable.

NO INBOX ROWS for moved text — see routes/rows.py. The Inbox is for what you
capture from now on, not a backlog of every note ever written.

Adding a field: convert its form to a ListBox (kind = the third value here)
and add the line below. The marker name includes all three values, so a new
entry runs on the next start without re-running the old ones.
"""
from __future__ import annotations

ROW_FIELDS: list[tuple[str, ...]] = [
    ("Cycle", "goals", "goal"),
    ("Cycle", "notes", "note"),
    ("Project", "note", "note"),
    ("Investment", "notes", "note"),
    ("ActivityLog", "notes", "note"),
    ("StretchSession", "notes", "note"),
    ("StretchSession", "stretches", "step"),
    ("Workout", "notes", "note"),
    # An imported .ics event keeps its description as text: the next import
    # rewrites it, and it never shows a + box.
    ("CalEvent", "notes", "note", "coalesce(n.source, '') <> 'ics'"),
    ("ResearchNote", "summary", "note"),
    ("StoryPanel", "notes", "note"),
    ("Contact", "notes", "note"),
    ("WritingPiece", "notes", "note"),
    ("PipelineStage", "process", "step"),
    ("PipelineStage", "inputs", "input"),
    ("PipelineStage", "outputs", "output"),
    ("PipelineStage", "tools", "tool"),
    ("Assessment", "notes", "note"),
    ("Baseline", "goals", "goal"),
    ("Baseline", "notes", "note"),
    ("MedicalEntry", "details", "note"),
    ("MedicalEntry", "notes", "follow-up"),
    # Medications had two generic boxes; they become the one notes box.
    ("MedEntry", "details", "note"),
    ("MedEntry", "notes", "note"),
    ("RecoverySession", "notes", "note"),
    ("Intolerance", "notes", "note"),
    ("Supplement", "notes", "note"),
    ("Recipe", "instructions", "step"),
    ("Instance", "look_into", "look into"),
    ("Instance", "understood", "understood"),
    ("Instance", "notes", "note"),
    ("ProjectPass", "look_into", "look into"),
    ("DeepDive", "info", "note"),
]

_MOVE = """
OPTIONAL MATCH (m:Marker {name: $mk})
WITH m WHERE m IS NULL
CALL () {
  MATCH (n:%(label)s)
  WHERE n.%(prop)s IS NOT NULL AND (%(where)s)
  // A list property (stretches) is already one item per element; a string
  // is split on its lines.
  WITH n, CASE WHEN valueType(n.%(prop)s) STARTS WITH 'LIST'
               THEN [x IN n.%(prop)s | toString(x)]
               ELSE split(replace(toString(n.%(prop)s), '\\r', ''), '\\n') END AS raw
  WITH n, [l IN raw WHERE trim(l) <> '' | trim(l)] AS lines
  WHERE size(lines) > 0
  UNWIND range(0, size(lines) - 1) AS i
  WITH n, i, lines[i] AS line
  WITH n, i, CASE WHEN line =~ '^([-*•·]|\\d+[.)])\\s+.*'
                  THEN trim(substring(line, size(split(line, ' ')[0]) + 1))
                  ELSE line END AS text
  WHERE text <> ''
  CREATE (r:Row {id: randomUUID(), text: text, kind: $kind,
                 created_at: coalesce(toString(n.created_at), '2000-01-01')
                             + '#' + right('000' + toString(i), 3)})
  CREATE (r)-[:ON]->(n)
  RETURN count(*) AS moved
}
MERGE (:Marker {name: $mk})
RETURN moved
"""


async def migrate(session) -> None:
    # Rows whose node was deleted (a DETACH DELETE elsewhere takes the ON edge
    # with it). A row only ever exists to be read off its node, so one with no
    # node is unreachable; its Inbox row, if any, stays.
    await session.run("MATCH (r:Row) WHERE NOT (r)-[:ON]->() DETACH DELETE r")
    for label, prop, kind, *where in ROW_FIELDS:
        mk = f"rows:{label}.{prop}->{kind}"
        await session.run(_MOVE % {"label": label, "prop": prop,
                                   "where": where[0] if where else "true"},
                          mk=mk, kind=kind)
