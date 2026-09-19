from __future__ import annotations

import pytest

from app.observability.metrics import worker_task_executions_total, worker_tasks_in_progress
from app.worker import tasks


def _count(operation: str, result: str) -> float:
    return worker_task_executions_total.labels(operation=operation, result=result)._value.get()


def _in_progress(operation: str) -> float:
    return worker_tasks_in_progress.labels(operation=operation)._value.get()


def _make(name: str, result, **options):
    def body(self):
        return result

    body.__name__ = f"{name}_body"
    return tasks._task(name, **options)(body)


def test_a_normal_return_is_a_success_with_the_standard_envelope() -> None:
    task = _make("deco_ok", {"total": 3})
    before = _count("deco_ok", "success")

    result = task.run()

    assert _count("deco_ok", "success") == before + 1
    assert result["total"] == 3
    assert result["operation"] == "deco_ok"
    assert {"task_id", "finished_at"} <= result.keys()
    assert _in_progress("deco_ok") == 0


def test_a_body_can_set_its_own_fields_over_the_envelope() -> None:
    task = _make("deco_own", {"finished_at": "custom"})

    assert task.run()["finished_at"] == "custom"


def test_skipped_and_failed_returns_get_their_own_metric_label() -> None:
    skipped = _make("deco_skip", tasks._Skipped({"status": "off"}))
    failed = _make("deco_fail", tasks._Failed({"status": "gone"}))

    assert skipped.run()["status"] == "off"
    assert failed.run()["status"] == "gone"

    assert _count("deco_skip", "skipped") == 1 and _count("deco_skip", "success") == 0
    assert _count("deco_fail", "error") == 1 and _count("deco_fail", "success") == 0


def test_an_exception_is_counted_and_still_propagates() -> None:
    def boom(self):
        raise RuntimeError("down")

    task = tasks._task("deco_boom")(boom)

    with pytest.raises(RuntimeError, match="down"):
        task.run()

    assert _count("deco_boom", "error") == 1
    assert _in_progress("deco_boom") == 0


def test_retries_are_opt_in() -> None:
    # hardware-touching and person-started tasks pass no `retries` and must not retry
    assert not getattr(tasks.ap_auto_reboot_switch_task, "autoretry_for", ())
    assert not getattr(tasks.switch_port_snapshot_cycle_task, "autoretry_for", ())
    assert tasks.poll_switch_task.autoretry_for == (Exception,)
    assert tasks.poll_switch_task.retry_kwargs == {"max_retries": 2}


def test_task_names_are_the_ones_beat_and_the_api_schedule() -> None:
    assert tasks.poll_all_switches_task.name == "tasks.poll_all_switches"
    assert tasks.ml_daily_cycle_task.name == "tasks.ml_daily_cycle"
    assert tasks.ap_auto_reboot_switch_task.name == "tasks.ap_auto_reboot_switch"
