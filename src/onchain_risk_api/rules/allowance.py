from hashlib import sha256

from onchain_risk_api.domain.models import Erc20AllowanceEvidence, RiskFinding


def _finding(*, rule_id: str, evidence: Erc20AllowanceEvidence, summary: str) -> RiskFinding:
    identity = f"{rule_id}:v1:{evidence.evidence_id}"
    return RiskFinding(
        finding_id="finding:" + sha256(identity.encode()).hexdigest(),
        rule_id=rule_id,
        evidence_ids=[evidence.evidence_id],
        summary=summary,
    )


def evaluate_max_allowance(evidence: Erc20AllowanceEvidence) -> list[RiskFinding]:
    if int(evidence.allowance_smallest_unit) != 2**256 - 1:
        return []
    return [
        _finding(
            rule_id="ERC20_MAX_ALLOWANCE",
            evidence=evidence,
            summary=(
                "Maximum uint256 allowance observed. Review spender authority; "
                "this does not establish maliciousness."
            ),
        ),
    ]


def evaluate_nonzero_allowance(evidence: Erc20AllowanceEvidence) -> list[RiskFinding]:
    amount = int(evidence.allowance_smallest_unit)
    if amount == 0 or amount == 2**256 - 1:
        return []
    return [
        _finding(
            rule_id="ERC20_NONZERO_ALLOWANCE",
            evidence=evidence,
            summary=(
                "A finite non-zero allowance was observed. Review whether the "
                "spender still needs this authority; this does not establish maliciousness."
            ),
        ),
    ]


def evaluate_allowance_rules(evidence: Erc20AllowanceEvidence) -> list[RiskFinding]:
    return evaluate_max_allowance(evidence) + evaluate_nonzero_allowance(evidence)
