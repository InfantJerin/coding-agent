# Human-in-the-Loop (HITL) Patterns for AI Agents

**Research Date:** March 2026
**Focus:** Production-ready patterns within the Microsoft/Teams ecosystem

---

## 1. Microsoft Teams as an Agent Interaction Channel

### 1.1 Adaptive Cards for Interactive Approvals

Adaptive Cards are the **recommended card type** for new Teams development. They are cross-product cards that work across Teams, Outlook, Cortana, and Windows.

**Core approval pattern with Action.Execute:**

```json
{
  "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
  "type": "AdaptiveCard",
  "version": "1.4",
  "refresh": {
    "action": {
      "type": "Action.Execute",
      "title": "Refresh",
      "verb": "acceptRejectView"
    },
    "userIds": ["<approver1-MRI>", "<approver2-MRI>"]
  },
  "body": [
    { "type": "TextBlock", "text": "Approval Request B12" },
    { "type": "TextBlock", "text": "Submitted by **Agent: DealBot**" },
    { "type": "TextBlock", "text": "Approval pending from **Megan and Nestor**" }
  ],
  "actions": [
    {
      "type": "Action.Execute",
      "title": "Approve",
      "verb": "approve",
      "data": { "requestId": "B12", "dealId": "DEAL-456" }
    },
    {
      "type": "Action.Execute",
      "title": "Reject",
      "verb": "reject",
      "data": { "requestId": "B12", "dealId": "DEAL-456" }
    }
  ]
}
```

**Key concepts:**
- **Action.Execute** (Universal Actions) is the modern approach; replaces legacy `Action.Submit`
- **User-Specific Views** via the `refresh` property: only users listed in `userIds` see Approve/Reject buttons; others see a read-only base card
- When a user clicks Approve, Teams sends an `adaptiveCard/action` invoke to the bot, which can respond with an updated card
- **Message edit** after approval updates the card for all conversation members, reflecting the new state
- The bot removes the approver's MRI from `userIds` after their decision, so auto-refresh stops for them

**Response modes for card actions:**
| Mode | Behavior |
|------|----------|
| `AdaptiveCardResponse.ReplaceForInteractor` | Replaces card only for the clicker (default) |
| `AdaptiveCardResponse.ReplaceForAll` | Replaces card for everyone in the conversation |
| `AdaptiveCardResponse.NewForAll` | Sends a new card as a separate message |

### 1.2 Teams Bot Framework -- Building Workflow Bots

The **TeamsFx SDK** provides `TeamsFxAdaptiveCardActionHandler` for handling card actions:

```typescript
// Card action handler for approval
export class ApproveActionHandler implements TeamsFxAdaptiveCardActionHandler {
  triggerVerb = "approve";
  adaptiveCardResponse = AdaptiveCardResponse.ReplaceForAll;

  async handleActionInvoked(context: TurnContext, actionData: any): Promise<InvokeResponse> {
    // actionData contains { requestId, dealId } from the card
    // Call your approval service here
    await approvalService.approve(actionData.requestId, context.activity.from.id);

    // Return updated card showing approval status
    const updatedCard = AdaptiveCards.declare(approvedCardTemplate).render({
      approvedBy: context.activity.from.name,
      timestamp: new Date().toISOString()
    });
    return InvokeResponseFactory.adaptiveCard(updatedCard);
  }
}
```

**Registration in bot initialization:**
```typescript
const conversationBot = new ConversationBot({
  cardAction: {
    enabled: true,
    actions: [
      new ApproveActionHandler(),
      new RejectActionHandler()
    ],
  }
});
```

**Architecture:**
1. Bot sends an Adaptive Card (the "action card") to a channel or chat
2. User clicks a button (Action.Execute with a unique `verb`)
3. Teams sends an `adaptiveCard/action` invoke to the bot
4. The card action handler matching `triggerVerb` fires
5. Handler executes business logic and returns a response card

### 1.3 Power Automate Approval Flows via Teams

Power Automate provides built-in **approval connectors** that integrate with Teams:
- Create approval flows that post Adaptive Cards to Teams channels
- Supports "Approve/Reject" and "Custom Responses" (e.g., "Approve with modifications")
- Approvals appear in the Teams Approvals app
- Outcomes feed back into the flow for downstream actions

This is a **low-code option** suitable for simpler approval workflows that don't need deep programmatic control.

### 1.4 Deal Room / Channel-per-Deal Pattern

Microsoft provides a **Deal Room template** in Sales Copilot (formerly Viva Sales):

**Architecture:**
- Each CRM opportunity gets its own Teams channel within an account-level team
- The channel is named after the opportunity (e.g., "Coffee Machine Deal")
- Linked to the CRM record (Dynamics 365 or Salesforce)
- Includes a **shared channel** option for external collaboration with customers
- Pre-configured with pinned apps and tabs

