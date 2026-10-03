from app.agent.trace import Step, Trajectory
from app.agent.verifier import normalise_citations, verify_final


def test_normalise_citations():
    assert normalise_citations(
        ["[doc:release_notes.md]", "doc:rag_basics.md", "release_notes.md"]
    ) == [
        "release_notes.md",
        "rag_basics.md",
    ]


def test_verify_final_flags_unretrieved_citations():
    traj = Trajectory(query="test")
    traj.add(
        Step(
            step=1,
            iteration=1,
            tool="search_knowledge_base",
            args={},
            result="...",
            sources=["rag_basics.md"],
            kind="evidence",
            ok=True,
        )
    )

    # Cited a source that was never retrieved
    args = {
        "answer": "Chunking is splitting documents.",
        "citations": ["rag_basics.md", "unseen_doc.md"],
        "confidence": "high",
        "evidence_sufficient": True,
    }
    problems = verify_final(args, traj)
    assert len(problems) == 1
    assert "unseen_doc.md" in problems[0]


def test_verify_final_passes_valid_citations():
    traj = Trajectory(query="test")
    traj.add(
        Step(
            step=1,
            iteration=1,
            tool="search_knowledge_base",
            args={},
            result="...",
            sources=["rag_basics.md"],
            kind="evidence",
            ok=True,
        )
    )
    args = {
        "answer": "Chunking is splitting documents.",
        "citations": ["rag_basics.md"],
        "confidence": "high",
        "evidence_sufficient": True,
    }
    problems = verify_final(args, traj)
    assert len(problems) == 0


def test_verify_final_flags_missing_citations_when_sufficient():
    traj = Trajectory(query="test")
    traj.add(
        Step(
            step=1,
            iteration=1,
            tool="search_knowledge_base",
            args={},
            result="...",
            sources=["rag_basics.md"],
            kind="evidence",
            ok=True,
        )
    )
    args = {
        "answer": "Chunking is splitting documents.",
        "citations": [],
        "confidence": "high",
        "evidence_sufficient": True,
    }
    problems = verify_final(args, traj)
    assert any("no citations were given" in p for p in problems)


def test_verify_final_flags_evidence_sufficient_on_failed_tools():
    traj = Trajectory(query="test")
    traj.add(
        Step(
            step=1,
            iteration=1,
            tool="search_knowledge_base",
            args={},
            result="error: tool unavailable",
            sources=[],
            kind="evidence",
            ok=False,
            error="tool_unavailable",
        )
    )
    args = {
        "answer": "Some confident answer despite failure.",
        "citations": ["rag_basics.md"],
        "confidence": "high",
        "evidence_sufficient": True,
    }
    problems = verify_final(args, traj)
    assert any("every evidence tool call failed" in p for p in problems)
