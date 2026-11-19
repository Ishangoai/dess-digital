# How DESS Minutes learns from reviewers

**The main idea.** The system learns the way a new company secretary learns a board's house style. It drafts, the professional corrects the draft in Word, and the system works out **why** each correction was made before anything is learned from it. Most corrections show that the draft failed to apply the DESS Standard, not that the Standard should change. Only real preferences of the organisation go forward as proposed profile changes, and a person confirms each one. The AI model itself is never retrained.

**One-line version:** every correction is understood first, as a mistake by the draft, a one-off choice, or a real house preference. Only house preferences can become profile changes, and only after the professional confirms them.

Each table pairs the plain-English statement (left) with the part of the system that does it (right). Paths are relative to `backend/` unless they start with `frontend/`. Ticket numbers refer to `reference/ref_3/dess-050-dess-054.excalidraw`.

## The loop

### 1. The system writes a draft

| What happens | How it is built |
|---|---|
| The system writes a draft from the agenda and transcript. | `app/minutes/pipeline.py` `Pipeline.run_drafting`: reads the evidence, then for each agenda item selects the content and writes its minute, then checks the whole draft once and reconsiders the items that have findings. |
| It follows the DESS standards. | `app/minutes/profiles/dess_standard.md` (both DESS documents, word for word) is sent with every model call: `PromptContext.system()` in `app/minutes/prompts.py`. |
| Each agenda item is drafted on its own, so even a cheaper model writes full minutes rather than a thin summary. | `Pipeline._each` runs one call per item in parallel (`MINUTES_PARALLEL_CALLS`). Code joins the results: `assemble_selection` and `assemble_draft`. |

### 2. The edited Word document comes back (DESS-050)

| What happens | How it is built |
|---|---|
| The exact Word file the professional downloads is kept as the original. | `app/services/edits.py` `export_document` stores the bytes and their SHA-256 hash (`exported_documents` table) on every download. |
| Every paragraph carries a hidden id, so it can be found again after editing. | `app/minutes/docx_export.py` `render_for_review` puts a hidden bookmark `_dess_p_<n>` on each paragraph and writes the draft id and export id into the file's properties. |
| The professional edits in Word as usual (Track Changes on or off, comments, replies to our questions) and uploads the file on the minutes or Edits page. | `POST /api/drafts/{id}/final` sends it to `edits.upload_edited`, which stores the uploaded bytes and hash (`edited_documents` table). |
| Tracked changes are read properly. | `app/minutes/docx_read.py` `read_docx` walks the Word XML itself: insertions kept, deletions dropped, and every tracked change kept as evidence. Plain `paragraph.text` would skip inserted text. |
| Each paragraph is lined up with the original: unchanged, changed, removed, added or moved to another item. | `app/minutes/alignment.py` `align`: matches by hidden id first; then by similarity within the same agenda item, for paragraphs whose id was lost; then across items, to find moved paragraphs. Stored in `edit_alignments`. |
| A reply to one of our questions is linked back to that question. | `docx_read._comments` follows Word's reply links (`commentsExtended.xml`); `edits._comments` matches the parent comment to the draft's question. |
| The result is shown side by side for each agenda item, with word-level differences. | `alignment.word_diff`; the **Edits** page `frontend/src/routes/drafts/[id]/edits/+page.svelte`. |

### 3. Each edit is understood before anything is learned (DESS-051)