**Programmatic channel creation via Graph API:**
```
POST /teams/{team-id}/channels
```
```json
{
  "displayName": "DEAL-456-Acme-Refinancing",
  "description": "Deal room for Acme Corp refinancing",
  "membershipType": "private"
}
```

Required permissions: `Channel.Create`, `Group.ReadWrite.All`, or `Directory.ReadWrite.All`.

**Channel types:**
| Type | Use Case |
|------|----------|
| `standard` | Open to all team members |
| `private` | Restricted to specific members |
| `shared` | Cross-organization collaboration |

### 1.5 Microsoft Copilot Studio Agents in Teams

As of November 2025, Copilot Studio supports **Human-in-the-Loop (HITL) in preview**:
- Agents can pause and request human input before continuing
- Structured requests are delivered as Outlook forms to designated reviewers
- After the reviewer responds, the agent resumes using submitted values as parameters
- Agents publish to Teams and Microsoft 365 Copilot directly

**2026 outlook:** Agent Flows and the Workflows Agent allow agents to own end-to-end processes with automated approvals, escalating to humans only when judgment is required.

### 1.6 Teams Activity Feed Notifications

The **Activity Feed API** (Microsoft Graph) enables agents to send notifications that appear in users' Activity Feed with native OS pop-ups:

**Manifest configuration:**
```json
{
  "activities": {
    "activityTypes": [
      {
        "type": "approvalRequired",
        "description": "Agent needs your approval",
        "templateText": "{actor} requires approval for {actionDescription}"
      }
    ]
  }
}
```

**API call to notify a user:**
```
POST /v1.0/teams/{teamId}/sendActivityNotification
```
```json
{
  "topic": {
    "source": "text",
    "value": "Deal Action Approval",
    "webUrl": "https://teams.microsoft.com/l/entity/..."
  },
  "activityType": "approvalRequired",
  "previewText": { "content": "Agent wants to update pricing on DEAL-456" },
  "recipient": {
    "@odata.type": "microsoft.graph.aadUserNotificationRecipient",
    "userId": "569363e2-..."
  },
  "templateParameters": [
    { "name": "actionDescription", "value": "update pricing from $2.5M to $2.3M" }
  ]
}
```

**Capabilities:**
- Deep-link into tabs, personal apps, bot messages, or Adaptive Cards
- Batch notifications to up to 100 users at a time
- Custom activity icons (in devPreview)
- Multiple recipient types: individual users, team members, channel members, chat members

### 1.7 Actionable Messages from Agents

**The complete flow for agent-sent actionable messages:**

1. **Agent posts an Adaptive Card** to a Teams channel/chat via the Bot Framework
2. The card contains `Action.Execute` buttons with verbs like `approve`, `reject`, `requestMoreInfo`
3. The `data` payload carries context (deal ID, proposed changes, agent reasoning)
4. **User-Specific Views** ensure only authorized approvers see action buttons
5. When a button is clicked, the bot receives an `adaptiveCard/action` invoke
6. The bot processes the action and:
   - Updates the card in place via `message edit` (reflected for all viewers)
   - Triggers the next step in the workflow (e.g., signals Temporal, sends event to Inngest)
7. **Centralized tracking** prevents duplicate responses, maintains audit logs, and sends outcome notifications

**Important limitation:** Microsoft Graph API only supports cards with `OpenUrl` action. For interactive cards with `Action.Execute`, you **must** use a Bot Framework bot, not raw Graph API message posting.

---

## 2. Approval Gate Patterns in Agentic Workflows

### 2.1 Temporal.io -- Signals for Human-in-the-Loop

Temporal is the most robust option for durable human-in-the-loop workflows.

**Architecture:**

```
Agent Workflow (Temporal) -----> Notify Human (Teams/Slack/Email)
        |                                    |
        v                                    v
  wait_condition()                  Human reviews in Teams
  (no compute consumed)                      |
        |                                    v
        | <--- Signal -----------  Human clicks Approve/Reject
        v
  Resume execution
```

**Implementation:**

```python
# Data models
@dataclass
class ApprovalDecision:
    request_id: str
    approved: bool
    comment: str = ""

# Workflow
@workflow.defn
class DealApprovalWorkflow:
    def __init__(self):
        self.approval_decision: Optional[ApprovalDecision] = None
        self.pending_request_id: Optional[str] = None

    @workflow.signal
    async def approval_decision_signal(self, decision: ApprovalDecision):
        if decision.request_id == self.pending_request_id:
            self.approval_decision = decision

    @workflow.run
    async def run(self, deal_action: DealAction) -> str:
        # Step 1: Agent analyzes and proposes action
        proposal = await workflow.execute_activity(
            analyze_deal_action, deal_action, schedule_to_close_timeout=timedelta(seconds=30)
        )

        # Step 2: Notify human via Teams
        self.pending_request_id = proposal.request_id
        await workflow.execute_activity(
            send_teams_approval_card, proposal, schedule_to_close_timeout=timedelta(seconds=10)
        )

        # Step 3: Wait for human decision (NO compute consumed)
        try:
            await workflow.wait_condition(
                lambda: self.approval_decision is not None,
                timeout=timedelta(hours=4),  # Auto-escalate after 4 hours
            )
        except asyncio.TimeoutError:
            await workflow.execute_activity(escalate_approval, proposal)
            return "ESCALATED"

        # Step 4: Execute or reject based on decision
        if self.approval_decision.approved:
            return await workflow.execute_activity(execute_deal_action, deal_action)
        else:
            return f"REJECTED: {self.approval_decision.comment}"
```

