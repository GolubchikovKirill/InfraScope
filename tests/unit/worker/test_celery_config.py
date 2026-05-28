from app.worker.celery_app import DEFAULT_QUEUE, celery_app


def test_celery_uses_redis_for_broker_and_backend():
    assert str(celery_app.conf.broker_url).startswith("redis://")
    assert str(celery_app.conf.result_backend).startswith("redis://")


def test_celery_has_production_safety_defaults():
    assert celery_app.conf.task_default_queue == DEFAULT_QUEUE
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert celery_app.conf.task_time_limit >= celery_app.conf.task_soft_time_limit
