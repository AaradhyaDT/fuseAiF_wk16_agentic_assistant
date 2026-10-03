---
name: citation-policy
description: Strict guidelines on citation grounding, doc_id formatting, and avoiding hallucinated references.
---

# Citation Policy Skill

To maintain verifiable provenance and pass the deterministic verification gate:

1. **Provable Provenance**:
   - Every cited item must correspond to a document returned by a successful `search_knowledge_base` or `read_document` call during the active execution trajectory.
   - External URLs or documents not residing in the retrieved set must NOT be passed to the `citations` list in `final_answer`.

2. **Format**:
   - In `final_answer.citations`, provide base filenames: e.g. `["release_notes.md", "rag_basics.md"]`.
   - In the text body, reference documents using markdown bracket notation: `[doc:release_notes.md]`.