**Key properties:**
- Workflows can wait for hours, days, or indefinitely **without consuming compute**
- If the system crashes, the workflow resumes exactly where it left off
- Durable timers survive infrastructure disruptions
- Signals are delivered via Temporal Client from any external system (Teams bot, API endpoint, etc.)
- Queries allow read-only state inspection without modifying the workflow

**Sending the signal from a Teams bot handler:**
```python
async def handle_approval(request_id: str, approved: bool, comment: str):
    client = await Client.connect("temporal-server:7233")
    handle = client.get_workflow_handle(f"deal-approval-{request_id}")
    await handle.signal(
        DealApprovalWorkflow.approval_decision_signal,
        ApprovalDecision(request_id=request_id, approved=approved, comment=comment)
    )
```

### 2.2 Inngest -- waitForEvent() Pattern

Inngest provides a serverless-friendly alternative for durable human-in-the-loop:

```typescript
const dealApproval = inngest.createFunction(
  { id: "deal-approval" },
  { event: "deal/action.proposed" },
  async ({ event, step }) => {
    // Step 1: Agent proposes action (cached/durable)
    const proposal = await step.run("analyze-deal", async () => {
      return await analyzeAndPropose(event.data.dealId);
    });

    // Step 2: Send notification to Teams
    await step.run("notify-approver", async () => {
      await sendTeamsApprovalCard(proposal);
    });

    // Step 3: Wait for approval event (pauses, no compute consumed)
    const approval = await step.waitForEvent("wait-for-approval", {
      event: "deal/action.approved",
      match: "data.requestId",  // Correlate by request ID
      timeout: "4h",             // Auto-escalate after 4 hours
    });

    if (!approval) {
      // Timeout -- escalate
      await step.run("escalate", async () => {
        await escalateToManager(proposal);
      });
      return { status: "ESCALATED" };
    }

    // Step 4: Execute approved action
    if (approval.data.approved) {
      return await step.run("execute-action", async () => {
        return await executeDealAction(proposal);
      });
    }
    return { status: "REJECTED", reason: approval.data.reason };
  }
);
```

**Key properties:**
- `waitForEvent()` uses CEL expressions for event matching
- Configurable timeouts (e.g., `"7d"` for week-long approvals)
- Each `step.run()` is checkpointed; retries don't re-execute previous steps
- Works on serverless (Vercel, Cloudflare Workers, etc.)
- The approval event can be sent from any system via Inngest's event API

### 2.3 LangGraph -- interrupt() and Checkpoints

LangGraph provides the most direct integration with LLM agent workflows:

**How it works:**

```python
from langgraph.checkpoint.memory import InMemorySaver  # Use AsyncPostgresSaver in production

def approval_node(state: AgentState) -> AgentState:
    # Pause execution and wait for human input
    decision = interrupt(
        "Agent proposes to update pricing from $2.5M to $2.3M on DEAL-456. "
        "Please enter 'approve' or 'reject'."
    )
    return {**state, "approval_decision": decision}

# Build the graph
builder = StateGraph(AgentState)
builder.add_node("analyze", analyze_node)
builder.add_node("approval", approval_node)
builder.add_node("execute", execute_node)
builder.add_node("reject", reject_node)

# Compile with checkpointer (required for interrupts)
memory = InMemorySaver()  # AsyncPostgresSaver for production
graph = builder.compile(checkpointer=memory)

# Execute until interrupt
thread = {"configurable": {"thread_id": "deal-456"}}
for event in graph.stream(initial_input, thread, stream_mode="values"):
    print(event)
# Graph is now paused at interrupt()

# Resume after human decision
for event in graph.stream(Command(resume="approve"), thread, stream_mode="values"):
    print(event)
```

**Key properties:**
- `interrupt()` pauses the graph and preserves complete state
- `Command(resume=value)` resumes from exact checkpoint
- `Command(goto="node_name")` enables dynamic routing post-approval
- Checkpointer backends: InMemorySaver (dev), AsyncPostgresSaver (production), Redis
- `interrupt_before=["node_name"]` for breakpoints at specific nodes
- Three human decision types: **approve** (proceed), **edit** (modify), **reject** (with feedback)

### 2.4 CrewAI -- Human Delegation

CrewAI supports HITL via task-level configuration:

```python
from crewai import Task, Agent

review_task = Task(
    description="Review the proposed deal terms for DEAL-456",
    agent=deal_analyst_agent,
    human_input=True  # Pauses before final answer for human validation
)
```

