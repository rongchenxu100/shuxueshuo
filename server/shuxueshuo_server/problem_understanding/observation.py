"""Read-only projection of observation evidence for extraction requests."""


def observation_view(observation):
    """Derived OCR hints only. No source record is mutated or promoted to printed."""
    pages = []
    manifest = []
    for page_no, page in enumerate(observation.get("pages", []), 1):
        pid = page["page_id"]
        lines = []
        notes = []
        formulas = []
        spans = sorted(
            (s for s in observation.get("text_spans", []) if s["page_id"] == pid),
            key=lambda s: s.get("reading_order", 0),
        )
        for span in spans:
            text = span.get("text", "")
            if not text:
                continue
            origin = span.get("origin", "unknown")
            # Preserve all lines and line breaks, including orphan denominator lines.
            lines.append(
                {
                    "text": text,
                    **(
                        {"note": "可能为手写或混合批注，需看图核查"}
                        if origin in ("handwritten", "mixed")
                        else {}
                    ),
                }
            )
        seen = set()
        for row in observation.get("formulas", []):
            if row["page_id"] != pid or not row.get("latex"):
                continue
            text = row["latex"]
            # Exact duplicate only within the same source location. Different candidates survive.
            key = (text, tuple(row.get("source_observation_ids", [])))
            if key in seen:
                continue
            seen.add(key)
            formulas.append({"text": text, "note": "公式候选，以原图为准"})
        for group, title in [
            ("ink_origins", "存在笔迹/来源混合区域"),
            ("occlusions", "存在遮挡区域"),
        ]:
            if any(x.get("page_id") == pid for x in observation.get(group, [])):
                notes.append(title)
        by_source = {}
        for f in observation.get("formulas", []):
            if f["page_id"] == pid:
                key = tuple(f.get("source_observation_ids", []))
                if key:
                    by_source.setdefault(key, set()).add(f.get("latex", ""))
        if any(len(v) > 1 for v in by_source.values()):
            notes.append("同一位置有不同公式候选，请独立看图判断。")
        pages.append(
            {
                "page": page_no,
                "lines": lines,
                "formula_candidates": formulas,
                "notes": notes,
            }
        )
        manifest.append({"page": page_no, "source_page_id": pid})
    return {"pages": pages}, manifest
