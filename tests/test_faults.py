from app.agent.context import NotesStore, SkillRegistry
from app.agent.faults import FaultInjector
from app.agent.tools import AgentToolbox


def test_fault_injector_tool_unavailable(tmp_path):
    notes = NotesStore()
    skills = SkillRegistry(tmp_path)
    toolbox = AgentToolbox(
        retriever=None,
        docs_dir=tmp_path,
        notes=notes,
        skills=skills,
    )
    injector = FaultInjector(toolbox, mode="tool_unavailable")
    outcome = injector.run("search_knowledge_base", {"query": "test"})
    assert outcome.ok is False
    assert outcome.error == "tool_unavailable"
    assert "connection refused" in outcome.result


def test_fault_injector_malformed_retrieval(tmp_path):
    notes = NotesStore()
    skills = SkillRegistry(tmp_path)
    toolbox = AgentToolbox(
        retriever=None,
        docs_dir=tmp_path,
        notes=notes,
        skills=skills,
    )
    injector = FaultInjector(toolbox, mode="malformed_retrieval")
    outcome = injector.run("search_knowledge_base", {"query": "test"})
    assert outcome.ok is True  # Payload is corrupted while reporting success
    assert "vect0r_dim_mismatch" in outcome.result
    assert outcome.sources == []
