from __future__ import annotations

import json

from deal_agent_platform.bootstrap import build_in_memory_platform
from deal_agent_platform.domain import ApprovalTier, ContextConfig, ReadinessGate, SourceMappings


def main() -> int:
    platform = build_in_memory_platform()
    context_id = "deal-abc-2026"
    platform.register_context(
        ContextConfig(
            context_id=context_id,
            name="Acme Revolver 2026",
            source_mappings=SourceMappings(
                sharepoint_paths=["/sites/LoanOps/ABC-Revolver-2026/"],
                email_aliases=["deal-abc@notices.internal.gs.com"],
            ),
            source_priority={"sharepoint": 10, "email": 30},
            readiness_gates={
                "deal_structuring": ReadinessGate(
                    gate_id="deal_structuring",
                    requires_fields=["facility_amount", "maturity_date"],
                    approval_tier=ApprovalTier.SINGLE_APPROVAL,
                    min_confidence=0.7,
                )
            },
            tool_allowlist=["search_deal_documents", "update_compliance_status"],
            tool_denylist=["trigger_payment"],
        )
    )

    raw_event = {
        "event_id": "evt-demo-1",
        "event_type": "document_received",
        "source": "sharepoint",
        "payload": {
            "path": "/sites/LoanOps/ABC-Revolver-2026/compliance_q1.pdf",
            "document_ref": "sp://sites/LoanOps/ABC-Revolver-2026/compliance_q1.pdf",
            "facts": {
                "facility_amount": {"value": 50000000, "confidence": 0.94},
                "maturity_date": {"value": "2028-03-15", "confidence": 0.91},
            },
            "metadata": {"content_hash": "hash-q1"},
        },
    }

    event = platform.ingest_raw_event(raw_event)
    workflow = platform.workflows[context_id]
    workflow.run_until_idle()
    status = workflow.get_status()
    print("Status after ingestion:")
    print(json.dumps(status, indent=2))

    pending = dict(platform.approval_gateway.pending)
    if pending:
        bundle_id = next(iter(pending))
        workflow.on_approval_response(
            bundle_id=bundle_id,
            approved=True,
            approver="j.smith",
            notes="approved in demo",
        )
        print(f"Approved bundle: {bundle_id}")
        print(json.dumps(workflow.get_status(), indent=2))
    else:
        print("No approval bundles generated.")

    print(f"Processed event: {event.event_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
