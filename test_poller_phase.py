from room_poller import RoomPoller


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload

    def get(self, url, timeout=10):
        return FakeResponse(self.payload)


def test_room_poller_filters_luckybag_rooms():
    poller = RoomPoller(endpoint='https://example.test', session=FakeSession({
        'rooms': [
            {'room_id': 1, 'red_packet_logo': 0, 'owner_nick': 'skip'},
            {'room_id': 2, 'red_packet_logo': 1, 'owner_nick': 'hit', 'bag_id': 999, 'task_gold': 250},
        ]
    }))

    result = poller.poll_once()
    assert len(result) == 1
    assert result[0].room_id == 2
    assert result[0].value == 250


def test_room_poller_handles_direct_payloads():
    poller = RoomPoller(endpoint='https://example.test', session=FakeSession({
        'room_id': 3,
        'red_packet_logo': 1,
        'owner_nick': 'direct',
        'bag_id': 777,
        'gold': 30,
    }))

    result = poller.poll_once()
    assert len(result) == 1
    assert result[0].bag_id == 777
    assert result[0].value == 30
