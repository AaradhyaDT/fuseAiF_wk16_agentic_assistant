
from app.agent.context import (
    NotesStore,
    SkillRegistry,
    ToolRound,
    cap_retrieval,
    render_transcript,
)


def test_notes_store():
    store = NotesStore(max_chars=200)
    msg1 = store.add("Fact A", "doc1.md", step=1)
    assert "noted" in msg1
    # Duplicate fact should not be duplicated
    msg2 = store.add("Fact A", "doc1.md", step=2)
    assert "already recorded" in msg2
    assert len(store) == 1
    rendered = store.render()
    assert "- Fact A [doc:doc1.md]" in rendered


def test_render_transcript_clearing():
    r1 = ToolRound(
        assistant={"role": "assistant", "content": "searching round 1"},
        tool_messages=[{"role": "tool", "content": "VERY LONG RAW RETRIEVAL CONTENT" * 10}],
        stubs=["[cleared] search() -> 1 hit"],
    )
    r2 = ToolRound(
        assistant={"role": "assistant", "content": "searching round 2"},
        tool_messages=[{"role": "tool", "content": "LATEST TOOL OUTPUT"}],
        stubs=["[cleared] latest"],
    )

    # With clearing enabled and keep_last=1: r1 should be replaced with stub, r2 preserved
    msgs_cleared, count = render_transcript([r1, r2], enable_clearing=True, keep_last=1)
    assert count == 1
    assert any("[cleared] search() -> 1 hit" == m.get("content") for m in msgs_cleared)
    assert any("LATEST TOOL OUTPUT" == m.get("content") for m in msgs_cleared)

    # With clearing disabled: both raw contents preserved
    msgs_raw, count_raw = render_transcript([r1, r2], enable_clearing=False, keep_last=1)
    assert count_raw == 0
    assert any("VERY LONG RAW RETRIEVAL CONTENT" in m.get("content", "") for m in msgs_raw)


def test_skill_registry(tmp_path):
    skills_dir = tmp_path / "skills"
    skill_a = skills_dir / "conflict-resolution"
    skill_a.mkdir(parents=True)
    content = (
        "---\n"
        "name: conflict-resolution\n"
        "description: Handle conflicting sources.\n"
        "---\n"
        "Full instructions here."
    )
    (skill_a / "SKILL.md").write_text(content)

    reg = SkillRegistry(skills_dir)
    assert "conflict-resolution: Handle conflicting sources." in reg.index()
    assert reg.load("conflict-resolution") == "Full instructions here."
    assert reg.load("non_existent") is None


def test_cap_retrieval():
    hits = [
        {"source": "doc1.md", "distance": 0.1, "text": "Short hit"},
        {"source": "doc2.md", "distance": 0.9, "text": "Low relevance hit"},
        {"source": "doc3.md", "distance": 0.2, "text": "A" * 1000},
    ]
    capped = cap_retrieval(hits, k=2, min_relevance=0.25, max_chars=50)
    assert len(capped) == 2
    assert capped[0]["source"] == "doc1.md"
    assert capped[1]["source"] == "doc3.md"
    assert len(capped[1]["text"]) <= 60
