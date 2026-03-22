# Deal Intelligence Agent Platform — Precise Review Notes

## Current design strengths

- **Context-scoped workflow model**: one Temporal workflow per `context_id` is clean and scalable.
- **Context ID as partition key**: good for isolation, audit, access control, and tracing.
- **Temporal-native lifecycle**: signals, activities, wait conditions, timers, and `continue_as_new` fit long-lived contexts well.
- **Shared worker pool**: good infra scaling model.
- **OPA enforcement**: strong enterprise control point.
- **Phased rollout**: practical and buildable.

## What is mostly fine as-is

- **Context resolution** can stay mostly deterministic if source-to-context mapping is pre-registered.
- **Folder / SharePoint site / email subject / source registration** are good routing anchors.
- **Temporal scalability** is not the main concern.

## Main gaps in current design

### 1. Truth / provenance model
**Current**
- Extracted values merge into working state.
- Overwrite is too simple.

**Suggestion**
- Track each fact with provenance.
- Store: `field`, `value`, `source`, `source_version`, `confidence`, `status`, `observed_at`, `approved_by`, `committed`.

### 2. Memory vs business state boundary
**Current**
- Boundary is not clear.

**Suggestion**
- Split into:
  - **Working memory** = observed / extracted / candidate / conflicted
  - **Committed business state** = approved / promoted / written to system of record

### 3. Conflict resolution
**Current**
- Last-write-wins / overwrite notification.

**Suggestion**
- Do not auto-overwrite important fields.
- Use:
  - source priority
  - version-aware supersession
  - conflict object + approval when needed

### 4. Readiness gates
**Current**
- Gate opens when fields are present.

**Suggestion**
- Gate should open only when fields are:
  - present
  - not conflicted
  - fresh enough
  - from acceptable source quality
  - approval-cleared if needed

### 5. Duplicate document handling
**Current**
- Not fully defined.

**Suggestion**
- Add 3 layers:
  1. **Event dedupe**: event/message/file version ids
  2. **Artifact dedupe**: content hash / normalized text hash
  3. **Lineage**: detect draft vs final vs superseding version

### 6. Approval hops
**Current**
- Risk of too many individual approvals.

**Suggestion**
- Approve **decision bundles**, not tool calls.
- One approval can cover multiple proposed state updates.

## Recommended state model

### Fact lifecycle
- `observed`
- `extracted`
- `candidate`
- `conflicted`
- `approved`
- `committed`
- `superseded`

## Recommended system layers

### Layer A: Raw evidence
- Documents, emails, event payloads, system snapshots

### Layer B: Fact ledger
- Versioned extracted facts with provenance

### Layer C: Working context state
- Best candidate values, conflicts, pending approvals, gate status

### Layer D: Committed business state
- Only approved / promoted data written to operational systems

## Simple operating rule

- **Memory is where the agent thinks.**
- **Business state is where the firm acts.**

## Buildability assessment

### Can be built now
- Context-scoped orchestration
- Document ingestion and extraction
- Deterministic routing from registered sources
- Approval-based progression
- Audit trail and dashboarding

### Should not be too broad in v1
- Full autonomous mutation of business systems
- Broad last-write-wins promotion
- Heavy generated-code execution
- Too many approval checkpoints

## Priority changes before implementation

1. Add a **fact ledger with provenance**
2. Separate **working memory** from **committed state**
3. Replace **last-write-wins** with **conflict-aware promotion**
4. Add **event/artifact dedupe + document lineage**
5. Move to **decision-bundle approvals**
6. Strengthen readiness gates beyond field presence

## Final view

- **Infra scalability**: good
- **Architecture direction**: strong
- **Main risk**: truth management, not workflow scaling
- **Recommendation**: proceed, but tighten state model before expanding autonomy
