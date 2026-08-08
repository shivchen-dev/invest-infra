from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from invest_api.application.research import ResearchQueryError, ResearchQueryService
from invest_api.schemas.research import EvidenceFactorResponse, EvidencePackResponse
from sqlalchemy.exc import OperationalError


def test_public_evidence_contract_omits_internal_metadata():
    fields = set(EvidencePackResponse.model_fields)

    assert {"workspace_path", "e2a_request_id", "e2a_session_id"}.isdisjoint(fields)


def test_factor_unit_is_explicit_in_public_contract():
    unit_schema = EvidenceFactorResponse.model_json_schema()["properties"]["unit"]

    assert "unit supplied by the frozen factor contract" in unit_schema["description"]


def test_list_cases_delegates_bounded_page_and_exact_count():
    repository = Mock()
    cases = [SimpleNamespace(case_id=uuid4())]
    repository.list_recent.return_value = cases
    repository.count_all.return_value = 7

    page, total = ResearchQueryService(repository, Mock(), Mock(), Mock()).list_cases(
        limit=25, offset=10
    )

    assert page == cases
    assert total == 7
    repository.list_recent.assert_called_once_with(limit=25, offset=10)
    repository.count_all.assert_called_once_with()


def test_query_service_translates_sqlalchemy_errors_without_details():
    repository = Mock()
    repository.get.side_effect = OperationalError("select", {}, Exception("password=secret"))

    with pytest.raises(ResearchQueryError, match="research query failed") as error:
        ResearchQueryService(repository, Mock(), Mock(), Mock()).get_case(uuid4())

    assert "password" not in str(error.value)


def test_get_evidence_requires_case_and_returns_packs():
    case_id = uuid4()
    pack = SimpleNamespace(pack_id=uuid4())
    cases = Mock()
    cases.get.return_value = SimpleNamespace(case_id=case_id)
    evidence = Mock()
    evidence.list_by_case.return_value = [pack]

    service = ResearchQueryService(cases, evidence, Mock(), Mock())

    assert service.get_case_evidence(case_id) == [pack]
    evidence.list_by_case.assert_called_once_with(case_id)


def test_get_result_requires_run_and_returns_result():
    run_id = uuid4()
    result = SimpleNamespace(result_id=uuid4())
    runs = Mock()
    runs.get.return_value = SimpleNamespace(run_id=run_id)
    results = Mock()
    results.get_by_run_id.return_value = result

    service = ResearchQueryService(Mock(), Mock(), runs, results)

    assert service.get_run_result(run_id) is result
    results.get_by_run_id.assert_called_once_with(run_id)
