import unittest

from deal_agent_platform.application.interfaces import ActivityPolicyInput
from deal_agent_platform.bootstrap import build_in_memory_platform
from deal_agent_platform.domain import ApprovalTier, ContextConfig, ReadinessGate, SourceMappings


class DealAgentScaffoldTests(unittest.TestCase):
    def _register_context(
        self,
        *,
        platform,
        context_id: str = "deal-abc-2026",
        approval_tier: ApprovalTier = ApprovalTier.SINGLE_APPROVAL,
        source_priority: dict[str, int] | None = None,
    ) -> None:
        platform.register_context(
            ContextConfig(
                context_id=context_id,
                name="Deal ABC",
                source_mappings=SourceMappings(
                    sharepoint_paths=["/sites/LoanOps/ABC-Revolver-2026/"],
                    email_aliases=["deal-abc@notices.internal.gs.com"],
                ),
                source_priority=source_priority or {"sharepoint": 10, "email": 20},
                readiness_gates={
                    "deal_structuring": ReadinessGate(
                        gate_id="deal_structuring",
                        requires_fields=["facility_amount", "maturity_date"],
                        min_confidence=0.7,
                        approval_tier=approval_tier,
                    )
                },
                tool_allowlist=["update_compliance_status", "search_deal_documents"],
                tool_denylist=["trigger_payment"],
                approval_tiers_by_action={
                    "update_compliance_status": ApprovalTier.SINGLE_APPROVAL
                },
            )
        )

    def test_bridge_workflow_and_approval_commit(self) -> None:
        platform = build_in_memory_platform()
        self._register_context(platform=platform)

        platform.ingest_raw_event(
            {
                "event_id": "evt-1",
                "source": "sharepoint",
                "event_type": "document_received",
                "payload": {
                    "path": "/sites/LoanOps/ABC-Revolver-2026/cert.pdf",
                    "document_ref": "sp://abc/cert.pdf",
                    "facts": {
                        "facility_amount": {"value": 50000000, "confidence": 0.95},
                        "maturity_date": {"value": "2028-03-15", "confidence": 0.9},
                    },
                    "metadata": {"content_hash": "hash-1"},
                },
            }
        )

        workflow = platform.workflows["deal-abc-2026"]
        results = workflow.run_until_idle()
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].skipped)
        self.assertEqual(len(platform.approval_gateway.pending), 1)

        bundle_id = next(iter(platform.approval_gateway.pending))
        workflow.on_approval_response(
            bundle_id=bundle_id,
            approved=True,
            approver="j.smith",
        )
        committed = platform.committed_store.get("deal-abc-2026")
        self.assertIn("facility_amount", committed.committed_fact_by_field)
        self.assertIn("maturity_date", committed.committed_fact_by_field)

    def test_duplicate_event_is_skipped(self) -> None:
        platform = build_in_memory_platform()
        self._register_context(platform=platform)

        raw = {
            "event_id": "evt-dup",
            "source": "sharepoint",
            "event_type": "document_received",
            "payload": {
                "path": "/sites/LoanOps/ABC-Revolver-2026/cert.pdf",
                "facts": {
                    "facility_amount": {"value": 50000000, "confidence": 0.95},
                    "maturity_date": {"value": "2028-03-15", "confidence": 0.9},
                },
            },
        }
        platform.ingest_raw_event(raw)
        platform.ingest_raw_event(raw)
        workflow = platform.workflows["deal-abc-2026"]
        results = workflow.run_until_idle()

        self.assertEqual(len(results), 2)
        self.assertFalse(results[0].skipped)
        self.assertTrue(results[1].skipped)
        self.assertEqual(results[1].skip_reason, "duplicate_event")

    def test_conflict_when_same_priority_and_different_values(self) -> None:
        platform = build_in_memory_platform()
        self._register_context(
            platform=platform,
            source_priority={"sharepoint": 10, "email": 10},
        )

        platform.ingest_raw_event(
            {
                "event_id": "evt-c1",
                "source": "sharepoint",
                "event_type": "document_received",
                "timestamp": "2026-03-22T10:00:00+00:00",
                "payload": {
                    "path": "/sites/LoanOps/ABC-Revolver-2026/cert-v1.pdf",
                    "facts": {"facility_amount": {"value": 50000000, "confidence": 0.9}},
                },
            }
        )
        platform.ingest_raw_event(
            {
                "event_id": "evt-c2",
                "source": "email",
                "event_type": "email_received",
                "timestamp": "2026-03-22T10:00:00+00:00",
                "payload": {
                    "mailbox_alias": "deal-abc@notices.internal.gs.com",
                    "facts": {"facility_amount": {"value": 70000000, "confidence": 0.9}},
                },
            }
        )

        workflow = platform.workflows["deal-abc-2026"]
        workflow.run_until_idle()
        status = workflow.get_status()
        self.assertIn("facility_amount", status["conflicts"])

    def test_auto_approve_gate_commits_without_human_signal(self) -> None:
        platform = build_in_memory_platform()
        self._register_context(platform=platform, approval_tier=ApprovalTier.AUTO_APPROVE)

        platform.ingest_raw_event(
            {
                "event_id": "evt-auto-1",
                "source": "sharepoint",
                "event_type": "document_received",
                "payload": {
                    "path": "/sites/LoanOps/ABC-Revolver-2026/cert.pdf",
                    "facts": {
                        "facility_amount": {"value": 50000000, "confidence": 0.95},
                        "maturity_date": {"value": "2028-03-15", "confidence": 0.91},
                    },
                },
            }
        )
        workflow = platform.workflows["deal-abc-2026"]
        workflow.run_until_idle()
        self.assertFalse(platform.approval_gateway.pending)
        committed = platform.committed_store.get("deal-abc-2026")
        self.assertIn("facility_amount", committed.committed_fact_by_field)

    def test_policy_engine_context_boundary(self) -> None:
        platform = build_in_memory_platform()
        self._register_context(platform=platform)

        decision = platform.policy_engine.evaluate(
            ActivityPolicyInput(
                tool_name="update_compliance_status",
                agent_context_id="deal-abc-2026",
                tool_args={"context_id": "deal-xyz-2026"},
            )
        )
        self.assertFalse(decision.allow)
        self.assertEqual(decision.reason, "context_boundary_violation")


if __name__ == "__main__":
    unittest.main()
