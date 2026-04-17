"""Concurrency tests for the persistence APIs.

The Swarm executor's :class:`concurrent.futures.ThreadPoolExecutor`
runs multiple foreground steps in parallel.  Each step's prompt
construction calls ``MemoryAPI.recall`` (and indirectly other APIs)
from a worker thread.  These tests pin down the contract that every
persistence API tolerates simultaneous access from many threads with
no ``sqlite3.ProgrammingError`` ("SQLite objects created in a thread
can only be used in that same thread") or data corruption.
"""

from __future__ import annotations

import gc
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

from swarm.context.api import SharedContextAPI
from swarm.experiments.api import ExperimentAPI
from swarm.memory.api import MemoryAPI
from swarm.messaging.api import MessageAPI
from swarm.registry.api import RegistryAPI

# ---------------------------------------------------------------------------
# MemoryAPI
# ---------------------------------------------------------------------------


class TestMemoryConcurrent:
    def test_ten_threads_store_simultaneously(self, tmp_path: Path) -> None:
        """10 threads each store a memory; all 10 rows must persist."""
        api = MemoryAPI(tmp_path / "mem.db")
        try:
            barrier = threading.Barrier(10)

            def worker(i: int) -> str:
                # Synchronize so all writers race the connection lock.
                barrier.wait()
                entry = api.store(
                    agent_name="agent-x",
                    content=f"memory-{i}",
                )
                return entry.id

            with ThreadPoolExecutor(max_workers=10) as pool:
                futures = [pool.submit(worker, i) for i in range(10)]
                ids = [f.result(timeout=10) for f in as_completed(futures)]

            # All inserts succeeded with unique IDs
            assert len(set(ids)) == 10
            # And all 10 rows are queryable
            assert api.count(agent_name="agent-x") == 10
            entries = api.recall("agent-x", limit=100)
            assert {e.content for e in entries} == {f"memory-{i}" for i in range(10)}
        finally:
            api.close()

    def test_recall_from_worker_thread_does_not_raise(self, tmp_path: Path) -> None:
        """Mirrors executor._build_agent_system_prompt usage from a worker."""
        api = MemoryAPI(tmp_path / "mem.db")
        try:
            api.store("agent-x", "seed")

            def worker() -> int:
                # Calling from a different thread than the one that
                # opened the API previously crashed with ProgrammingError.
                return len(api.recall("agent-x"))

            with ThreadPoolExecutor(max_workers=4) as pool:
                results = [f.result(timeout=5) for f in [
                    pool.submit(worker) for _ in range(8)
                ]]
            assert all(r == 1 for r in results)
        finally:
            api.close()

    def test_count_public_method(self, tmp_path: Path) -> None:
        """The new public count() method works without poking _conn."""
        api = MemoryAPI(tmp_path / "mem.db")
        try:
            assert api.count() == 0
            api.store("a", "one")
            api.store("a", "two")
            api.store("b", "three")
            assert api.count() == 3
            assert api.count(agent_name="a") == 2
            assert api.count(agent_name="b") == 1
        finally:
            api.close()


# ---------------------------------------------------------------------------
# RegistryAPI
# ---------------------------------------------------------------------------


class TestRegistryConcurrent:
    def test_search_during_concurrent_create_no_programming_error(
        self, tmp_path: Path,
    ) -> None:
        """5 reader threads + 1 writer thread on the same RegistryAPI."""
        api = RegistryAPI(tmp_path / "reg.db")
        try:
            stop = threading.Event()
            errors: list[BaseException] = []

            def writer() -> int:
                count = 0
                try:
                    for i in range(20):
                        api.create(
                            name=f"writer-{i}",
                            system_prompt=f"prompt {i}",
                            tools=[],
                            permissions=[],
                        )
                        count += 1
                finally:
                    stop.set()
                return count

            def reader() -> int:
                hits = 0
                while not stop.is_set():
                    try:
                        results = api.search("writer")
                        hits += len(results)
                    except BaseException as exc:  # noqa: BLE001
                        errors.append(exc)
                        return -1
                return hits

            with ThreadPoolExecutor(max_workers=6) as pool:
                w = pool.submit(writer)
                rs = [pool.submit(reader) for _ in range(5)]
                assert w.result(timeout=10) == 20
                for r in rs:
                    assert r.result(timeout=10) >= 0

            assert not errors, f"Reader threads raised: {errors!r}"
            assert api.count() == 20
        finally:
            api.close()

    def test_count_public_method(self, tmp_path: Path) -> None:
        api = RegistryAPI(tmp_path / "reg.db")
        try:
            assert api.count() == 0
            api.create(name="a", system_prompt="p", tools=[], permissions=[])
            api.create(name="b", system_prompt="p", tools=[], permissions=[])
            assert api.count() == 2
        finally:
            api.close()