**Patterns:**
- **`human_input=True`**: Agent prompts user for validation before delivering final answer
- **Webhook-based pause**: Crew pauses, notifies external system via webhook, waits for feedback
- **HumanTool**: Agents invoke a tool that routes to a human when guidance is needed
- **Hierarchical delegation**: `allow_delegation=True` with `allowed_agents` parameter controls which agents can delegate to humans

**Collaboration models:**
| Model | Description |
|-------|-------------|
| Supervisor | Human approves key actions |
| Co-pilot | Agent works alongside human, offering suggestions |
| Conversational Partner | Agent asks clarifying questions to help human think |

### 2.5 Camunda/Flowable -- Human Task Patterns

Camunda implements a mature, BPMN-based human task model:

**Task assignment strategy:**
- Assign to **candidate groups** (not individuals) to distribute workload
- Individuals **claim** tasks before working on them, preventing duplicate effort
- Tasks can target specific assignees via process variables when needed

**Task lifecycle:** Assignment -> Claiming -> Completion (with delegation/escalation capabilities)

**External Task Pattern for agent integration:**
1. Process reaches a service task configured as an "external task"
2. Camunda creates the task and waits
3. An external worker (the AI agent) fetches, executes, and completes the task
4. If human approval is needed, the process routes to a user task
5. The user task appears in Camunda Tasklist or a custom task list

**Frontend integration options:**
| Approach | Pros | Cons |
|----------|------|------|
| Camunda Tasklist | Zero development effort | Limited customization |
| Custom Task List via API | Full UX control | Requires development |
| Third-party integration | Fits existing tools | Complex synchronization |

---

## 3. Agent-to-Human Notification Patterns

### 3.1 Production Notification Strategies

**Tiered notification approach for AI agents:**

| Severity | Channel | Example |
|----------|---------|---------|
| Informational | Activity Feed / simple message | "Agent completed analysis of 50 deals" |
| Action Required | Adaptive Card with buttons | "Agent needs approval to update pricing" |
| Urgent / Escalation | Activity Feed + @mention + card | "Approval timeout: 3h remaining on $5M deal" |
| Critical / Failure | PagerDuty + Teams + Email | "Agent failed after 3 retries on deal execution" |

### 3.2 Adaptive Cards vs. Simple Messages

**Use Adaptive Cards when:**
- The notification requires user action (approve, reject, provide input)
- You need structured display of data (tables, facts, images)
- You want to show progress with visual elements
- You need user-specific views (different buttons for different roles)
- Dynamic data binding via templates is needed

**Use simple text messages when:**
- The notification is purely informational
- No user action is required
- You want minimal UI overhead
- Speed of delivery matters more than presentation

**Adaptive Card for agent status update:**
```json
{
  "type": "AdaptiveCard",
  "version": "1.4",
  "body": [
    {
      "type": "TextBlock",
      "text": "Agent Status: Deal Analysis Complete",
      "weight": "Bolder",
      "size": "Medium"
    },
    {
      "type": "FactSet",
      "facts": [
        { "title": "Deal:", "value": "DEAL-456 Acme Refinancing" },
        { "title": "Action:", "value": "Pricing update proposed" },
        { "title": "Current Price:", "value": "$2,500,000" },
        { "title": "Proposed Price:", "value": "$2,300,000" },
        { "title": "Confidence:", "value": "87%" },
        { "title": "Risk Level:", "value": "Medium" }
      ]
    },
    {
      "type": "TextBlock",
      "text": "**Agent Reasoning:** Market analysis shows comparable deals closing at $2.2-2.4M range. Reducing to $2.3M increases close probability by 23% based on historical data.",
      "wrap": true
    }
  ],
  "actions": [
    {
      "type": "Action.Execute",
      "title": "Approve",
      "verb": "approve",
      "data": { "dealId": "DEAL-456", "newPrice": 2300000 }
    },
    {
      "type": "Action.Execute",
      "title": "Reject",
      "verb": "reject",
      "data": { "dealId": "DEAL-456" }
    },
    {
      "type": "Action.Execute",
      "title": "Modify Amount",
      "verb": "modify",
      "data": { "dealId": "DEAL-456" }
    }
  ]
}
```

### 3.3 Escalation Patterns

**The ESCALATE.md protocol** provides a standardized configuration for AI agent escalation:

**Configuration structure:**
```markdown
## TRIGGERS
- Production deployments
- Financial transactions
- Actions exceeding cost_exceeds_usd: 100.00

## CHANNELS
- Email: address, timeout_minutes
- Slack: channel, timeout_minutes

## APPROVAL
- approval_timeout_minutes: 240
- on_timeout: escalate_to_killswitch
- on_denial: halt_and_log
- on_approval: proceed_and_log
```

**Approval methods:** Email reply (APPROVE/DENY), Slack emoji reaction, POST to approval API endpoint with signed token.

