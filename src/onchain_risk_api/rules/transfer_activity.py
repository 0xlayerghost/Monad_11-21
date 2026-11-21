from hashlib import sha256

from onchain_risk_api.domain.models import Erc20TransferEvent, RiskFinding

ZERO_ADDRESS = "0x" + "00" * 20


def _event_finding(
    *, rule_id: str, evidence_id: str, event: Erc20TransferEvent, summary: str,
) -> RiskFinding:
    identity = ":".join([
        rule_id, "v1", evidence_id, event.transaction_hash.lower(), str(event.log_index),
    ])
    return RiskFinding(
        finding_id="finding:" + sha256(identity.encode()).hexdigest(),
        rule_id=rule_id,
        evidence_ids=[evidence_id],
        summary=summary,
    )


def evaluate_transfer_activity(
    *, evidence_id: str, events: list[Erc20TransferEvent],
) -> list[RiskFinding]:
    findings: list[RiskFinding] = []
    for event in events:
        event_reference = f"transaction {event.transaction_hash}, log {event.log_index}"
        if event.from_address.lower() == ZERO_ADDRESS:
            findings.append(_event_finding(
                rule_id="ERC20_ZERO_ADDRESS_SOURCE",
                evidence_id=evidence_id,
                event=event,
                summary=(
                    f"A Transfer with the zero address as source was observed at "
                    f"{event_reference}. This is mint-like event evidence, not proof of "
                    "supply integrity, standard compliance or safety."
                ),
            ))
        if event.to_address.lower() == ZERO_ADDRESS:
            findings.append(_event_finding(
                rule_id="ERC20_ZERO_ADDRESS_DESTINATION",
                evidence_id=evidence_id,
                event=event,
                summary=(
                    f"A Transfer with the zero address as destination was observed at "
                    f"{event_reference}. This is burn-like event evidence, not proof of "
                    "supply reduction, standard compliance or safety."
                ),
            ))
    return findings