# ---------------------------------------------------------------------------
# MessageAPI
# ---------------------------------------------------------------------------


class TestMessageConcurrent:
    def test_concurrent_send_and_receive(self, tmp_path: Path) -> None:
        api = MessageAPI(tmp_path / "msg.db")
        try:
            barrier = threading.Barrier(8)

            def worker(i: int) -> None:
                barrier.wait()
                api.send(
                    from_agent=f"agent-{i}",
                    to_agent="receiver",
                    content=f"hello-{i}",
                    run_id="run-1",
                )

            with ThreadPoolExecutor(max_workers=8) as pool:
                for f in as_completed(
                    [pool.submit(worker, i) for i in range(8)],
                ):
                    f.result(timeout=10)

            assert api.count(run_id="run-1") == 8
            received = api.receive("receiver", run_id="run-1", limit=100)
            assert {m.content for m in received} == {
                f"hello-{i}" for i in range(8)
            }
        finally:
            api.close()

    def test_count_public_method(self, tmp_path: Path) -> None:
        api = MessageAPI(tmp_path / "msg.db")
        try:
            assert api.count() == 0
            api.send("a", "b", "x", run_id="r1")
            api.send("a", "b", "y", run_id="r2")
            assert api.count() == 2
            assert api.count(run_id="r1") == 1
        finally:
            api.close()


# ---------------------------------------------------------------------------
# SharedContextAPI
# ---------------------------------------------------------------------------


class TestSharedContextConcurrent:
    def test_concurrent_set_and_get(self, tmp_path: Path) -> None:
        api = SharedContextAPI(tmp_path / "ctx.db")
        try:
            barrier = threading.Barrier(8)

            def writer(i: int) -> None:
                barrier.wait()
                api.set("run-1", f"key-{i}", f"value-{i}")

            with ThreadPoolExecutor(max_workers=8) as pool:
                for f in as_completed(
                    [pool.submit(writer, i) for i in range(8)],
                ):
                    f.result(timeout=10)

            data = api.get_all("run-1")
            assert len(data) == 8
            for i in range(8):
                assert data[f"key-{i}"] == f"value-{i}"
        finally:
            api.close()


# ---------------------------------------------------------------------------
# ExperimentAPI
# ---------------------------------------------------------------------------


class TestExperimentConcurrent:
    def test_concurrent_record_result(self, tmp_path: Path) -> None:
        api = ExperimentAPI(tmp_path / "exp.db")
        try:
            api.create("test-exp", agent_a="a1", agent_b="a2")
            barrier = threading.Barrier(8)

            def worker(i: int) -> None:
                barrier.wait()
                api.record_result(
                    "test-exp",
                    variant="A" if i % 2 == 0 else "B",
                    success=True,
                    duration_secs=0.1,
                )

            with ThreadPoolExecutor(max_workers=8) as pool:
                for f in as_completed(
                    [pool.submit(worker, i) for i in range(8)],
                ):
                    f.result(timeout=10)

            results = api.get_results("test-exp")
            assert results["variants"]["A"]["total_runs"] == 4
            assert results["variants"]["B"]["total_runs"] == 4
        finally:
            api.close()


# ---------------------------------------------------------------------------
# Stress test (executor-style mixed reads/writes)
# ---------------------------------------------------------------------------