**Context requirements for escalation notifications:**
- Requested action in plain language
- Justification
- Estimated costs
- Reversibility assessment
- Alternatives considered
- Session ID for log correlation
- Approval deadline

### 3.4 Proactive Messaging from Bots (No User Initiation)

Teams bots can send messages proactively (without a user message first):

**Prerequisites:**
1. Bot must be installed in the target context (team, chat, or personal)
2. Store a `conversationReference` when the bot first interacts

**Sending a proactive message:**
```csharp
// C# - Store conversation references on first interaction
private readonly ConcurrentDictionary<string, ConversationReference> _conversationReferences;

// Later, send proactive message
foreach (var conversationReference in _conversationReferences.Values)
{
    await ((BotAdapter)_adapter).ContinueConversationAsync(
        _appId, conversationReference, BotCallback, default(CancellationToken));
}

private async Task BotCallback(ITurnContext turnContext, CancellationToken cancellationToken)
{
    // Send Adaptive Card or text message
    var card = CreateApprovalCard(pendingApproval);
    var attachment = new Attachment
    {
        ContentType = "application/vnd.microsoft.card.adaptive",
        Content = card
    };
    await turnContext.SendActivityAsync(MessageFactory.Attachment(attachment));
}
```

**JavaScript equivalent:**
```javascript
const ref = TurnContext.getConversationReference(context.activity);
await context.adapter.continueConversation(ref, async (context) => {
    await context.sendActivity("Agent needs your attention on DEAL-456.");
});
```

**Best practices:**
- Store conversation references in a database (not in-memory)
- The bot can be proactively installed via Microsoft Graph
- Track message IDs to later update or delete proactive messages
- Use `UpdateActivityAsync` to update existing Adaptive Cards in place

---

## 4. Interactive Approval UIs for AI Agents

### 4.1 What a Good Approval Interface Looks Like

**Essential components of an agent approval request:**

1. **Proposed action in plain language**: "Agent wants to reduce pricing from $2.5M to $2.3M"
2. **Agent reasoning/justification**: The chain of thought or analysis that led to the proposal
3. **Relevant context**: Deal details, customer history, comparable transactions
4. **Risk indicators**: Confidence score, risk classification, irreversibility flag
5. **Clear action buttons**: Approve, Reject, Modify, Request More Info
6. **Deadline indicator**: "Approval needed by 5:00 PM EST"

### 4.2 Diff-Style Views

For changes to structured data, show what the agent proposes to change:

```json
{
  "type": "ColumnSet",
  "columns": [
    {
      "type": "Column",
      "items": [
        { "type": "TextBlock", "text": "Field", "weight": "Bolder" },
        { "type": "TextBlock", "text": "Price" },
        { "type": "TextBlock", "text": "Term" },
        { "type": "TextBlock", "text": "Rate" }
      ]
    },
    {
      "type": "Column",
      "items": [
        { "type": "TextBlock", "text": "Current", "weight": "Bolder" },
        { "type": "TextBlock", "text": "$2,500,000" },
        { "type": "TextBlock", "text": "5 years" },
        { "type": "TextBlock", "text": "4.5%" }
      ]
    },
    {
      "type": "Column",
      "items": [
        { "type": "TextBlock", "text": "Proposed", "weight": "Bolder", "color": "Attention" },
        { "type": "TextBlock", "text": "$2,300,000", "color": "Attention" },
        { "type": "TextBlock", "text": "5 years" },
        { "type": "TextBlock", "text": "4.5%" }
      ]
    }
  ]
}
```

### 4.3 Approval with Modification

Support "approve but change the amount" via Adaptive Card input fields:

```json
{
  "type": "Action.Execute",
  "title": "Approve with Modification",
  "verb": "approveModified",
  "data": { "dealId": "DEAL-456" }
}
```

When the user clicks this, show a follow-up card (via `Action.ShowCard` or a new card response) with input fields:

```json
{
  "type": "Input.Number",
  "id": "modifiedPrice",
  "label": "Enter approved amount",
  "placeholder": "2300000",
  "min": 0
}
```

### 4.4 Timeout and Auto-Escalation

**Tiered escalation with SLAs:**

| Tier | Trigger | Reviewers | SLA |
|------|---------|-----------|-----|
| Tier 1 | Confidence 0.6-0.8, moderate risk | Team reviewers | 4 hours |
| Tier 2 | Confidence <0.6 or high blast radius | Team leads | 1 hour |
| Tier 3 | Compliance/critical infrastructure | Executives | 15 minutes |

**Implementation pattern:**
1. Agent sends initial approval card with deadline
2. Workflow sets timeout (Temporal `wait_condition` / Inngest `waitForEvent` / LangGraph checkpoint)
3. If timeout expires:
   - Send escalation notification to next-tier approver
   - Update original card to show escalation status
   - Start new timer for escalated approval
4. If all tiers exhaust: auto-deny and log, or route to killswitch

