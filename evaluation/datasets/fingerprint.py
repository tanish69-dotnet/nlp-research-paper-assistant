"""Evidence fingerprint — stable SHA over the structural evidence only.

Timestamp, ``score`` and ``warnings`` are excluded so two evidence bundles that
differ only in retriever timing/scores still count as equivalent for the
"evidence frozen" control (EVALUATION.md §7, point 1, §11 evidence_fingerprint).
"""

from __future__ import annotations

import hashlib
import json

from app.schemas.evidence import EvidenceBundle


def evidence_fingerprint(bundle: EvidenceBundle) -> str:
    """Hex SHA-256 over a canonical projection of the structural evidence.

    Covers: per-item ``evidence_id/paper_id/type/content/caption/reference/
    page/section/table_data/image`` (sorted by ``evidence_id``) and the
    ``papers`` list (sorted by ``paper_id``). ``score/truncated/metadata/
    warnings/retrieval`` are excluded by design (see docstring).
    """
    items = sorted(bundle.evidence, key=lambda item: item.evidence_id)
    papers = sorted(bundle.papers, key=lambda paper: paper.paper_id)

    projection = {
        "papers": [
            {
                "paper_id": paper.paper_id,
                "title": paper.title,
            }
            for paper in papers
        ],
        "evidence": [
            {
                "evidence_id": item.evidence_id,
                "paper_id": item.paper_id,
                "type": item.type,
                "content": item.content,
                "caption": item.caption,
                "reference": item.reference,
                "page": item.page,
                "section": item.section,
                "table_data": item.table_data.model_dump(mode="json") if item.table_data else None,
                "image": (item.image.model_dump(mode="json") if item.image else None),
            }
            for item in items
        ],
    }
    blob = json.dumps(projection, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