class TestStressMixedReadsWrites:
    def test_eight_threads_fifty_iterations(self, tmp_path: Path) -> None:
        """8 worker threads, 50 mixed read/write ops each, no corruption."""
        memory = MemoryAPI(tmp_path / "mem.db")
        registry = RegistryAPI(tmp_path / "reg.db")
        messages = MessageAPI(tmp_path / "msg.db")
        try:
            barrier = threading.Barrier(8)
            errors: list[BaseException] = []

            def worker(thread_id: int) -> None:
                barrier.wait()
                try:
                    for i in range(50):
                        # Memory store + recall (mirrors executor prompt build)
                        memory.store(
                            agent_name=f"agent-{thread_id}",
                            content=f"thread{thread_id}-iter{i}",
                        )
                        recalled = memory.recall(
                            agent_name=f"agent-{thread_id}", limit=5,
                        )
                        assert len(recalled) > 0

                        # Registry write + read
                        if i % 5 == 0:
                            registry.create(
                                name=f"agent-{thread_id}-{i}",
                                system_prompt="stress",
                                tools=[],
                                permissions=[],
                            )
                        registry.search("stress")

                        # Messaging write + read
                        messages.send(
                            from_agent=f"agent-{thread_id}",
                            to_agent="*",
                            content=f"t{thread_id}i{i}",
                            run_id="stress-run",
                        )
                        messages.receive(
                            "any-receiver", run_id="stress-run", limit=10,
                        )
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)
                    raise

            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = [pool.submit(worker, t) for t in range(8)]
                for f in as_completed(futures):
                    f.result(timeout=60)

            assert not errors, f"Worker threads raised: {errors!r}"

            # Final consistency checks — exact counts because of barriers.
            assert memory.count() == 8 * 50
            # Registry: each thread created on iters 0,5,10,...,45 = 10 each.
            assert registry.count() == 8 * 10
            assert messages.count(run_id="stress-run") == 8 * 50
        finally:
            memory.close()
            registry.close()
            messages.close()


# ---------------------------------------------------------------------------
# close() closes every per-thread connection
# ---------------------------------------------------------------------------


def _open_in_threads(api: object, n: int) -> None:
    """Force *n* worker threads to each touch the API so the pool stores
    one connection per thread.

    Uses :meth:`_get_conn` directly — it is the documented way for the
    APIs to obtain a thread-bound connection.
    """
    barrier = threading.Barrier(n)

    def worker() -> None:
        barrier.wait()
        # Force a connection on this thread.
        conn = api._get_conn()  # type: ignore[attr-defined]
        # Use the connection so it is fully initialized.
        conn.execute("SELECT 1").fetchone()

    with ThreadPoolExecutor(max_workers=n) as pool:
        for f in as_completed([pool.submit(worker) for _ in range(n)]):
            f.result(timeout=5)


@pytest.mark.parametrize(
    "factory",
    [
        lambda p: MemoryAPI(p / "mem.db"),
        lambda p: RegistryAPI(p / "reg.db"),
        lambda p: MessageAPI(p / "msg.db"),
        lambda p: SharedContextAPI(p / "ctx.db"),
        lambda p: ExperimentAPI(p / "exp.db"),
    ],
    ids=["memory", "registry", "message", "context", "experiment"],
)
def test_close_closes_all_per_thread_connections(
    factory: object,
    tmp_path: Path,
) -> None:
    """``close()`` plus per-thread finalizers must drain the pool.

    Round 5 follow-up: every connection handed out by ``get()`` is now
    paired with a ``weakref.finalize`` keyed on the calling thread, so
    worker threads that exit without ``close_all`` being called still
    release their handle (preventing the 178 ResourceWarnings the
    earlier hardening pass missed).  The combination — eager
    finalizers for worker threads + ``close_all`` for the owning
    thread — must leave the tracked set empty.
    """
    api = factory(tmp_path)  # type: ignore[operator]
    try:
        _open_in_threads(api, n=4)
        # Worker threads have exited; their finalizers may already have
        # closed and deregistered those connections.  At minimum the
        # owning thread's connection is still tracked.
        gc.collect()
        assert api._pool.open_count() >= 1  # type: ignore[attr-defined]
    finally:
        api.close()

    # After close, the tracked set is empty.
    gc.collect()
    assert api._pool.open_count() == 0  # type: ignore[attr-defined]

    # And subsequent operations now raise (use-after-close surfaces
    # loudly rather than silently re-opening).
    with pytest.raises(sqlite3.ProgrammingError):
        api._get_conn()  # type: ignore[attr-defined]