**Production best practices:**
- Test timeout paths before production (what if reviewer is on vacation?)
- Default to "deny" for financial actions when no one responds
- Log every timeout with full context for audit
- Send reminder notifications at 50% and 75% of timeout window

---

## 5. Financial Services-Specific Patterns

### 5.1 Maker-Checker Pattern with AI Agents

The maker-checker (four-eyes) principle is foundational in financial services: **for each transaction, at least two individuals are required for completion**.

**AI agent as maker, human as checker:**
1. AI agent analyzes deal data and proposes an action (maker)
2. Human reviews and approves/rejects (checker)
3. Action executes only after human approval

**AI agent as accelerated checker:**
1. Human initiates a deal action (maker)
2. AI agent performs automated compliance checks (first check)
3. Human reviewer performs final approval (second check)
4. Automation provides instant validation (limit breaches, policy violations)

**Implementation considerations:**
- The agent's proposal and the human's approval must be from **different principals**
- Audit trail must capture both the agent's reasoning and the human's decision
- The human cannot be the same person who configured the agent's rules

### 5.2 Four-Eyes Principle Implementation

**Pattern for AI-assisted four-eyes:**
```
Agent (Eye 1: Automated Analysis)
    |
    v
Reviewer 1 (Eye 2: Business Judgment)
    |
    v
[Optional] Reviewer 2 (Eye 3: Compliance/Risk)
    |
    v
[Optional] Reviewer 3 (Eye 4: Senior Management for high-value)
```

**Threshold-based routing:**
| Deal Value | Required Approvals |
|-----------|-------------------|
| < $100K | Agent auto-approves (logged) |
| $100K - $1M | Agent + 1 human reviewer |
| $1M - $10M | Agent + 2 human reviewers (four-eyes) |
| > $10M | Agent + 2 reviewers + senior management |

### 5.3 Audit Trail Requirements

Every approval interaction must capture:
- **Timestamp** (UTC)
- **Action ID** (unique identifier)
- **Action type** (pricing change, term modification, etc.)
- **Agent confidence score** at time of proposal
- **Routing tier** and risk classification
- **Reviewer ID** (authenticated identity)
- **Decision** (approved/rejected/modified)
- **Time-to-decision** (SLA compliance tracking)
- **Modifications** (if the reviewer changed the proposal)
- **Full agent reasoning chain** (retrievable by session ID)

### 5.4 Confidence-Based Routing for Financial Actions

**Starting thresholds (calibrate after 30 days of production data):**

| Action Type | Irreversible? | Auto-Approve Threshold | Human Review Threshold |
|------------|---------------|----------------------|----------------------|
| Price inquiry | No | 0.70 | Below 0.70 |
| Term update | Yes | Never auto-approve | Always human |
| Pricing change | Yes | Never auto-approve | Always human |
| Document generation | No | 0.85 | Below 0.85 |
| Client communication | Partially | 0.90 | Below 0.90 |

**Calibration method:**
- Track Expected Calibration Error (ECE) across confidence buckets
- Compare agent's stated confidence vs. actual reviewer approval rate
- Per-action-type thresholds based on error cost analysis
- Recalibrate after 30 days of production data, then quarterly

---

## 6. Microsoft Graph API for Teams Programmatic Access

### 6.1 Creating Channels Programmatically

```
POST /teams/{team-id}/channels
Authorization: Bearer {token}
Content-Type: application/json
```

```json
{
  "displayName": "DEAL-456-Acme-Refinancing",
  "description": "Deal room for Acme Corp refinancing opportunity",
  "membershipType": "private"
}
```

**Required permissions:** `Channel.Create`, `Group.ReadWrite.All`, or `Directory.ReadWrite.All`

**Supported channel types:** `standard`, `private`, `shared`

### 6.2 Posting Messages with Adaptive Cards

```
POST /teams/{team-id}/channels/{channel-id}/messages
Authorization: Bearer {token}
Content-Type: application/json
```

```json
{
  "body": {
    "contentType": "html",
    "content": "<attachment id=\"74d20c7f-09a7-4f15-96de-f35f09e1e4e6\"></attachment>"
  },
  "attachments": [
    {
      "id": "74d20c7f-09a7-4f15-96de-f35f09e1e4e6",
      "contentType": "application/vnd.microsoft.card.adaptive",
      "content": "{\"type\":\"AdaptiveCard\",\"version\":\"1.4\",\"body\":[{\"type\":\"TextBlock\",\"text\":\"Agent Update\"}]}"
    }
  ]
}
```

**Required permissions:** `ChannelMessage.Send` (delegated), `Teamwork.Migrate.All` (application)

**Critical limitation:** Cards posted via Graph API only support `Action.OpenUrl`. For interactive cards with `Action.Execute` (approve/reject buttons), **you must use a Bot Framework bot** to post the card. Graph API can read bot-posted cards with other actions, but cannot create them.

### 6.3 Receiving Card Action Responses

