import app.services.kafka_events as kafka_events


def test_publish_event_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(kafka_events.settings, "KAFKA_ENABLED", False)
    monkeypatch.setattr(kafka_events, "_PRODUCER", None)
    kafka_events.publish_event({"event": "test"})


def test_publish_event_uses_existing_producer(monkeypatch):
    class _DummyProducer:
        def __init__(self):
            self.sent = []

        def send(self, topic, payload):
            self.sent.append((topic, payload))

    dummy = _DummyProducer()
    monkeypatch.setattr(kafka_events.settings, "KAFKA_ENABLED", True)
    monkeypatch.setattr(kafka_events.settings, "KAFKA_EVENT_TOPIC", "infrascope.events")
    monkeypatch.setattr(kafka_events, "_PRODUCER", dummy)

    kafka_events.publish_event({"event_type": "device_online"})

    assert len(dummy.sent) == 1
    assert dummy.sent[0][0] == "infrascope.events"
