// Reference-ingestion schema — loaded by db.py on startup (split on ';').
// Everything here is IF NOT EXISTS, so it is safe to run on every boot.
//
// NOTE ON LABELS: form/warrant are PROPERTIES on :Reference, never labels —
// reclassifying a source must be a SET, not a relabel (spec DO-NOT).
//
// The canonical bibliography node. One node per cited WORK; a work cited by
// five documents has five incoming :CITES edges, not five nodes.
CREATE CONSTRAINT reference_uid IF NOT EXISTS FOR (r:Reference) REQUIRE r.uid IS UNIQUE;
CREATE INDEX reference_doi IF NOT EXISTS FOR (r:Reference) ON (r.doi);
CREATE INDEX reference_title_norm IF NOT EXISTS FOR (r:Reference) ON (r.title_norm);
// :Author and :Venue already carry name-uniqueness constraints (db.py) — the
// pipeline MERGEs on name to reuse those nodes, and stamps a uid on create.
CREATE CONSTRAINT author_uid IF NOT EXISTS FOR (a:Author) REQUIRE a.uid IS UNIQUE;
CREATE CONSTRAINT venue_uid IF NOT EXISTS FOR (v:Venue) REQUIRE v.uid IS UNIQUE;
// Review queue — a parse/resolve below the confidence threshold lands here,
// NOT in the graph. POST /confirm is what turns an item into a :Reference.
CREATE CONSTRAINT refreview_uid IF NOT EXISTS FOR (q:RefReviewItem) REQUIRE q.uid IS UNIQUE;
CREATE INDEX refreview_status IF NOT EXISTS FOR (q:RefReviewItem) ON (q.status)