When a user clicks an `Action.Execute` button:
1. Teams sends an `adaptiveCard/action` invoke activity to the bot
2. The bot's `onInvokeActivity` handler fires
3. The handler receives:
   - `context.activity.from` -- who clicked
   - `context.activity.value.action.verb` -- which button
   - `context.activity.value.action.data` -- the data payload
4. The bot returns an `InvokeResponse` with an updated card or status

### 6.4 Proactive Messaging Architecture

**Setup flow:**
1. Register the bot in Azure Bot Service
2. Install the bot app in target Teams/channels/users
3. On first interaction (`onMembersAdded` or any activity), capture and persist `ConversationReference`
4. When the agent needs to notify, retrieve the reference and call `continueConversationAsync`

**Proactive installation via Graph (no user interaction needed):**
```
POST /users/{user-id}/teamwork/installedApps
Content-Type: application/json
```
```json
{
  "teamsApp@odata.bind": "https://graph.microsoft.com/v1.0/appCatalogs/teamsApps/{teams-app-id}"
}
```

This installs the bot for a user, after which the bot can send proactive messages.

**Service URLs by environment:**
| Environment | URL |
|------------|-----|
| Public | `https://smba.trafficmanager.net/teams/` |
| GCC | `https://smba.infra.gcc.teams.microsoft.com/teams` |
| GCC High | `https://smba.infra.gov.teams.microsoft.us/teams` |
| DoD | `https://smba.infra.dod.teams.microsoft.us/teams` |

---

## 7. Recommended Architecture for a Teams-Based Agent Approval System

### End-to-End Flow

```
AI Agent (analysis/proposal)
    |
    v
Temporal Workflow (durable orchestration)
    |
    +--> Teams Bot posts Adaptive Card with approve/reject
    |         |
    |         v
    |    User clicks Approve/Reject in Teams
    |         |
    |         v
    |    Bot handler receives invoke, signals Temporal
    |
    v
Temporal resumes workflow
    |
    +--> If approved: execute action, post confirmation card
    +--> If rejected: log, notify agent, post rejection card
    +--> If timeout: escalate to next tier, send new card
```

### Technology Selection Guide

| Requirement | Recommended Approach |
|------------|---------------------|
| Interactive approvals in Teams | Bot Framework + Adaptive Cards with `Action.Execute` |
| Durable workflow orchestration | Temporal.io (most robust) or Inngest (serverless) |
| LLM agent integration | LangGraph `interrupt()` for within-agent pauses |
| Deal room per deal | Graph API channel creation + Deal Room template |
| Proactive notifications | Bot Framework proactive messaging + Activity Feed API |
| Audit trail | Log all decisions with Temporal workflow history |
| Multi-level approvals | Temporal signals + tiered escalation |
| Low-code approval flows | Power Automate with Teams approval connector |

---

## Sources

