from resilience import ProtocolDriftDetector, classify_failure, score_opportunity
from speed_scheduler import BagOpportunity


def test_classify_failure_maps_known_error_strings():
    assert classify_failure("Luckybag habis masa berlakunya") == "expired"
    assert classify_failure("room not found") == "room_missing"


def test_protocol_drift_detector_flags_missing_fields():
    detector = ProtocolDriftDetector()
    assert detector.detect({"op": 2101, "body": {"Code": 1012}}) is True
    assert detector.detect({"op": 2101, "body": {"Code": 0, "ErrStr": "", "ID": 999, "Gold": 5, "IsBlack": 0}}) is False


def test_score_opportunity_uses_value_freshness_and_worker_count():
    bag = BagOpportunity(room_id=123, bag_id=999, bag_value=25, discovered_at=1234567890, source="manual")
    score = score_opportunity(bag, worker_count=2)
    assert score > 0
