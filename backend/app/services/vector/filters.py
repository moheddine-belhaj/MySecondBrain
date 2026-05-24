"""FilterBuilder — translates SearchFilter into Qdrant filter syntax.

Kept in its own module so that qdrant_client imports are isolated here.
The rest of the vector service layer (models, repository) stays provider-neutral.

Qdrant filter model recap
--------------------------
Filter(must=[...])           — all conditions must match (AND)
FieldCondition(key, match)   — a single field predicate
MatchValue(value=x)          — exact scalar match
MatchAny(any=[...])          — field value is in the given list (useful for tags)

Example generated filter for SearchFilter(tags=["ai"], note_id="abc"):
    Filter(must=[
        FieldCondition(key="tags",    match=MatchAny(any=["ai"])),
        FieldCondition(key="note_id", match=MatchValue(value="abc")),
    ])
"""

from qdrant_client.http import models as qmodels

from app.services.vector.models import SearchFilter


class FilterBuilder:
    """Convert a SearchFilter into a qdrant_client Filter (or None).

    Returns None when the SearchFilter has no active conditions — callers
    should treat None as "no filter" rather than passing it to Qdrant as-is
    (passing an empty Filter() can behave differently across versions).
    """

    @staticmethod
    def build(f: SearchFilter | None) -> qmodels.Filter | None:
        if f is None:
            return None

        conditions: list[qmodels.FieldCondition] = []

        if f.tags:
            conditions.append(
                qmodels.FieldCondition(
                    key="tags",
                    match=qmodels.MatchAny(any=f.tags),
                )
            )

        if f.note_id:
            conditions.append(
                qmodels.FieldCondition(
                    key="note_id",
                    match=qmodels.MatchValue(value=f.note_id),
                )
            )

        if f.note_path:
            conditions.append(
                qmodels.FieldCondition(
                    key="note_path",
                    match=qmodels.MatchValue(value=f.note_path),
                )
            )

        if f.note_title:
            conditions.append(
                qmodels.FieldCondition(
                    key="note_title",
                    match=qmodels.MatchValue(value=f.note_title),
                )
            )

        if not conditions:
            return None

        return qmodels.Filter(must=conditions)
