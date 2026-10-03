import os

import httpx
import streamlit as st

st.set_page_config(page_title="WK16 Agentic Assistant", page_icon="🤖", layout="wide")

DEFAULT_BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8000")

with st.sidebar:
    st.header("Mode & Settings")
    backend = st.text_input("Backend URL", value=st.session_state.get("backend", DEFAULT_BACKEND))
    st.session_state.backend = backend
    mode = st.radio("Pipeline Mode", ["W16 Agentic (Verified Answering)", "W15 Classic (Single-pass RAG)"])
    enable_clearing = st.toggle("Enable Tool Result Clearing", value=True, help="Context engineering: stubs out stale tool calls")
    st.divider()

    st.subheader("Classic Pipeline Toggles")
    use_rag = st.toggle("Use RAG (W15)", value=True)
    use_tools = st.toggle("Allow tool calling (W15)", value=True)
    st.divider()

    if st.button("Re-ingest documents"):
        try:
            with st.spinner("Indexing..."):
                stats = httpx.post(f"{backend}/ingest", timeout=300).json()
            st.success(f"Indexed {stats['files']} files into {stats['chunks']} chunks.")
        except Exception as exc:
            st.error(f"Ingest failed: {exc}")

st.title("WK16 Verified AI Assistant")
st.caption("Agentic ReAct loop · Deterministic Verifier · Context Clearing & Notes · Fallback Chain")

if "messages" not in st.session_state:
    st.session_state.messages = []

for entry in st.session_state.messages:
    with st.chat_message(entry["role"]):
        st.markdown(entry["content"])
    meta = entry.get("meta")
    if meta:
        if meta.get("mode") == "agent":
            with st.expander(f"Agent Trajectory ({meta.get('iterations', 1)} iterations, {meta.get('latency_ms', 0)}ms)"):
                st.write(f"**Status:** `{meta.get('status')}` | **Termination Reason:** `{meta.get('termination_reason')}` | **Provider:** `{meta.get('provider_used')}`")
                if meta.get("citations"):
                    st.write(f"**Verified Citations:** {', '.join(f'`{c}`' for c in meta['citations'])}")
                if meta.get("verification_failures"):
                    st.warning(f"Verification Retries: {len(meta['verification_failures'])} issues flagged during loop")

                usage = meta.get("usage", {})
                st.caption(
                    f"Tokens: prompt={usage.get('prompt_tokens', 0)} · completion={usage.get('completion_tokens', 0)} · "
                    f"reasoning={usage.get('reasoning_tokens', 0)} · total={usage.get('total_tokens', 0)} (LLM calls: {usage.get('llm_calls', 0)})"
                )

                traj = meta.get("trajectory", {})
                steps = traj.get("steps", [])
                if steps:
                    st.write("### Execution Steps")
                    for s in steps:
                        with st.container():
                            st.markdown(f"**Step {s['step']} [Iter {s['iteration']}]: `{s['tool']}`** (kind: `{s.get('kind', 'tool')}`, ok: `{s.get('ok')}`)")
                            if s.get("reasoning"):
                                st.caption(f"*Rationale:* {s['reasoning']}")
                            st.code(s.get("result", "")[:400], language="json" if s.get("result", "").startswith("{") else "text")

                notes = meta.get("notes", [])
                if notes:
                    st.write("### Scratchpad Notes")
                    for n in notes:
                        st.markdown(f"- {n['fact']} `[doc:{n['source']}]`")
        else:
            details = st.expander("Details")
            details.caption(
                f"provider=`{meta.get('provider_used')}` · latency={meta.get('latency_ms')}ms · "
                f"cached={meta.get('cached')} · degraded={meta.get('degraded')}"
            )
            if meta.get("sources"):
                details.write("**Sources**")
                for src in meta["sources"]:
                    details.write(f"- `{src['source']}` (score={src.get('score')})")
            if meta.get("tools_called"):
                details.write(f"**Tools called:** {', '.join(meta['tools_called'])}")

prompt = st.chat_input("Ask a question...")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Executing agentic loop..." if "Agentic" in mode else "Thinking..."):
            try:
                if "Agentic" in mode:
                    history = [
                        {"role": m["role"], "content": m["content"]}
                        for m in st.session_state.messages[:-1]
                        if m["role"] in {"user", "assistant"}
                    ]
                    response = httpx.post(
                        f"{backend}/agent",
                        json={
                            "message": prompt,
                            "history": history,
                            "enable_clearing": enable_clearing,
                        },
                        timeout=180,
                    )
                    response.raise_for_status()
                    data = response.json()
                    data["mode"] = "agent"
                else:
                    response = httpx.post(
                        f"{backend}/chat",
                        json={"message": prompt, "use_rag": use_rag, "use_tools": use_tools},
                        timeout=180,
                    )
                    response.raise_for_status()
                    data = response.json()
                    data["mode"] = "classic"
            except Exception as exc:
                data = {
                    "answer": f"⚠️ Backend error: {exc}",
                    "provider_used": "none",
                    "status": "failed",
                    "termination_reason": "error",
                    "latency_ms": 0,
                    "mode": "agent" if "Agentic" in mode else "classic",
                }
        st.markdown(data["answer"])
    st.session_state.messages.append({"role": "assistant", "content": data["answer"], "meta": data})

