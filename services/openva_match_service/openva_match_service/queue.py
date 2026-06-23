"""Provider-neutral queue interface + in-memory implementation (WP-02C).

This is the ``queue`` provider interface required by hosted-deployment.yaml
``cross_cutting_execution_constraints.provider_interfaces``. It models the
Cloud-Tasks-shaped delivery the worker/reconciler rely on, but is provider-neutral:
the only durable adapter shipped here is in-memory (deterministic local tests). A real
Cloud Tasks adapter is a later, infrastructure-gated work package (NOT implemented here).

Faithful semantics modelled from the contract (``handoff``):
  - A task is NAMED. Generation 0 (the API's normal enqueue) uses ``task name == job_id``;
    recovery generation N uses ``handoff.recovery_task_name_template`` =
    ``{job_id}-r{dispatch_attempt}`` (a hyphen, never a colon — Cloud Tasks TASK_ID only
    permits ``[A-Za-z0-9_-]``). ``first_recovery_generation`` is 1; r0 is never reproduced.
  - Creating a task whose name is ALREADY PENDING returns "already exists" — idempotent
    dedup of the API's own enqueue retry (``enqueue_dedup``). We return ``False`` (no NEW
    task was created) WITHOUT error, so the caller treats it as accepted-existing.
  - A COMPLETED / DELETED task name is TOMBSTONED (Cloud Tasks keeps the name ~24h) and
    cannot be recreated under the SAME name. ``enqueue`` of a tombstoned name returns
    ``False`` too, but creates NO task — this is exactly the condition the reconciler
    recovers from by re-enqueueing under a FRESH ``-r{n}`` name (``on_name_tombstoned``).
  - Queue messages carry ONLY the ``job_id`` (``handoff``: queue messages carry job_id
    only / ``request_envelope.carried_in_queue: false``). The submitted request payload is
    NEVER in the queue; the worker reconstructs it from the transient request envelope.

Delivery model: a delivered task is a :class:`Delivery` carrying the ``job_id`` (and its
task name + dispatch_attempt for diagnostics). The worker ``ack``s a delivery on success
or ack-and-drop; the task name then becomes tombstoned (it cannot be recreated). This
mirrors Cloud Tasks where a 2xx from the handler deletes/acks the task.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass


def task_name(job_id: str, dispatch_attempt: int = 0) -> str:
    """Return the task name for a dispatch generation.

    Generation 0 (the API's normal enqueue) is the bare ``job_id``; recovery generation
    N (the reconciler's re-dispatch) is ``{job_id}-r{dispatch_attempt}`` per
    ``handoff.recovery_task_name_template``. ``first_recovery_generation`` is 1, so r0 is
    never produced here (a 0 generation is the un-suffixed name)."""
    if dispatch_attempt <= 0:
        return job_id
    return f"{job_id}-r{dispatch_attempt}"


@dataclass(frozen=True)
class Delivery:
    """A single delivered task. Carries ONLY the job_id (plus the task name and the
    dispatch generation for diagnostics) — never the submitted request payload, which the
    worker reconstructs from the transient request envelope (handoff: queue messages carry
    job_id only)."""

    job_id: str
    task_name: str
    dispatch_attempt: int


class Queue(ABC):
    """Provider-neutral task queue with Cloud-Tasks-shaped naming/dedup/tombstone
    semantics. The worker consumes deliveries via ``poll`` and ``ack``s them; the API and
    reconciler create tasks via ``enqueue``."""

    @abstractmethod
    def enqueue(self, job_id: str, *, dispatch_attempt: int = 0) -> bool:
        """Create a task named for ``(job_id, dispatch_attempt)``.

        Returns ``True`` iff a NEW pending task was created. Returns ``False`` (no error)
        when the name is already pending (idempotent dedup — accepted-existing) OR the name
        is tombstoned (completed/deleted; cannot be recreated). A ``False`` from a
        tombstoned name is the reconciler's signal to re-enqueue under a fresh ``-r{n}``
        generation."""
        ...

    @abstractmethod
    def poll(self) -> Delivery | None:
        """Return the next delivery to process, or ``None`` when the queue is idle.

        A polled task stays pending (in flight) until ``ack``ed; an un-acked delivery may
        be redelivered (the worker's CAS dedups a duplicate delivery)."""
        ...

    @abstractmethod
    def ack(self, delivery: Delivery) -> None:
        """Acknowledge a processed delivery: the task is removed and its NAME is tombstoned
        (it cannot be recreated under the same name, mirroring Cloud Tasks ~24h name
        retention). Idempotent: acking an unknown/already-acked delivery is a no-op."""
        ...

    @abstractmethod
    def pending_names(self) -> frozenset[str]:
        """Snapshot of the task names currently pending (created, not yet acked). For
        tests/diagnostics only."""
        ...


class InMemoryQueue(Queue):
    """In-memory, NON-DURABLE queue faithful to the dedup/tombstone semantics the
    reconciler relies on. Thread-safe (a lock guards the create-check-write and the FIFO),
    so it can be driven from a worker loop and concurrent reconcilers in tests."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # Names that have a pending (created, not-yet-acked) task.
        self._pending: set[str] = set()
        # Names that are tombstoned (acked/deleted) and cannot be recreated.
        self._tombstoned: set[str] = set()
        # FIFO of deliveries to hand out on poll().
        self._fifo: deque[Delivery] = deque()

    def enqueue(self, job_id: str, *, dispatch_attempt: int = 0) -> bool:
        name = task_name(job_id, dispatch_attempt)
        with self._lock:
            if name in self._pending:
                # ALREADY_EXISTS while pending: idempotent dedup of a retry — no new task.
                return False
            if name in self._tombstoned:
                # Completed/deleted name is tombstoned and cannot be recreated. The
                # reconciler recovers by enqueueing a fresh -r{n} generation name.
                return False
            self._pending.add(name)
            self._fifo.append(
                Delivery(job_id=job_id, task_name=name, dispatch_attempt=dispatch_attempt)
            )
            return True

    def poll(self) -> Delivery | None:
        with self._lock:
            while self._fifo:
                delivery = self._fifo.popleft()
                # Skip a delivery whose task was acked/tombstoned after it was queued.
                if delivery.task_name in self._pending:
                    return delivery
            return None

    def ack(self, delivery: Delivery) -> None:
        with self._lock:
            self._pending.discard(delivery.task_name)
            # Tombstone the name so it cannot be recreated (Cloud Tasks name retention).
            self._tombstoned.add(delivery.task_name)

    def pending_names(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._pending)

    def redeliver(self, delivery: Delivery) -> None:
        """Re-queue an in-flight (still-pending, un-acked) delivery for another poll.

        Models at-least-once redelivery (a worker crash before ack). Only re-queues while
        the task name is still pending — an acked/tombstoned task is never redelivered.
        Used by tests to exercise the worker's duplicate-delivery ack-and-drop path."""
        with self._lock:
            if delivery.task_name in self._pending:
                self._fifo.append(delivery)
