from __future__ import annotations

from contextlib import contextmanager
from time import perf_counter

from prometheus_client import Counter, Gauge, Histogram

auth_events_total = Counter(
    "infrascope_auth_events_total",
    "Authentication and token-validation events.",
    ["result", "reason"],
)

scanner_runs_total = Counter(
    "infrascope_scanner_runs_total",
    "Network scanner run outcomes.",
    ["result"],
)

scanner_duration_seconds = Histogram(
    "infrascope_scanner_duration_seconds",
    "Duration of scanner runs.",
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300),
)

scanner_devices_found_total = Counter(
    "infrascope_scanner_devices_found_total",
    "Number of discovered devices from scanner runs.",
)

printer_polls_total = Counter(
    "infrascope_printer_polls_total",
    "Printer polling outcomes.",
    ["mode", "printer_type", "result"],
)

media_player_polls_total = Counter(
    "infrascope_media_player_polls_total",
    "Media player polling outcomes.",
    ["mode", "device_type", "result"],
)

media_player_ops_total = Counter(
    "infrascope_media_player_ops_total",
    "Media player operation outcomes.",
    ["operation", "result"],
)

switch_ops_total = Counter(
    "infrascope_switch_ops_total",
    "Network switch operation outcomes.",
    ["operation", "result"],
)

switch_port_ops_total = Counter(
    "infrascope_switch_port_ops_total",
    "Switch port operation outcomes.",
    ["vendor", "operation", "result"],
)

switch_port_op_duration_seconds = Histogram(
    "infrascope_switch_port_op_duration_seconds",
    "Duration of switch port operations.",
    ["vendor", "operation"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30),
)

snmp_operations_total = Counter(
    "infrascope_snmp_operations_total",
    "SNMP operation outcomes.",
    ["operation", "result", "reason"],
)

ssh_operations_total = Counter(
    "infrascope_ssh_operations_total",
    "SSH operation outcomes.",
    ["operation", "result", "reason"],
)

worker_tasks_enqueued_total = Counter(
    "infrascope_worker_tasks_enqueued_total",
    "Number of tasks enqueued for worker execution.",
    ["operation"],
)

worker_task_executions_total = Counter(
    "infrascope_worker_task_executions_total",
    "Worker task execution outcomes.",
    ["operation", "result"],
)

worker_task_duration_seconds = Histogram(
    "infrascope_worker_task_duration_seconds",
    "Duration of worker task execution.",
    ["operation"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300),
)

worker_tasks_in_progress = Gauge(
    "infrascope_worker_tasks_in_progress",
    "Current number of worker tasks in progress.",
    ["operation"],
)

worker_task_status_checks_total = Counter(
    "infrascope_worker_task_status_checks_total",
    "Task status API checks by state.",
    ["state"],
)

ml_train_runs_total = Counter(
    "infrascope_ml_train_runs_total",
    "Prediction training runs by model family and result.",
    ["model_family", "result"],
)

ml_train_duration_seconds = Histogram(
    "infrascope_ml_train_duration_seconds",
    "Duration of prediction training runs.",
    ["model_family"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300),
)

ml_inference_duration_seconds = Histogram(
    "infrascope_ml_inference_duration_seconds",
    "Duration of prediction scoring/inference runs.",
    ["operation"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30),
)

ml_predictions_total = Counter(
    "infrascope_ml_predictions_total",
    "Generated predictions by kind.",
    ["prediction_kind", "risk_level"],
)

ml_model_active_info = Gauge(
    "infrascope_ml_model_active_info",
    "Active prediction model info.",
    ["model_family", "version"],
)

network_bulk_operation_duration_seconds = Histogram(
    "infrascope_network_bulk_operation_duration_seconds",
    "Duration of bulk network operations.",
    ["operation"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300),
)

network_bulk_processed_total = Counter(
    "infrascope_network_bulk_processed_total",
    "Number of devices processed by bulk network operations.",
    ["operation", "result"],
)

network_discovery_runs_total = Counter(
    "infrascope_network_discovery_runs_total",
    "Discovery scan runs by kind and result.",
    ["kind", "result"],
)

network_discovery_devices_total = Counter(
    "infrascope_network_discovery_devices_total",
    "Devices identified by discovery scans.",
    ["kind"],
)

network_probe_attempts_total = Counter(
    "infrascope_network_probe_attempts_total",
    "Low-level network probe attempts by scope and result.",
    ["scope", "result"],
)

network_probe_duration_seconds = Histogram(
    "infrascope_network_probe_duration_seconds",
    "Duration of low-level network probe attempts.",
    ["scope", "result"],
    buckets=(0.01, 0.03, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)

poll_resilience_events_total = Counter(
    "infrascope_poll_resilience_events_total",
    "Polling resilience state machine and circuit breaker events.",
    ["kind", "event"],
)

devices_total = Gauge(
    "infrascope_devices_total",
    "Total number of configured devices by kind.",
    ["kind"],
)

devices_online = Gauge(
    "infrascope_devices_online",
    "Number of currently online devices by kind.",
    ["kind"],
)

service_edge_requests_total = Counter(
    "infrascope_service_edge_requests_total",
    "Service-to-service request outcomes.",
    ["source_service", "target_service", "transport", "operation", "result"],
)

service_edge_request_duration_seconds = Histogram(
    "infrascope_service_edge_request_duration_seconds",
    "Service-to-service request duration.",
    ["source_service", "target_service", "transport", "operation"],
    buckets=(0.01, 0.03, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30),
)


def set_device_counts(kind: str, total: int, online: int) -> None:
    devices_total.labels(kind=kind).set(max(total, 0))
    devices_online.labels(kind=kind).set(max(online, 0))


@contextmanager
def observe_duration(metric: Histogram):
    start = perf_counter()
    try:
        yield
    finally:
        metric.observe(max(perf_counter() - start, 0))


@contextmanager
def observe_service_edge(*, source: str, target: str, transport: str, operation: str):
    start = perf_counter()
    result = "success"
    try:
        yield
    except Exception:
        result = "error"
        raise
    finally:
        elapsed = max(perf_counter() - start, 0)
        service_edge_request_duration_seconds.labels(
            source_service=source,
            target_service=target,
            transport=transport,
            operation=operation,
        ).observe(elapsed)
        service_edge_requests_total.labels(
            source_service=source,
            target_service=target,
            transport=transport,
            operation=operation,
            result=result,
        ).inc()