| What happens | How it is built |
|---|---|
| A changed paragraph is split into its separate edits, so a corrected figure and a rewording in the same sentence are judged separately. | `app/minutes/edit_labels.py` `hunks`. |
| Cheap cases are labelled by rules, with no model call: formatting only, punctuation, capitalisation, date format, a name replaced by a role. | `edit_labels.code_label`. A name replaced by a role is "profile not applied" under WS4, which says to use roles for ordinary reporting. |
| Every other edit is labelled by the model, one call per agenda item. It sees the original and edited text, what the drafting stage selected, the transcript lines and the professional's comments, plus the whole profile. | `app/services/edit_classify.py` `classify`; the instructions are `TASK_CLASSIFY` in `edit_labels.py`. Each call appears in the AI activity panel as `classify:<item>`. |
| Each edit gets a **kind**: factual correction, content added, content removed, wording or style, structure or layout. | `EditLabel.kind` |
| … a **dimension**, MP1 to MP9 or WS1 to WS6. | `EditLabel.dimensions` |
| … and a **cause**: the evidence was misread; the profile already requires this and the draft did not apply it; the profile is silent or says otherwise; or a choice for this meeting only. | `EditLabel.cause` |
| For added content, it records whether the transcript supports it (with line references) or it comes from the professional's own knowledge. | `EditLabel.support` and `EditLabel.evidence` |
| Repeated edits become one finding with a count: fourteen names replaced by "the Board" are one finding, not fourteen. | `edit_labels.group_findings` groups by rule, or by the same change appearing in several places. |
| **The cause decides where an edit goes.** Mistakes by the draft go to the team's defect list and become test cases. One-off choices stay with that meeting. Only "the profile is silent or says otherwise" can go forward as a proposed profile change. | `edit_labels.ROUTES`: `defect`, `meeting_only` or `candidate`. Shown as three groups on the Edits page. |

### 4. Proposed changes are confirmed by a person (DESS-052, DESS-053; in progress)

| What happens | How it is built |
|---|---|
| Candidate edits become amendment proposals in plain English, with their evidence, and are checked against the existing provisions for conflicts and duplicates. | Issue #25 (DESS-052): a proposal object and a review screen. |
| The professional accepts, rejects or rewords each one; accepted proposals create a new profile version. | `create_version(origin=feedback)` in `app/services/profile.py`. Drafts only use confirmed versions (`active_version`). |
| We show the next draft is better before relying on the change. | DESS-054; `evals/replay.py` re-drafts past meetings with a new profile version and compares the results with the professionals' final copies. |

## House examples

| What happens | How it is built |
|---|---|
| An organisation's final edited minutes are shown to later drafts for similar items, as examples of structure and phrasing, never of facts. | `app/services/learning.py` `house_examples`, by agenda item purpose (approval, noting and so on), up to 2 each. They go into each item's prompt as `<house_examples>`. |
| Examples never cross between organisations. | Only for organisation profiles (created from DESS Standard on the Minutes profiles page), and only from that profile's own drafts. |

## Safeguards

| Safeguard | How it is built |
|---|---|
| **Nothing changes the profile without a person.** Classification only labels edits; it never edits the profile. | `edit_classify.py` writes only `edit_classifications`. Profile versions are created through confirmation (DESS-052/053). |
| **The cause label protects the profile.** A broad rule is never inferred from one specific edit, and rules the Standard already has are not added again. | `ROUTES`: only `profile_silent` edits are candidates. The model is told to check the dimension's default standard before choosing anything else. |
| **Every label shows its reason and evidence.** | `reason`, `profile_basis` and `evidence` on each label, shown on the Edits page. |
| **Each organisation learns separately.** | Organisation profiles and the per-profile filter in `house_examples`. |

## How we know it's improving

| What happens | How it is built |
|---|---|
| Every piece of feedback earns a score from 0 to 1: approval 1, revision request 0, an edited copy the share of the draft kept. | `app/services/feedback.py`; for an edited copy, `roundtrip.summarise` (word-weighted similarity per item). |
| The scores page compares setups (profile version and model). | `feedback.scores`, `GET /api/feedback/scores`, the **Draft scores** page. Expected score `(sum + 1) / (n + 2)`. |
| Quality is measured against the DESS standards, not only against edits. | `evals/compare.py` with `evals/judge.py`: a strong model scores minutes 1–5 per agenda item. |

## "Is this machine learning?"

| What to say | Why, technically |
|---|---|
| It's learning from feedback without retraining the model. | The model is fixed by `LLM_MODEL`. Only the profile (after confirmation) and the examples change. |
| Retraining would need hundreds of corrected minutes, which we don't have yet. | Fine-tuning needs a large set of draft and final pairs. |
| Every change can be read and reversed. | Profile versions are kept; to undo one, upload an earlier version's content as a new version and confirm it. |
| The data for retraining later is being collected now. | `exported_documents` and `edited_documents` hold each original and final file; `edit_alignments` and `edit_classifications` hold what changed and why. |
