"""Completed operations must not accumulate in _operations (only in history)."""
import time
import unittest
from src.plugin_system.operation_queue import PluginOperationQueue
from src.plugin_system.operation_types import OperationType, OperationStatus


class TestOperationQueueEviction(unittest.TestCase):
    """Test that completed ops are evicted from _operations index."""

    def setUp(self):
        self.queue = PluginOperationQueue(max_history=50)

    def tearDown(self):
        self.queue.shutdown()

    def test_completed_ops_evicted_from_index(self):
        """Ops executed via callback must be absent from _operations after completion."""
        ids = []
        for i in range(5):
            op_id = self.queue.enqueue_operation(
                operation_type=OperationType.INSTALL,
                plugin_id=f"evict-test-plugin-{i}",
                parameters={},
                operation_callback=lambda op: {"message": "done", "success": True},
            )
            ids.append(op_id)

        # Wait for the worker thread to drain the queue.
        # join() blocks until all task_done() calls match get() calls.
        self.queue._operation_queue.join()

        for op_id in ids:
            self.assertNotIn(
                op_id,
                self.queue._operations,
                f"op {op_id} should have been evicted from _operations after completion",
            )

    def test_completed_ops_still_in_history(self):
        """Evicted ops must still be retrievable via _operation_history."""
        op_id = self.queue.enqueue_operation(
            operation_type=OperationType.INSTALL,
            plugin_id="evict-history-plugin",
            parameters={},
            operation_callback=lambda op: {"message": "done", "success": True},
        )

        self.queue._operation_queue.join()

        history_ids = {op.operation_id for op in self.queue._operation_history}
        self.assertIn(op_id, history_ids, "completed op must remain in _operation_history")

    def test_get_operation_status_falls_back_to_history(self):
        """get_operation_status must find completed ops via history fallback."""
        op_id = self.queue.enqueue_operation(
            operation_type=OperationType.INSTALL,
            plugin_id="evict-status-plugin",
            parameters={},
            operation_callback=lambda op: {"message": "done", "success": True},
        )

        self.queue._operation_queue.join()

        # After eviction, status lookup must still return the operation
        result = self.queue.get_operation_status(op_id)
        self.assertIsNotNone(result, "get_operation_status must fall back to history")
        self.assertEqual(result.status, OperationStatus.COMPLETED)

    def test_cancelled_ops_evicted_from_index(self):
        """Cancelled ops must also be evicted from _operations."""
        # Enqueue without a callback so it parks as PENDING in the queue;
        # cancel before the worker drains it.  Because there's no callback
        # the worker would complete it almost immediately, so we must cancel
        # synchronously under the lock before the worker grabs it.
        op_id = self.queue.enqueue_operation(
            operation_type=OperationType.INSTALL,
            plugin_id="evict-cancel-plugin",
            parameters={},
        )

        # cancel_operation checks PENDING status; it may already be running,
        # so accept either True (cancelled) or False (already executing).
        self.queue.cancel_operation(op_id)

        # Either way, wait for the queue to drain fully.
        self.queue._operation_queue.join()

        self.assertNotIn(
            op_id,
            self.queue._operations,
            "cancelled op should be evicted from _operations",
        )


if __name__ == "__main__":
    unittest.main()
