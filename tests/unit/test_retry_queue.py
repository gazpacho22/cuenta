"""Unit tests for the SQLite retry queue repository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from expense_bot.graph.state import RetryJob
from expense_bot.integrations.retry_queue import (
    RetryQueueError,
    RetryQueueRepository,
)


@pytest.fixture
def repo(tmp_path):
    """Provide a repository backed by a temporary SQLite file."""

    database = tmp_path / "retry.sqlite"
    repository = RetryQueueRepository(database)
    yield repository
    repository.close()


def make_job(thread_id: str, *, offset_minutes: int = 0) -> RetryJob:
    """Helper for building RetryJob instances in tests."""

    run_at = datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=offset_minutes)
    return RetryJob(
        thread_id=thread_id,
        payload={"journal_entry": thread_id},
        next_run_at=run_at,
    )


def test_enqueue_and_get_roundtrip(repo: RetryQueueRepository) -> None:
    job = make_job("thread-1")

    stored = repo.enqueue(job)
    fetched = repo.get(stored.id or -1)

    assert stored.id is not None
    assert fetched is not None
    assert fetched.id == stored.id
    assert fetched.thread_id == "thread-1"
    assert fetched.payload["journal_entry"] == "thread-1"
    assert fetched.attempts == 0


def test_acquire_due_job_respects_locking(repo: RetryQueueRepository) -> None:
    due_job = repo.enqueue(make_job("thread-due", offset_minutes=-5))
    future_job = repo.enqueue(make_job("thread-future", offset_minutes=10))

    now = datetime.now(UTC).replace(microsecond=0)
    acquired = repo.acquire_due_job("worker-a", now=now)

    assert acquired is not None
    assert acquired.id == due_job.id
    assert repo.acquire_due_job("worker-b", now=now) is None  # already locked

    repo.mark_failure(
        acquired.id,
        "worker-a",
        error="ERPNext outage",
        next_run_at=now + timedelta(minutes=1),
    )

    next_attempt = repo.acquire_due_job("worker-b", now=now + timedelta(minutes=2))
    assert next_attempt is not None
    assert next_attempt.id == due_job.id

    still_future = repo.acquire_due_job("worker-b", now=now + timedelta(seconds=30))
    assert still_future is None  # future job not due yet

    future_pickup = repo.acquire_due_job("worker-b", now=now + timedelta(minutes=15))
    assert future_pickup is not None
    assert future_pickup.id == future_job.id


def test_mark_failure_increments_attempts(repo: RetryQueueRepository) -> None:
    job = repo.enqueue(make_job("thread-failure", offset_minutes=-1))
    acquired = repo.acquire_due_job("worker-a")
    assert acquired is not None

    updated = repo.mark_failure(
        acquired.id,
        "worker-a",
        error="503",
        next_run_at=datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=5),
    )

    assert updated.attempts == 1
    assert updated.error == "503"
    reacquired = repo.acquire_due_job("worker-b", now=updated.next_run_at)
    assert reacquired is not None
    assert reacquired.id == job.id


def test_mark_success_removes_job(repo: RetryQueueRepository) -> None:
    job = repo.enqueue(make_job("thread-success", offset_minutes=-1))
    acquired = repo.acquire_due_job("worker-a")
    assert acquired is not None

    repo.mark_success(acquired.id, "worker-a")
    assert repo.get(job.id or -1) is None


def test_mark_failure_requires_matching_lock(repo: RetryQueueRepository) -> None:
    job = repo.enqueue(make_job("thread-lock", offset_minutes=-1))
    acquired = repo.acquire_due_job("worker-a")
    assert acquired is not None

    with pytest.raises(RetryQueueError):
        repo.mark_failure(
            acquired.id,
            "worker-b",
            error="wrong worker",
            next_run_at=datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=1),
        )