### Microsoft Teams & Bot Framework
- [Custom Teams bot for approval workflows and proactive messaging](https://learn.microsoft.com/en-in/answers/questions/5705984/custom-microsoft-teams-bot-for-approval-workflows)
- [Up to date views - Adaptive Cards in Teams](https://learn.microsoft.com/en-us/microsoftteams/platform/task-modules-and-cards/cards/universal-actions-for-adaptive-cards/up-to-date-views)
- [Build and Customize Workflow Bot in Teams](https://learn.microsoft.com/en-us/microsoftteams/platform/bots/how-to/conversations/workflow-bot-in-teams)
- [Send proactive messages - Teams](https://learn.microsoft.com/en-us/microsoftteams/platform/bots/how-to/conversations/send-proactive-messages)
- [Send notifications with a Bot - Teams](https://learn.microsoft.com/en-us/microsoftteams/platform/bots/build-notification-capability)
- [Add card actions in a bot - Teams](https://learn.microsoft.com/en-us/microsoftteams/platform/task-modules-and-cards/cards/cards-actions)
- [Designing Adaptive Cards for your app](https://learn.microsoft.com/en-us/microsoftteams/platform/task-modules-and-cards/cards/design-effective-cards)
- [Create flows that post Adaptive Cards to Teams](https://learn.microsoft.com/en-us/power-automate/create-adaptive-cards)

### Microsoft Graph API
- [Create channel - Microsoft Graph](https://learn.microsoft.com/en-us/graph/api/channel-post?view=graph-rest-1.0)
- [Send chatMessage in channel - Microsoft Graph](https://learn.microsoft.com/en-us/graph/api/chatmessage-post?view=graph-rest-1.0)
- [Teams messaging APIs overview](https://learn.microsoft.com/en-us/graph/teams-messaging-overview)
- [Send activity feed notifications - Microsoft Graph](https://learn.microsoft.com/en-us/graph/teams-send-activityfeednotifications)
- [Authorize Proactive Bot Installation - Graph](https://learn.microsoft.com/en-us/microsoftteams/platform/graph-api/proactive-bots-and-messages/graph-proactive-bots-and-messages)

### Microsoft Copilot Studio & Deal Rooms
- [Connect and configure agent for Teams - Copilot Studio](https://learn.microsoft.com/en-us/microsoft-copilot-studio/publication-add-bot-to-microsoft-teams)
- [What's new in Copilot Studio - November 2025](https://www.microsoft.com/en-us/microsoft-copilot/blog/copilot-studio/whats-new-in-microsoft-copilot-studio-november-2025/)
- [6 core capabilities to scale agent adoption in 2026](https://www.microsoft.com/en-us/microsoft-copilot/blog/copilot-studio/6-core-capabilities-to-scale-agent-adoption-in-2026/)
- [Set up a team using the deal room template](https://learn.microsoft.com/en-us/microsoft-sales-copilot/set-up-team-deal-room-template)
- [Collaboration spaces in the Sales agent](https://learn.microsoft.com/en-us/microsoft-sales-copilot/collaboration-space)

### Temporal.io
- [Human-in-the-Loop AI Agent - Temporal](https://docs.temporal.io/ai-cookbook/human-in-the-loop-python)
- [Adding Durable Human-in-the-Loop - Temporal Tutorials](https://learn.temporal.io/tutorials/ai/building-durable-ai-applications/human-in-the-loop/)
- [Building Long-Running MCP Tools with HITL - Temporal](https://learn.temporal.io/tutorials/ai/building-mcp-tools-with-temporal/adding-hitl-to-mcp-tools/)
- [Build resilient agentic AI with Temporal](https://temporal.io/blog/build-resilient-agentic-ai-with-temporal)

### LangGraph
- [Human-in-the-loop - LangChain Docs](https://docs.langchain.com/oss/python/langchain/human-in-the-loop)
- [Interrupts and Commands in LangGraph - DEV Community](https://dev.to/jamesbmour/interrupts-and-commands-in-langgraph-building-human-in-the-loop-workflows-4ngl)
- [LangGraph interrupt() - Simpler Way for HITL Agents](https://medium.com/@areebahmed575/langgraphs-interrupt-function-the-simpler-way-to-build-human-in-the-loop-agents-faef98891a92)
- [Building Production-Ready HITL AI Agents with LangGraph](https://dev.to/sreeni5018/beyond-input-building-production-ready-human-in-the-loop-ai-with-langgraph-2en9)
- [HITL Plan-and-Execute AI Agents with LangGraph and Streamlit](https://www.marktechpost.com/2026/02/16/how-to-build-human-in-the-loop-plan-and-execute-ai-agents-with-explicit-user-approval-using-langgraph-and-streamlit/)

### Inngest
- [Durable Execution: Key to Harnessing AI Agents - Inngest](https://www.inngest.com/blog/durable-execution-key-to-harnessing-ai-agents)
- [Inngest Agent Kit - GitHub](https://github.com/inngest/agent-kit)

### CrewAI
- [Human Input on Execution - CrewAI](https://docs.crewai.com/en/learn/human-input-on-execution)
- [Hierarchical AI Agents: Guide to CrewAI Delegation](https://activewizards.com/blog/hierarchical-ai-agents-a-guide-to-crewai-delegation)

### Camunda
- [Understanding Human Tasks Management - Camunda 8 Docs](https://docs.camunda.io/docs/components/best-practices/architecture/understanding-human-tasks-management/)
- [Orchestrate Human Workflows - Camunda](https://camunda.com/solutions/human-workflow/)
- [External Task Pattern with Camunda](https://contentservices.asee.io/maximizing-camundas-potential-with-external-task-pattern/)

### General HITL Patterns
- [Human-in-the-Loop Patterns for AI Agents (2026)](https://myengineeringpath.dev/genai-engineer/human-in-the-loop/)
- [HITL for AI Agents: Best Practices, Frameworks - Permit.io](https://www.permit.io/blog/human-in-the-loop-for-ai-agents-best-practices-frameworks-use-cases-and-demo)
- [The 2026 Guide to Agentic Workflow Architectures](https://www.stackai.com/blog/the-2026-guide-to-agentic-workflow-architectures)
- [ESCALATE.md - AI Agent Human Approval Protocol](https://escalate.md/)
- [The Escalation Rule Pattern Every AI Agent Needs - DEV Community](https://dev.to/askpatrick/the-escalation-rule-pattern-every-ai-agent-needs-and-most-skip-ph9)

### Financial Services
- [Maker-checker - Wikipedia](https://en.wikipedia.org/wiki/Maker-checker)
- [What CIOs in Finance Do to Navigate AI Agents - CIO](https://www.cio.com/article/4123497/what-cios-in-finance-do-to-navigate-ai-agents.html)
- [4-Eyes Policy for Approval Tasks - ServiceNow](https://www.servicenow.com/docs/bundle/xanadu-financial-services-operations/page/product/fso-card-operations/concept/implementing-4-eyes-principle.html)
- [2-Eyes, 4-Eyes, 6-Eyes Principle - ProcessMaker](https://www.processmaker.com/blog/2-eyes-4-eyes-6-eyes-principle/)
